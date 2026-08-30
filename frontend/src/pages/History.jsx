import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import client, { errorMessage } from '../api/client';
import { Alert, Poster, Spinner } from '../components/Common';

/** Past recommendations — backs GET /history. */
export default function History() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    client
      .get('/history')
      .then(({ data }) => setData(data))
      .catch((err) => setError(errorMessage(err, 'Could not load your history')))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="center-screen">
        <Spinner accent />
      </div>
    );
  }

  // Group consecutive rows sharing a mood — one search produced five of them.
  const groups = [];
  for (const item of data?.items || []) {
    const last = groups[groups.length - 1];
    if (last && last.mood === item.mood_input && last.at.slice(0, 16) === item.recommended_at.slice(0, 16)) {
      last.items.push(item);
    } else {
      groups.push({ mood: item.mood_input, at: item.recommended_at, items: [item] });
    }
  }

  return (
    <div className="page">
      <h1>Your history</h1>
      <p className="muted">{data?.total || 0} recommendations so far.</p>
      <Alert kind="error">{error}</Alert>

      {groups.length === 0 && (
        <div className="empty">
          Nothing yet. <Link to="/">Find your first film →</Link>
        </div>
      )}

      <div className="stack" style={{ marginTop: 24 }}>
        {groups.map((group, i) => (
          <div className="card" key={`${group.at}-${i}`}>
            <div className="row row--between" style={{ marginBottom: 14 }}>
              <em className="muted">“{group.mood}”</em>
              <span className="tiny muted">{new Date(group.at).toLocaleString()}</span>
            </div>

            <div className="stack">
              {group.items.map((item) => (
                <div className="row" key={item.rec_id} style={{ gap: 14, alignItems: 'flex-start' }}>
                  <div style={{ width: 46 }}>
                    <Poster movie={item.movie} />
                  </div>
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <Link to={`/movie/${item.movie.movie_id}`}>
                      <strong className="small">{item.movie.title}</strong>
                    </Link>
                    <p className="tiny muted" style={{ margin: '2px 0 0', fontStyle: 'italic' }}>
                      {item.explanation}
                    </p>
                  </div>
                  <span className="tag">{(item.score * 100).toFixed(0)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
