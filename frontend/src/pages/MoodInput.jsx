import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import client, { errorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { Alert, Spinner } from '../components/Common';
import { IconSparkles } from '../components/Icons';

const WATCHING_WITH = ['Alone', 'Partner', 'Family', 'Friends'];
const TIME_AVAILABLE = ['~1hr', '~2hrs', '~3hrs+'];

const EXAMPLES = [
  'Dark and mind-blowing, but not too long',
  'Light and funny, I had a rough week',
  'A tense thriller with a twist I will not see coming',
  'Something beautiful and slow to fall asleep to',
];

/** Screen 2 — Mood input, the main screen. */
export default function MoodInput() {
  const [moodText, setMoodText] = useState('');
  const [watchingWith, setWatchingWith] = useState('');
  const [timeAvailable, setTimeAvailable] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const { user } = useAuth();
  const navigate = useNavigate();

  async function submit(e) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const { data } = await client.post('/recommend', {
        mood_text: moodText.trim(),
        watching_with: watchingWith || null,
        time_available: timeAvailable || null,
      });
      // Carry the dropdown context too: the API response does not echo it
      // back, and "Show me 5 more" needs the same filters.
      navigate('/recommendations', {
        state: {
          response: data,
          context: {
            watching_with: watchingWith || null,
            time_available: timeAvailable || null,
          },
        },
      });
    } catch (err) {
      setError(errorMessage(err, 'Could not get recommendations'));
    } finally {
      setBusy(false);
    }
  }

  const firstName = (user?.username || '').split(' ')[0];

  return (
    <div className="page page--narrow fade-in">
      <header className="hero">
        <span className="hero__eyebrow">
          <IconSparkles size={15} />
          {user?.has_taste_data ? 'Tuned to your taste' : 'Powered by NCF + SBERT'}
        </span>
        <h1>
          {firstName ? `${firstName}, what are you` : 'What are you'}{' '}
          <span className="gradient-text">in the mood for?</span>
        </h1>
        <p className="hero__sub">
          Describe it however you like — the tone, the pace, how you want to feel afterwards.
        </p>
      </header>

      <form onSubmit={submit} className="stack">
        <div className="field">
          <label htmlFor="mood">Your mood</label>
          <textarea
            id="mood"
            className="textarea--mood"
            value={moodText}
            onChange={(e) => setMoodText(e.target.value)}
            placeholder="I want something dark and mind-blowing but not too long..."
            required
            minLength={3}
            maxLength={1000}
          />
          <div className="row" style={{ gap: 8, marginTop: 12 }}>
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                className="chip-btn"
                onClick={() => setMoodText(ex)}
              >
                {ex.length > 32 ? `${ex.slice(0, 32)}…` : ex}
              </button>
            ))}
          </div>
        </div>

        <div className="grid-2">
          <div className="field">
            <label htmlFor="with">Watching with</label>
            <select id="with" value={watchingWith} onChange={(e) => setWatchingWith(e.target.value)}>
              <option value="">No preference</option>
              {WATCHING_WITH.map((w) => (
                <option key={w} value={w}>{w}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="time">Time available</label>
            <select id="time" value={timeAvailable} onChange={(e) => setTimeAvailable(e.target.value)}>
              <option value="">No limit</option>
              {TIME_AVAILABLE.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>

        <Alert kind="error">{error}</Alert>

        <button
          type="submit"
          className="btn btn--primary btn--lg"
          disabled={busy || moodText.trim().length < 3}
        >
          {busy ? (
            <>
              <Spinner /> Reading your mood…
            </>
          ) : (
            <>
              <IconSparkles size={19} /> Find My Movies
            </>
          )}
        </button>
      </form>

      {!user?.has_taste_data && (
        <div className="card card--flat card--pad-sm" style={{ marginTop: 32 }}>
          <div className="row row--between">
            <div style={{ flex: 1, minWidth: 200 }}>
              <strong className="small">New here?</strong>
              <p className="muted small" style={{ margin: 0 }}>
                Answer 5 quick questions and recommendations sharpen straight away.
              </p>
            </div>
            <Link to="/onboarding" className="btn btn--ghost btn--sm">
              Set up my taste
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
