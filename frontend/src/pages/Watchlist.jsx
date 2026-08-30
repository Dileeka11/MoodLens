import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import client, { errorMessage } from '../api/client';
import { Alert, MovieTile, SkeletonGrid } from '../components/Common';

const TABS = [
  { value: 'saved', label: 'Want to watch' },
  { value: 'watched', label: 'Watched' },
  { value: 'not_interested', label: 'Not interested' },
];

export default function Watchlist() {
  const [tab, setTab] = useState('saved');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await client.get('/watchlist', { params: { status: tab } });
      setItems(data);
      setError('');
    } catch (err) {
      setError(errorMessage(err, 'Could not load your list'));
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  async function move(movieId, status) {
    try {
      await client.post('/watchlist', { movie_id: movieId, status });
      load();
    } catch (err) {
      setError(errorMessage(err, 'Could not update'));
    }
  }

  async function remove(movieId) {
    try {
      await client.delete(`/watchlist/${movieId}`);
      setItems((list) => list.filter((i) => i.movie.movie_id !== movieId));
    } catch (err) {
      setError(errorMessage(err, 'Could not remove'));
    }
  }

  return (
    <div className="page">
      <h1>My list</h1>

      <div className="row" style={{ gap: 8, marginTop: 16, marginBottom: 24 }}>
        {TABS.map((t) => (
          <button
            key={t.value}
            className={`btn btn--sm ${tab === t.value ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => setTab(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <Alert kind="error">{error}</Alert>

      {loading ? (
        <SkeletonGrid count={6} />
      ) : items.length === 0 ? (
        <div className="empty">
          {tab === 'saved' && <>Nothing saved yet. <Link to="/browse">Browse films →</Link></>}
          {tab === 'watched' && <>No films marked as watched yet.</>}
          {tab === 'not_interested' && <>Nothing hidden. Films you dismiss stay out of your recommendations.</>}
        </div>
      ) : (
        <div className="movie-grid stagger">
          {items.map((item) => (
            <div key={item.entry_id}>
              <MovieTile movie={item.movie} subtitle={item.movie.release_year} />
              <div className="row" style={{ gap: 6, marginTop: 8 }}>
                {tab !== 'watched' && (
                  <button className="btn btn--ghost btn--sm" onClick={() => move(item.movie.movie_id, 'watched')}>
                    Watched
                  </button>
                )}
                {tab !== 'saved' && (
                  <button className="btn btn--ghost btn--sm" onClick={() => move(item.movie.movie_id, 'saved')}>
                    Save
                  </button>
                )}
                <button className="btn btn--danger btn--sm" onClick={() => remove(item.movie.movie_id)}>
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'watched' && items.length > 0 && (
        <p className="muted small" style={{ marginTop: 20 }}>
          Watched and dismissed films are excluded from future recommendations.
        </p>
      )}
    </div>
  );
}
