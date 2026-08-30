import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import client, { errorMessage } from '../api/client';
import { Alert, CountUp, Reveal, Spinner } from '../components/Common';

function BarChart({ rows, valueKey, labelKey, suffix = '' }) {
  const max = Math.max(...rows.map((r) => r[valueKey]), 1);
  return (
    <div className="bars">
      {rows.map((row) => (
        <div className="bar-row" key={row[labelKey]}>
          <span className="muted">{row[labelKey]}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(row[valueKey] / max) * 100}%` }} />
          </span>
          <span className="tiny muted">{row[valueKey]}{suffix}</span>
        </div>
      ))}
    </div>
  );
}

export default function TasteProfile() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    client
      .get('/profile')
      .then(({ data }) => setData(data))
      .catch((err) => setError(errorMessage(err, 'Could not load your profile')))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="center-screen">
        <Spinner accent />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page">
        <Alert kind="error">{error || 'No profile data'}</Alert>
      </div>
    );
  }

  const nothingYet = data.total_ratings === 0 && data.onboarding_seeds === 0;
  const maxWord = Math.max(...data.mood_words.map((w) => w.count), 1);

  return (
    <div className="page">
      <h1>Your taste</h1>
      <p className="muted">Built from what you have rated and searched for.</p>
      <Alert kind="error">{error}</Alert>

      {nothingYet ? (
        <div className="empty">
          Nothing to show yet. <Link to="/">Find a film</Link> or{' '}
          <Link to="/onboarding">answer the 5 questions</Link> to get started.
        </div>
      ) : (
        <>
          <div className="stat-grid" style={{ marginTop: 24 }}>
            <div className="stat">
              <div className="stat__value"><CountUp value={data.total_ratings} /></div>
              <div className="stat__label">Films rated</div>
            </div>
            <div className="stat">
              <div className="stat__value">
                {data.average_rating != null ? data.average_rating.toFixed(1) : '—'}
              </div>
              <div className="stat__label">Your average</div>
            </div>
            <div className="stat">
              <div className="stat__value"><CountUp value={data.total_searches} /></div>
              <div className="stat__label">Mood searches</div>
            </div>
          </div>

          {data.onboarding_seeds > 0 && (
            <p className="muted small" style={{ marginTop: 12 }}>
              Plus {data.onboarding_seeds} starter picks from onboarding — these shape
              recommendations but are not counted as films you rated.
            </p>
          )}

          {data.top_genres.length > 0 && (
            <Reveal><div className="card" style={{ marginTop: 28 }}>
              <h2>Your genres</h2>
              <p className="muted small">By how often they appear in what you like.</p>
              <div style={{ marginTop: 16 }}>
                <BarChart rows={data.top_genres} valueKey="count" labelKey="genre" />
              </div>
              <div className="row" style={{ gap: 8, marginTop: 18 }}>
                {data.top_genres.slice(0, 5).map((g) => (
                  <span key={g.genre} className="tag tag--accent">
                    {g.genre} · {g.avg_rating.toFixed(1)}★
                  </span>
                ))}
              </div>
            </div></Reveal>
          )}

          {data.total_ratings > 0 && (
            <Reveal><div className="card" style={{ marginTop: 24 }}>
              <h2>How you rate</h2>
              <div style={{ marginTop: 16 }}>
                <BarChart
                  rows={data.rating_distribution.filter((r) => r.count > 0)}
                  valueKey="count"
                  labelKey="stars"
                />
              </div>
            </div></Reveal>
          )}

          {data.decades.length > 0 && (
            <Reveal><div className="card" style={{ marginTop: 24 }}>
              <h2>Eras you lean towards</h2>
              <div style={{ marginTop: 16 }}>
                <BarChart rows={data.decades} valueKey="count" labelKey="decade" />
              </div>
            </div></Reveal>
          )}

          {data.mood_words.length > 0 && (
            <Reveal><div className="card" style={{ marginTop: 24 }}>
              <h2>Words you search with</h2>
              <p className="muted small">Pulled from your own mood descriptions.</p>
              <div className="chip-cloud" style={{ marginTop: 16 }}>
                {data.mood_words.map((w) => (
                  <span
                    key={w.word}
                    className="tag tag--accent"
                    style={{ fontSize: `${0.75 + (w.count / maxWord) * 0.6}rem` }}
                  >
                    {w.word}
                  </span>
                ))}
              </div>
            </div></Reveal>
          )}
        </>
      )}
    </div>
  );
}
