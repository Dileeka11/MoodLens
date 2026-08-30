# MoodLens

Mood-based movie recommendations. You describe how you feel in plain English; a
hybrid of a pre-trained **Neural Collaborative Filtering** model and **SBERT**
sentence embeddings picks five films and explains each one.

```
hybrid score = 0.7 × normalised NCF score + 0.3 × normalised SBERT cosine similarity
```

Everything runs locally. No external AI APIs.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy 2.0, PyMySQL |
| Database | MySQL / MariaDB |
| Frontend | React 18 + Vite, React Router, axios |
| Collaborative filtering | PyTorch, pre-trained NCF (6040 users × 3706 movies, 50-dim) |
| Semantic matching | sentence-transformers, `all-MiniLM-L6-v2` (384-dim, runs on CPU) |
| Auth | JWT (python-jose) + bcrypt (passlib) |

---

## Prerequisites

- **Python 3.10+** (developed on 3.11)
- **Node.js 18+** (developed on 24)
- **MySQL 8 or MariaDB 10.4+** — XAMPP is fine
- ~3 GB free disk for PyTorch and the SBERT model

These four artifacts must sit in the project root:

```
ncf_model.pth      trained NCF weights (state_dict)
movie2idx.pkl      MovieLens movieId -> model index   (3706 entries)
user2idx.pkl       MovieLens userId  -> model index   (6040 entries)
movies.csv         movieId, title, genres            (3883 rows)
```

---

## Setup

### 1. Database

Start MySQL, then create the schema:

```bash
"C:\xampp\mysql\bin\mysql.exe" -u root < sql/schema.sql
```

On macOS/Linux: `mysql -u root -p < sql/schema.sql`

This creates the `moodlens` database and all six tables (`users`, `movies`,
`ratings`, `recommendations`, `watchlist`, `password_resets`). `sql/schema.sql`
is the single source of truth for the schema. The script is re-runnable — it
drops the tables first, so **it will erase existing data**.

### 2. Backend

