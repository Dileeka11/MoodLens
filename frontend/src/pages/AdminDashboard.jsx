import { useCallback, useEffect, useRef, useState } from 'react';
import client, { errorMessage } from '../api/client';
import { Alert, CountUp, Spinner } from '../components/Common';

function SyncBar({ state, matched, missed }) {
  const pct = state.total > 0 ? Math.round((state.done / state.total) * 100) : 0;
  return (
    <div>
      {(state.running || state.done > 0) && (
        <>
          <div style={{
            height: 6, borderRadius: 3, background: 'var(--surface-2)',
            overflow: 'hidden', marginBottom: 6,
          }}>
            <div style={{
              height: '100%', width: `${pct}%`,
              background: 'var(--accent)', borderRadius: 3,
              transition: 'width .4s',
            }} />
          </div>
          <p className="muted tiny" style={{ margin: 0 }}>
            {state.done} / {state.total} ({pct}%)
            {state[matched] > 0 && <> · {state[matched]} {matched}</>}
            {state[missed] > 0 && <> · {state[missed]} {missed}</>}
          </p>
        </>
      )}
      {state.error && <p className="tiny" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>{state.error}</p>}
      {!state.running && state.finished_at && (
        <p className="muted tiny" style={{ margin: '4px 0 0' }}>
          Done · {new Date(state.finished_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}

const EMPTY_MOVIE = {
  title: '', genres: '', release_year: '', runtime_minutes: '',
  poster_url: '', overview: '', tmdb_id: '',
};

/** Screen 6 — admin dashboard. */
export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [model, setModel] = useState(null);
  const [movies, setMovies] = useState({ items: [], total: 0, page: 1, per_page: 20 });
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(null);      // movie object or EMPTY_MOVIE
  const [evaluating, setEvaluating] = useState(false);
  const [metrics, setMetrics] = useState(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [sync, setSync] = useState(null);
  const syncPollRef = useRef(null);

  const loadMovies = useCallback(async () => {
    const { data } = await client.get('/admin/movies', { params: { q: query, page, per_page: 20 } });
    setMovies(data);
  }, [query, page]);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      client.get('/admin/stats').then(({ data }) => setStats(data)),
      client.get('/admin/model').then(({ data }) => setModel(data)),
      client.get('/admin/sync/status').then(({ data }) => setSync(data)),
      loadMovies(),
    ])
      .catch((err) => setError(errorMessage(err, 'Could not load the dashboard')))
      .finally(() => setLoading(false));
  }, [loadMovies]);

  // Poll sync status every 2 s while any job is running.
  useEffect(() => {
    const anyRunning = sync?.posters?.running || sync?.recent?.running;
    if (anyRunning && !syncPollRef.current) {
      syncPollRef.current = setInterval(async () => {
        try {
          const { data } = await client.get('/admin/sync/status');
          setSync(data);
          if (!data.posters.running && !data.recent.running) {
            clearInterval(syncPollRef.current);
            syncPollRef.current = null;
            // Refresh movie count once sync finishes.
            const { data: s } = await client.get('/admin/stats');
            setStats(s);
          }
        } catch { /* ignore */ }
      }, 2000);
    }
    if (!anyRunning && syncPollRef.current) {
      clearInterval(syncPollRef.current);
      syncPollRef.current = null;
    }
    return () => {};
  }, [sync?.posters?.running, sync?.recent?.running]);

  // Debounce the search so each keystroke does not hit the API.
  useEffect(() => {
    const t = setTimeout(() => {
      loadMovies().catch((err) => setError(errorMessage(err)));
    }, 300);
    return () => clearTimeout(t);
  }, [query, page, loadMovies]);

  async function saveMovie(e) {
    e.preventDefault();
    setError('');
    const payload = {
      title: editing.title,
      genres: editing.genres || '',
      overview: editing.overview || null,
      poster_url: editing.poster_url || null,
      release_year: editing.release_year ? Number(editing.release_year) : null,
      runtime_minutes: editing.runtime_minutes ? Number(editing.runtime_minutes) : null,
      tmdb_id: editing.tmdb_id ? Number(editing.tmdb_id) : null,
    };
    try {
      if (editing.movie_id) await client.put(`/admin/movies/${editing.movie_id}`, payload);
      else await client.post('/admin/movies', payload);
      setEditing(null);
      await loadMovies();
      const { data } = await client.get('/admin/stats');
      setStats(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save the movie'));
    }
  }

  async function remove(movie) {
    if (!window.confirm(`Delete "${movie.title}"? Its ratings and recommendations go too.`)) return;
    try {
      await client.delete(`/admin/movies/${movie.movie_id}`);
      await loadMovies();
      const { data } = await client.get('/admin/stats');
      setStats(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not delete the movie'));
    }
  }

  async function reevaluate() {
    setEvaluating(true);
    setError('');
    try {
      const { data } = await client.post('/admin/model/retrain');
      setModel(data);
    } catch (err) {
      setError(errorMessage(err, 'Evaluation failed'));
    } finally {
      setEvaluating(false);
    }
  }

  async function startSync(kind) {
    setError('');
    try {
      await client.post(`/admin/sync/${kind}`);
      const { data } = await client.get('/admin/sync/status');
      setSync(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not start sync'));
    }
  }

  async function loadMetrics() {
    setMetricsLoading(true);
    setError('');
    try {
      const { data } = await client.get('/admin/model/metrics', { params: { k: 5 } });
      setMetrics(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not run the evaluation'));
    } finally {
      setMetricsLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="center-screen">
        <Spinner accent />
      </div>
    );
  }

  const pages = Math.max(1, Math.ceil(movies.total / movies.per_page));

  return (
    <div className="page">
      <h1>Admin dashboard</h1>
      <Alert kind="error">{error}</Alert>

      <div className="stat-grid" style={{ marginTop: 24 }}>
        <div className="stat">
          <div className="stat__value">{stats ? <CountUp value={stats.users} /> : '—'}</div>
          <div className="stat__label">Users</div>
        </div>
        <div className="stat">
          <div className="stat__value">{stats ? <CountUp value={stats.movies} /> : '—'}</div>
          <div className="stat__label">Movies</div>
        </div>
        <div className="stat">
          <div className="stat__value">{stats ? <CountUp value={stats.ratings} /> : '—'}</div>
          <div className="stat__label">Ratings</div>
        </div>
      </div>

      {/* --- model panel --- */}
      <div className="card" style={{ marginTop: 28 }}>
        <div className="row row--between">
          <div>
            <h2 style={{ marginBottom: 4 }}>NCF model</h2>
            <p className="muted small" style={{ margin: 0 }}>
              Checkpoint dated{' '}
              <strong>
                {model?.last_trained ? new Date(model.last_trained).toLocaleDateString() : 'unknown'}
              </strong>
              {' · '}
              RMSE{' '}
              <strong>{model?.rmse != null ? model.rmse.toFixed(3) : 'not evaluated'}</strong>
              {model?.evaluated_on_ratings != null && model.evaluated_on_ratings > 0 && (
                <> on {model.evaluated_on_ratings} ratings</>
              )}
            </p>
          </div>
          <button className="btn btn--primary" onClick={reevaluate} disabled={evaluating}>
            {evaluating ? <Spinner /> : 'Re-evaluate model'}
          </button>
        </div>

        <Alert kind="warn">
          Re-evaluation scores the existing checkpoint against your users' ratings — it does not
          retrain the weights. Retraining is an offline job, deliberately kept out of the app.
        </Alert>

        {/* Without this the button can succeed and appear to do nothing, e.g.
            when no user is mapped onto a trained NCF embedding yet. */}
        {model?.note && (
          <p className="small" style={{ margin: '12px 0 0' }}>
            <strong>Last run:</strong>{' '}
            <span className="muted">{model.note}</span>
            {model.evaluated_at && (
              <span className="muted"> ({new Date(model.evaluated_at).toLocaleString()})</span>
            )}
          </p>
        )}

        <p className="muted tiny" style={{ margin: '10px 0 0' }}>
          {model?.num_users} users × {model?.num_movies} movies · {model?.candidates} rankable ·
          SBERT {model?.sbert_model} ({model?.sbert_dim}-dim)
        </p>
      </div>

      {/* --- accuracy metrics --- */}
      <div className="card" style={{ marginTop: 24 }}>
        <div className="row row--between">
          <div>
            <h2 style={{ marginBottom: 4 }}>Accuracy</h2>
            <p className="muted small" style={{ margin: 0 }}>
              Measured against the real MovieLens ratings the model was trained on.
            </p>
          </div>
          <button className="btn btn--ghost" onClick={loadMetrics} disabled={metricsLoading}>
            {metricsLoading ? 'Measuring...' : 'Run evaluation'}
          </button>
        </div>

        {metrics && !metrics.available && (
          <Alert kind="warn">{metrics.reason}</Alert>
        )}

        {metrics && metrics.available && (
          <>
            <div className="stat-grid" style={{ marginTop: 18, gridTemplateColumns: 'repeat(4, 1fr)' }}>
              <div className="stat">
                <div className="stat__value">{metrics.rmse}</div>
                <div className="stat__label">RMSE (stars)</div>
              </div>
              <div className="stat">
                <div className="stat__value">{metrics.mae}</div>
                <div className="stat__label">MAE (stars)</div>
              </div>
              <div className="stat">
                <div className="stat__value">
                  {metrics.precision_at_k != null ? `${(metrics.precision_at_k * 100).toFixed(0)}%` : '-'}
                </div>
                <div className="stat__label">Precision@{metrics.k}</div>
              </div>
              <div className="stat">
                <div className="stat__value">
                  {metrics.ndcg_at_k != null ? metrics.ndcg_at_k.toFixed(3) : '-'}
                </div>
                <div className="stat__label">NDCG@{metrics.k}</div>
              </div>
            </div>
            <p className="muted tiny" style={{ marginTop: 12 }}>
              {metrics.ratings_evaluated?.toLocaleString()} ratings from{' '}
              {metrics.users_evaluated?.toLocaleString()} users in {metrics.source_file}, in{' '}
              {metrics.took_seconds}s. {metrics.note}
            </p>
          </>
        )}

        {!metrics && (
          <p className="muted small" style={{ marginTop: 12 }}>
            Needs a MovieLens ratings file (ratings.dat or ratings.csv) beside the model artifacts.
            Without ground truth there is nothing to measure against.
          </p>
        )}
      </div>

      {/* --- tmdb sync --- */}
      <div className="card" style={{ marginTop: 24 }}>
        <h2 style={{ marginBottom: 4 }}>TMDB Sync</h2>
        <p className="muted small" style={{ margin: '0 0 18px' }}>
          Fetch posters, synopses and runtimes from TMDB, or import films released after 2000.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {/* posters */}
          <div className="card card--flat card--pad-sm">
            <div className="row row--between" style={{ marginBottom: 10 }}>
              <strong className="small">Sync Posters &amp; Details</strong>
              <button
                className="btn btn--primary btn--sm"
                onClick={() => startSync('posters')}
                disabled={sync?.posters?.running || sync?.recent?.running}
              >
                {sync?.posters?.running ? <><Spinner /> Running…</> : 'Start'}
              </button>
            </div>
            <p className="muted tiny" style={{ margin: '0 0 8px' }}>
              Fills poster_url, synopsis and runtime for existing MovieLens movies that are missing them.
            </p>
            {sync?.posters && (
              <SyncBar state={sync.posters} matched="matched" missed="missed" />
            )}
          </div>

          {/* recent */}
          <div className="card card--flat card--pad-sm">
            <div className="row row--between" style={{ marginBottom: 10 }}>
              <strong className="small">Import Recent Movies (2001+)</strong>
              <button
                className="btn btn--primary btn--sm"
                onClick={() => startSync('recent')}
                disabled={sync?.recent?.running || sync?.posters?.running}
              >
                {sync?.recent?.running ? <><Spinner /> Running…</> : 'Start'}
              </button>
            </div>
            <p className="muted tiny" style={{ margin: '0 0 8px' }}>
              Imports well-known films from 2001 to today via TMDB Discover (~200 per year, min 300 votes).
            </p>
            {sync?.recent && (
              <SyncBar state={sync.recent} matched="added" missed="skipped" />
            )}
          </div>
        </div>
      </div>

      {/* --- movie table --- */}
      <div className="row row--between" style={{ marginTop: 36, marginBottom: 14 }}>
        <h2 style={{ margin: 0 }}>Movies</h2>
        <div className="row" style={{ gap: 10 }}>
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search titles…"
            style={{ width: 220 }}
          />
          <button className="btn btn--primary btn--sm" onClick={() => setEditing({ ...EMPTY_MOVIE })}>
            Add movie
          </button>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Title</th>
              <th>Genres</th>
              <th>Year</th>
              <th>Runtime</th>
              <th>Rating</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {movies.items.map((m) => (
              <tr key={m.movie_id}>
                <td className="muted">{m.movie_id}</td>
                <td>{m.title}</td>
                <td className="muted small">{m.genres || '—'}</td>
                <td>{m.release_year || '—'}</td>
                <td>{m.runtime_minutes ? `${m.runtime_minutes}m` : '—'}</td>
                <td>{m.rating_count > 0 ? Number(m.avg_rating).toFixed(1) : '—'}</td>
                <td>
                  <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
                    <button className="btn btn--ghost btn--sm" onClick={() => setEditing({ ...m })}>
                      Edit
                    </button>
                    <button className="btn btn--danger btn--sm" onClick={() => remove(m)}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {movies.items.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">No movies match “{query}”.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="row row--between" style={{ marginTop: 14 }}>
        <span className="muted small">
          {movies.total} movies · page {movies.page} of {pages}
        </span>
        <div className="row" style={{ gap: 8 }}>
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            Previous
          </button>
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => setPage((p) => Math.min(pages, p + 1))}
            disabled={page >= pages}
          >
            Next
          </button>
        </div>
      </div>

      {/* --- add / edit modal --- */}
      {editing && (
        <div className="modal-backdrop" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{editing.movie_id ? 'Edit movie' : 'Add movie'}</h2>
            <form onSubmit={saveMovie} className="stack" style={{ marginTop: 16 }}>
              <div className="field">
                <label htmlFor="m-title">Title</label>
                <input
                  id="m-title"
                  value={editing.title}
                  onChange={(e) => setEditing({ ...editing, title: e.target.value })}
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="m-genres">Genres (pipe-separated)</label>
                <input
                  id="m-genres"
                  value={editing.genres || ''}
                  onChange={(e) => setEditing({ ...editing, genres: e.target.value })}
                  placeholder="Action|Sci-Fi"
                />
              </div>
              <div className="grid-2">
                <div className="field">
                  <label htmlFor="m-year">Release year</label>
                  <input
                    id="m-year"
                    type="number"
                    value={editing.release_year || ''}
                    onChange={(e) => setEditing({ ...editing, release_year: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="m-runtime">Runtime (min)</label>
                  <input
                    id="m-runtime"
                    type="number"
                    value={editing.runtime_minutes || ''}
                    onChange={(e) => setEditing({ ...editing, runtime_minutes: e.target.value })}
                  />
                </div>
              </div>
              <div className="field">
                <label htmlFor="m-poster">Poster URL</label>
                <input
                  id="m-poster"
                  value={editing.poster_url || ''}
                  onChange={(e) => setEditing({ ...editing, poster_url: e.target.value })}
                  placeholder="https://…"
                />
              </div>
              <div className="field">
                <label htmlFor="m-overview">Synopsis</label>
                <textarea
                  id="m-overview"
                  value={editing.overview || ''}
                  onChange={(e) => setEditing({ ...editing, overview: e.target.value })}
                  style={{ minHeight: 90 }}
                />
              </div>
              <div className="row row--between" style={{ marginTop: 8 }}>
                <button type="button" className="btn btn--ghost" onClick={() => setEditing(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn--primary">
                  {editing.movie_id ? 'Save changes' : 'Create movie'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
