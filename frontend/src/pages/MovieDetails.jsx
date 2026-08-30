import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import client, { errorMessage } from '../api/client';
import {
  Alert,
  GenreTags,
  MovieTile,
  Poster,
  SkeletonGrid,
  Spinner,
  Stars,
  formatRuntime,
} from '../components/Common';
import { IconArrowLeft } from '../components/Icons';

/** Screen 5 — movie details. */
export default function MovieDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  // When arriving from a recommendation, the explanation is carried in
  // navigation state so the "Why we chose this" panel shows immediately,
  // even before (or without) a matching row in the recommendations table.
  const passedExplanation = location.state?.explanation;

  const [movie, setMovie] = useState(null);
  const [similar, setSimilar] = useState(null);
  const [listStatus, setListStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLoading(true);
    setSimilar(null);
    window.scrollTo(0, 0);

    client
      .get(`/movie/${id}`)
      .then(({ data }) =>
        setMovie({
          ...data,
          last_explanation: data.last_explanation || passedExplanation || null,
        }),
      )
      .catch((err) => setError(errorMessage(err, 'Could not load this movie')))
      .finally(() => setLoading(false));

    // Secondary content: failing here should not break the page.
    client
      .get(`/movie/${id}/similar`, { params: { limit: 6 } })
      .then(({ data }) => setSimilar(data))
      .catch(() => setSimilar([]));

    client
      .get('/watchlist')
      .then(({ data }) => {
        const entry = data.find((e) => e.movie.movie_id === Number(id));
        setListStatus(entry ? entry.status : null);
      })
      .catch(() => setListStatus(null));
  }, [id]);

  async function rate(value) {
    setSaving(true);
    setError('');
    try {
      await client.post('/rate', { movie_id: Number(id), rating_value: value });
      setMovie((m) => ({ ...m, your_rating: value }));
    } catch (err) {
      setError(errorMessage(err, 'Could not save your rating'));
    } finally {
      setSaving(false);
    }
  }

  async function setStatus(status) {
    setError('');
    try {
      if (status === null) {
        await client.delete(`/watchlist/${id}`);
        setListStatus(null);
      } else {
        await client.post('/watchlist', { movie_id: Number(id), status });
        setListStatus(status);
      }
    } catch (err) {
      setError(errorMessage(err, 'Could not update your list'));
    }
  }

  if (loading) {
    return (
      <div className="center-screen">
        <Spinner accent />
      </div>
    );
  }

  if (!movie) {
    return (
      <div className="page">
        <Alert kind="error">{error || 'Movie not found'}</Alert>
        <button className="btn btn--ghost" style={{ marginTop: 16 }} onClick={() => navigate(-1)}>
          Back
        </button>
      </div>
    );
  }

  const runtime = formatRuntime(movie.runtime_minutes);

  return (
    <div className="page fade-in has-backdrop">
      {/* The film's own poster, blurred behind the header. Uses the cached
          image, so it adds no network request. */}
      {movie.poster_url && (
        <div className="backdrop" aria-hidden="true">
          <img src={movie.poster_url} alt="" />
        </div>
      )}

      <button
        className="btn btn--ghost btn--sm"
        onClick={() => navigate(-1)}
        style={{ marginBottom: 24 }}
      >
        <IconArrowLeft size={16} /> Back
      </button>

      <div
        className="detail-layout"
        style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 32, alignItems: 'start' }}
      >
        <Poster movie={movie} />

        <div>
          <h1 style={{ marginBottom: 8 }}>{movie.title}</h1>

          <div className="row muted" style={{ gap: 14, marginBottom: 14 }}>
            {movie.release_year && <span>{movie.release_year}</span>}
            {runtime ? <span>{runtime}</span> : <span className="tiny">Runtime not on file</span>}
            <span className="row" style={{ gap: 6 }}>
              <Stars value={movie.avg_rating} size={15} />
              {movie.rating_count > 0
                ? `${Number(movie.avg_rating).toFixed(1)} from ${movie.rating_count} rating${movie.rating_count === 1 ? '' : 's'}`
                : 'No ratings yet'}
            </span>
          </div>

          <GenreTags genres={movie.genres} limit={8} />

          <div className="card card--flat card--pad-sm" style={{ marginTop: 22 }}>
            <div className="row row--between">
              <div>
                <strong className="small">
                  {movie.your_rating ? 'Your rating' : 'Rate This Movie'}
                </strong>
                {movie.your_rating && (
                  <p className="muted tiny" style={{ margin: 0 }}>
                    Tap a different star to change it.
                  </p>
                )}
              </div>
              <span className="row" style={{ gap: 10 }}>
                {saving && <Spinner accent />}
                <Stars value={movie.your_rating || 0} onRate={rate} size={26} />
              </span>
            </div>
          </div>

          <div className="row" style={{ gap: 8, marginTop: 14 }}>
            <button
              className={`btn btn--sm ${listStatus === 'saved' ? 'btn--primary' : 'btn--ghost'}`}
              onClick={() => setStatus(listStatus === 'saved' ? null : 'saved')}
            >
              {listStatus === 'saved' ? 'Saved' : 'Save for later'}
            </button>
            <button
              className={`btn btn--sm ${listStatus === 'watched' ? 'btn--primary' : 'btn--ghost'}`}
              onClick={() => setStatus(listStatus === 'watched' ? null : 'watched')}
            >
              {listStatus === 'watched' ? 'Watched' : 'Mark watched'}
            </button>
            <button
              className={`btn btn--sm ${listStatus === 'not_interested' ? 'btn--primary' : 'btn--danger'}`}
              onClick={() => setStatus(listStatus === 'not_interested' ? null : 'not_interested')}
            >
              {listStatus === 'not_interested' ? 'Hidden' : 'Not interested'}
            </button>
          </div>

          <Alert kind="error">{error}</Alert>

          {movie.last_explanation && (
            <div className="card" style={{ marginTop: 22, borderLeft: '3px solid var(--accent)' }}>
              <h3 style={{ color: 'var(--accent)' }}>Why we chose this</h3>
              <p style={{ fontStyle: 'italic', margin: 0 }}>{movie.last_explanation}</p>
            </div>
          )}

          <div style={{ marginTop: 22 }}>
            <h3>Synopsis</h3>
            {movie.overview ? (
              <p>{movie.overview}</p>
            ) : (
              <p className="muted small">
                No synopsis on file — the MovieLens dataset ships titles and genres only. An admin
                can add one from the dashboard.
              </p>
            )}
          </div>

          {!movie.in_ncf_model && (
            <Alert kind="info">
              Released after our ratings model was trained, so its predicted score is
              estimated from the most similar films the model does know. It still appears
              in recommendations, marked as an estimate.
            </Alert>
          )}
        </div>
      </div>

      {/* --- more like this --- */}
      <div style={{ marginTop: 56 }}>
        <div className="section-head">
          <h2>More like this</h2>
        </div>
        <div className="rule" />
        <div style={{ marginTop: 4 }}>
          {similar === null ? (
            <SkeletonGrid count={6} />
          ) : similar.length === 0 ? (
            <p className="muted small">
              No similar titles — this film has no embedding in the trained model.
            </p>
          ) : (
            <div className="movie-grid stagger">
              {similar.map(({ movie: m, similarity }) => (
                <MovieTile key={m.movie_id} movie={m} subtitle={`${(similarity * 100).toFixed(0)}% similar`} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