```bash
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

macOS/Linux: `venv/bin/pip install -r requirements.txt`

Use a virtualenv. The pins (`numpy<2`, `bcrypt==4.0.1`) will downgrade a global
Python install and break unrelated projects.

Copy the environment template and edit if your MySQL credentials differ:

```bash
copy .env.example .env
```

Generate a real JWT secret before deploying anywhere:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Load the movie catalogue, then create your admin account:

```bash
venv\Scripts\python -m app.scripts.seed_movies
```

```bash
venv\Scripts\python -m app.scripts.create_admin
```

`create_admin` prompts for a password (minimum 8 characters) and defaults to
`admin@moodlens.app`. Do **not** use a `.local` or `.localhost` address —
the email validator rejects special-use domains and the account could not log in.

### 3. Run everything

From the **project root**, one command starts the backend and the frontend
together:

```bash
npm run setup
```

```bash
npm run dev
```

```
[backend]  Uvicorn running on http://127.0.0.1:8001
[frontend] Local: http://localhost:5180/
```

Open **http://localhost:5180**. Ctrl+C stops both.

`npm run dev` works from the `frontend/` folder too — it delegates to the root
script, so you never end up with only half the stack running.

Ports default to **8001** and **5180** because 8000 and 5173 are commonly taken
by other local projects. Override with `BACKEND_PORT`, `FRONTEND_PORT`, or
`VITE_API_TARGET`.

To run just one side:

```bash
npm run dev:backend
```

```bash
npm run dev:frontend
```

**First boot takes 1–2 minutes** — SBERT encodes all 3706 movies. The result is
cached to `backend/cache/`, and later boots take about 15 seconds. API docs are
at http://localhost:8001/docs.

### 4. Posters, synopses and runtimes (optional)

`movies.csv` ships only titles and genres. To fill in artwork, synopses and
runtimes, get a **free TMDB key** at
https://www.themoviedb.org/settings/api (sign up, then API → Developer), add it
to `backend/.env`:

```
TMDB_API_KEY=your_key_here
```

Try a small batch first, then run the rest:

```bash
cd backend && venv\Scripts\python -m app.scripts.backfill_tmdb --limit 50
```

```bash
cd backend && venv\Scripts\python -m app.scripts.backfill_tmdb
```

The full run covers 3883 films and takes roughly 15-25 minutes. It is
resumable — rows that already have a `tmdb_id` are skipped, so you can stop it
and re-run.

This is the only part of MoodLens that contacts an external service, and it
fetches catalogue metadata only. Recommendations are always computed locally.

Once runtimes exist, the **time_available filter starts working** and the
`~1hr` / `~2hrs` options actually narrow the results.

MovieLens titles need rewriting before they can be looked up — it stores
`"Matrix, The (1999)"` and `"Postino, Il (The Postman) (1994)"`. The script
moves the trailing article and falls back to alternate titles; 1094 of the 3883
titles need this.

### 5. Films released after 2000 (optional)

MovieLens 1M stops at 2000, and the NCF checkpoint only knows those 3706
films. To add newer releases (needs a `TMDB_API_KEY`, as in step 4):

```bash
cd backend && venv\Scripts\python -m app.scripts.import_recent --from 2001 --to 2026
```

Useful flags: `--per-year 60` caps how many films per year, `--min-votes 800`
skips obscure titles. Imported rows get `source='tmdb'` and ids from 100000 up,
so they can never collide with a MovieLens id. Restart the backend afterwards —
the catalogue and the content bridge are built once at startup.

---

## How a recommendation is built

1. **NCF** scores all 3706 trained movies for the user in one batched forward
   pass, in `eval()` mode so dropout is off and scores are reproducible.
2. **SBERT** encodes the mood text and takes the cosine similarity against the
   cached movie embeddings. Each movie's embedding comes from its title, its
   genres, and a fixed mood-vocabulary expansion (`Sci-Fi` → *"futuristic, mind
   bending, cerebral, speculative, technology, space"*), which is what lets a
   query like *"dark and mind-blowing"* match anything at all.
3. Both score vectors are **min-max normalised to 0–1** before blending. Raw
   NCF output clusters in a narrow band while cosine sits near zero; without
   normalising, NCF would dominate far past its 0.7 share.
4. Films the user already rated are removed. `time_available` caps runtime, but
   only for films whose runtime is known. `watching_with` applies small genre
   adjustments (`Family` scores Horror at −0.60, effectively removing it).
5. The top 5 get **template-based explanations** and are written to
   `recommendations` with the mood text, both component scores, and the text.

### Films the model was never trained on

The checkpoint has embeddings for exactly 3706 films. Anything newer — a TMDB
import, an admin entry — has none, so the collaborative model cannot score it.
Retraining is out of scope, so the **content bridge**
(`services/bridge.py`) borrows a score instead:

1. Find the film's nearest neighbours among the 3706 trained films in SBERT space.
2. Estimate its NCF score as the similarity-weighted mean of those neighbours'
   scores for this user, with weights ∝ cosine⁴ so the closest dominate.
3. Rescale the estimates to the same mean and spread as the real scores.

Step 3 is not cosmetic. Averaging compresses variance — a mean of k scores can
never reach the extremes the individual scores do — so without rescaling **no
post-2000 film ever ranked**, no matter how well it matched. Distribution
matching undoes that artefact without inventing signal.

Estimates are labelled everywhere they surface: the API returns
`score_source: "estimated"`, the explanation says the film is too recent for
the ratings model, and the UI marks the card. An estimate is never presented
as a model prediction.

### Cold start

App users are not MovieLens users, so a new account has no NCF embedding.
`users.ncf_user_index` is `NULL` and the recommender falls back to a
**population prior**: the mean NCF score over 256 seeded trained users. The API
returns `personalised: false` and the explanations say so rather than implying
personalisation that does not exist.

Onboarding writes seed rows into `ratings` with `source='onboarding'`, choosing
the highest-prior films in the chosen genres. Explanations distinguish these
from real ratings ("Your starter picks lean Crime" vs "You've rated Crime films
4.5 on average").

---

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/register` | — | Create account, returns JWT |
| POST | `/login` | — | Sign in, returns JWT |
| GET | `/me` | user | Current account |
| GET | `/onboarding/questions` | — | The 5 questions |
| POST | `/onboarding` | user | Submit answers, seed profile |
| POST | `/recommend` | user | `{mood_text, watching_with, time_available}` → top 5 |
| POST | `/rate` | user | `{movie_id, rating_value}` (0.5–5.0, half steps) |
| GET | `/ratings` | user | Your ratings |
| GET | `/movie/{id}` | user | Full detail + your rating + last explanation |
| GET | `/movies?q=` | user | Title search |
| GET | `/history` | user | Past recommendations |
| GET | `/admin/stats` | admin | Dashboard counters |
| GET/POST/PUT/DELETE | `/admin/movies` | admin | Movie CRUD |
| GET/POST/DELETE | `/admin/users` | admin | User management |
| GET | `/admin/model` | admin | Model status, RMSE, checkpoint date |
| POST | `/admin/model/retrain` | admin | **Evaluates** the checkpoint (see below) |
| GET | `/browse` | user | Filtered catalogue: genre, year range, rating, sort |
| GET | `/movie/{id}/similar` | user | SBERT nearest neighbours |
| GET/POST/DELETE | `/watchlist` | user | Saved / watched / not-interested |
| GET | `/profile` | user | Taste analytics for the dashboard |
| GET | `/admin/model/metrics` | admin | RMSE, MAE, Precision@K, NDCG@K |
| GET | `/health` | — | Liveness + model status |

---

## Screens

1. **Login / Register** — email + password, Create New Account, forgot-password link
2. **Mood Input** — free-text area, watching-with and time-available dropdowns, Find My Movies
3. **Recommendations** — five cards with poster, stars, runtime, genres, italic explanation, inline Rate and Details
4. **Onboarding** — one question at a time, progress bar, 4 options, Next / Skip
5. **Movie Details** — poster left, metadata right, Rate This Movie, "Why we chose this" panel, synopsis
6. **Admin Dashboard** — 3 stat cards, model panel, searchable movie table with Add / Edit / Delete
7. **History** — past recommendations grouped by search
8. **Browse** — full catalogue with genre / year / rating filters and sorting
9. **My list** — want-to-watch, watched, and dismissed titles
10. **Your taste** — genre affinity, rating distribution, eras, mood-word cloud

