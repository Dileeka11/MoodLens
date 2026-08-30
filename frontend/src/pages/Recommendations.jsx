import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import client, { errorMessage } from '../api/client';
import { IconSparkles, IconStar } from '../components/Icons';
import {
  Alert,
  GenreTags,
  Poster,
  SkeletonCard,
  Stars,
  formatRuntime,
} from '../components/Common';

/** Screen 3 — the recommendation cards. */
export default function Recommendations() {
  const location = useLocation();
  const navigate = useNavigate();
  const initial = location.state?.response;
  const context = location.state?.context || {};

  const [response] = useState(initial);
  const [results, setResults] = useState(initial?.results || []);
  const [ratings, setRatings] = useState({});
  const [marked, setMarked] = useState({});      // movie_id -> 'saved' | 'not_interested'
  const [error, setError] = useState('');
  const [loadingMore, setLoadingMore] = useState(false);

  // Results live in navigation state; a hard refresh loses them.
  if (!response) return <Navigate to="/" replace />;

  async function rate(movieId, value) {
    setError('');
    try {
      await client.post('/rate', { movie_id: movieId, rating_value: value });
      setRatings((prev) => ({ ...prev, [movieId]: value }));
    } catch (err) {
      setError(errorMessage(err, 'Could not save your rating'));
    }
  }

  async function mark(movieId, status) {
    setError('');
    try {
      await client.post('/watchlist', { movie_id: movieId, status });
      setMarked((prev) => ({ ...prev, [movieId]: status }));
    } catch (err) {
      setError(errorMessage(err, 'Could not update your list'));
    }
  }

  async function showMore() {
    setLoadingMore(true);
    setError('');
    try {
      // Exclude what is already on screen so the next batch is genuinely new.
      const { data } = await client.post('/recommend', {
        mood_text: response.mood_text,
        watching_with: context.watching_with || null,
        time_available: context.time_available || null,
        exclude_movie_ids: results.map((r) => r.movie.movie_id),
      });
      if (data.results.length === 0) {
        setError('No more matches for this mood — try describing it differently.');
      } else {
        setResults((prev) => [...prev, ...data.results]);
      }
    } catch (err) {
      setError(errorMessage(err, 'Could not load more'));
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="page">
      <div className="row row--between" style={{ marginBottom: 6 }}>
        <h1 style={{ margin: 0 }}>Your <span className="gradient-text">picks</span></h1>
        <button className="btn btn--ghost btn--sm" onClick={() => navigate('/')}>
          New search
        </button>
      </div>

      <p className="muted">
        For <em>&ldquo;{response.mood_text}&rdquo;</em>
        {response.mood_terms?.length > 0 && (
          <>
            {' '}&mdash; we picked up on{' '}
            {response.mood_terms.map((t) => (
              <span key={t} className="tag tag--accent" style={{ marginRight: 6 }}>
                {t}
              </span>
            ))}
          </>
        )}
      </p>

      {!response.personalised && (
        <Alert kind="info">
          These come from what viewers broadly agree on. Rate a few films &mdash; or finish{' '}
          <Link to="/onboarding">onboarding</Link> &mdash; and they will start reflecting your taste.
        </Alert>
      )}

      <Alert kind="error">{error}</Alert>

      <div className="stack stagger" style={{ marginTop: 24 }}>
        {results.map((item) => {
          const movie = item.movie;
          const runtime = formatRuntime(movie.runtime_minutes);
          const justRated = ratings[movie.movie_id];
          const status = marked[movie.movie_id];

          // A dismissed card collapses in place rather than vanishing, so the
          // list does not jump and the action stays undoable.
          if (status === 'not_interested') {
            return (
              <div className="card card--flat card--pad-sm row row--between" key={movie.movie_id}>
                <span className="muted small">
                  Hidden <strong>{movie.title}</strong> &mdash; it will stay out of future picks.
                </span>
                <button className="btn--link small" onClick={() => mark(movie.movie_id, 'saved')}>
                  Undo
                </button>
              </div>
            );
          }

          // The top pick gets a wider, poster-led layout so the list has a
          // focal point rather than five identical rows.
          const isFeatured = item.rank === 1;

          return (
            <article
              className={isFeatured ? 'featured' : 'movie-card'}
              key={movie.movie_id}
            >
              <Link to={`/movie/${movie.movie_id}`} state={{ explanation: item.explanation }}>
                <Poster movie={movie} badge={isFeatured} />
              </Link>

              <div>
                {isFeatured ? (
                  <>
                    <span className="featured__badge">
                      <IconSparkles size={13} /> Top pick
                    </span>
                    <h2>
                      <Link
                        to={`/movie/${movie.movie_id}`}
                        state={{ explanation: item.explanation }}
                        style={{ color: 'inherit' }}
                      >
                        {movie.title}
                      </Link>
                    </h2>
                  </>
                ) : (
                  <div className="row" style={{ gap: 10, marginBottom: 4 }}>
                    <span className="movie-card__rank">{item.rank}</span>
                    <h3 style={{ margin: 0 }}>
                      <Link
                        to={`/movie/${movie.movie_id}`}
                        state={{ explanation: item.explanation }}
                        style={{ color: 'inherit' }}
                      >
                        {movie.title}
                      </Link>
                    </h3>
                  </div>
                )}

                <div className="row movie-card__meta" style={{ gap: 12 }}>
                  <span className="row" style={{ gap: 6 }}>
                    <Stars value={movie.avg_rating} size={15} />
                    {movie.rating_count > 0
                      ? `${Number(movie.avg_rating).toFixed(1)} (${movie.rating_count})`
                      : justRated
                        ? 'You rated it first'
                        : 'Not rated yet'}
                  </span>
                  {runtime && <span>{runtime}</span>}
                  {!runtime && <span className="tiny">Runtime not on file</span>}
                </div>

                <div style={{ marginTop: 8 }}>
                  <GenreTags genres={movie.genres} />
                </div>

                <p className="movie-card__why">{item.explanation}</p>

                {/* Score breakdown: the final blend plus the two components it
                    came from, so the number is inspectable rather than magic. */}
                <div className="score-bar" title="0.7 x NCF + 0.3 x mood similarity">
                  <div className="score-bar__head">
                    <span className="score-bar__pct">{(item.score * 100).toFixed(0)}%</span>
                    <span className="tiny muted">match</span>
                  </div>
                  <div className="score-bar__parts">
                    <span className="tiny muted">
                      Taste model {(item.ncf_score * 100).toFixed(0)}%
                    </span>
                    <span className="score-bar__track">
                      <span
                        className="score-bar__fill score-bar__fill--ncf"
                        style={{ width: `${item.ncf_score * 100}%` }}
                      />
                    </span>
                    <span className="tiny muted">
                      Mood match {(item.sbert_score * 100).toFixed(0)}%
                    </span>
                    <span className="score-bar__track">
                      <span
                        className="score-bar__fill score-bar__fill--sbert"
                        style={{ width: `${item.sbert_score * 100}%` }}
                      />
                    </span>
                  </div>
                </div>

                <div className="movie-card__actions">
                  {justRated ? (
                    <span className="row small muted" style={{ gap: 6 }}>
                      <Stars value={justRated} size={15} /> Saved
                    </span>
                  ) : (
                    <span className="row" style={{ gap: 8 }}>
                      <span className="small muted">Rate:</span>
                      <Stars value={0} onRate={(v) => rate(movie.movie_id, v)} />
                    </span>
                  )}
                  <Link
                    to={`/movie/${movie.movie_id}`}
                    state={{ explanation: item.explanation }}
                    className="btn btn--ghost btn--sm"
                  >
                    Details
                  </Link>
                  <button
                    className="btn btn--ghost btn--sm"
                    onClick={() => mark(movie.movie_id, 'saved')}
                    disabled={status === 'saved'}
                  >
                    {status === 'saved' ? 'On your list' : 'Save for later'}
                  </button>
                  <button
                    className="btn btn--danger btn--sm"
                    onClick={() => mark(movie.movie_id, 'not_interested')}
                  >
                    Not interested
                  </button>
                </div>
              </div>
            </article>
          );
        })}

        {loadingMore && <SkeletonCard />}
      </div>

      <div style={{ textAlign: 'center', marginTop: 28 }}>
        <button className="btn btn--ghost" onClick={showMore} disabled={loadingMore}>
          {loadingMore ? 'Finding more…' : 'Show me 5 more'}
        </button>
      </div>
    </div>
  );
}