All screens support light and dark themes; the toggle in the nav cycles
system → dark → light and persists.

---

## Known limitations

These are real constraints of the shipped data, not bugs.

**No posters, synopses, or runtimes out of the box.** `movies.csv` has only
`movieId, title, genres`. Run the TMDB backfill above to fill them in. Posters fall back to a generated initials tile, the synopsis panel
explains its absence, and runtime shows "not on file". The schema has
`poster_url`, `overview`, `runtime_minutes` and `tmdb_id` columns for an admin
to fill in. Because runtime is unknown, the `time_available` filter currently
matches nothing — it is wired up and will apply as soon as runtimes exist.

**177 movies cannot be recommended.** `movies.csv` has 3883 titles but the model
was trained on 3706. The remaining 177 were never rated in the training set and
have no embedding. They are browsable and rateable but excluded from ranking;
their detail page says so.

**The era preference does not affect ranking.** Onboarding question 3 steers
which films get *seeded* but is not persisted, so it does not bias later
recommendations. Fixing it properly needs a stored preference column.

**SBERT partly matches title words.** *"dark"* can still pull in *Tales from
the Darkside* by title rather than tone. The release year is stripped before
encoding — leaving it in made similarity return only films from the same
year — but title words still carry weight. NCF's 0.7 share limits the damage.

**The 0.7 weighting favours older films.** Every app user has
`ncf_user_index = NULL`, so 70% of every score comes from the same population
prior — and that prior rates acclaimed older films highest. A modern
blockbuster can match a mood almost perfectly and still rank low: for
*"a superhero blockbuster"*, The Batman (2022) scores 0.85 on mood but 0.47 on
the prior, landing at #2184 while Star Wars takes #1. The mood term simply
cannot outvote a term with 2.3x its weight. Options: lower `NCF_WEIGHT` in
`.env`, or map users onto a real NCF user embedding so the collaborative term
becomes personal.

**Mood text must be English.** `all-MiniLM-L6-v2` is English-only: Sinhala
input produces a near-identical vector for every query. Switch `SBERT_MODEL`
in `.env` to `paraphrase-multilingual-MiniLM-L12-v2` for 50+ languages, then
clear `backend/cache/` to re-encode. Explanations remain English (templates).

**Accuracy needs a ratings file.** `/admin/model/metrics` computes RMSE, MAE,
Precision@5 and NDCG@5 against MovieLens ground truth, but that file is not
shipped here. Drop `ratings.dat` (ml-1m) or `ratings.csv` beside the model
artifacts and the Accuracy panel starts working. Without it the endpoint
reports `available: false` rather than inventing numbers.

**"Retrain NCF Model" does not retrain.** The model is served as-is by design.
The button calls an **evaluation** that scores the existing checkpoint against
your users' real ratings and records the RMSE; weights are never modified, and
the dashboard says so. It needs at least one user with a non-NULL
`ncf_user_index`, otherwise it reports that nothing was evaluable. RMSE assumes
the sigmoid output maps to `rating / 5`; if training used a different target
scale, change `RATING_SCALE` in `app/services/model_meta.py`.

---

## Project layout

```
MoodLens/
├── ncf_model.pth, movie2idx.pkl, user2idx.pkl, movies.csv
├── sql/schema.sql
├── backend/
│   ├── requirements.txt, .env.example
│   └── app/
│       ├── config.py, database.py, models.py, schemas.py, auth.py, main.py
│       ├── routers/    auth_routes, onboarding, recommend, ratings, movies, history, admin
│       ├── services/   ncf_service, sbert_service, model_registry, recommender,
│       │               explainer, onboarding, model_meta
│       └── scripts/    seed_movies, create_admin
└── frontend/
    └── src/
        ├── api/client.js, context/AuthContext.jsx, components/Common.jsx
        ├── pages/  Login, MoodInput, Recommendations, Onboarding,
        │           MovieDetails, AdminDashboard, History
        └── styles/global.css
```

---

## Troubleshooting

**`Keras 3 ... not supported in Transformers`** — TensorFlow is installed and
`transformers` tries to load its TF backend. Already handled: `sbert_service`
sets `USE_TF=0` before importing. If you hit it elsewhere, set that env var.

**`Can't connect to MySQL`** — check MySQL is running and that `DB_USER` /
`DB_PASSWORD` in `backend/.env` match. XAMPP defaults to `root` with an empty
password.

**`/recommend` returns 503** — model warm-up failed. Check the startup log; the
usual cause is a missing artifact. `GET /health` shows what loaded.

**Recommendations feel generic** — expected until you rate films. Everyone
starts on the population prior; `personalised: false` in the response confirms it.

**Stale embeddings after editing titles/genres** — delete `backend/cache/` and
restart to re-encode.
