import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import client, { errorMessage } from '../api/client';
import { Alert, Spinner } from '../components/Common';

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const navigate = useNavigate();

  const [checking, setChecking] = useState(true);
  const [tokenError, setTokenError] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  // Validate up front so an expired link says so before the user types a password.
  useEffect(() => {
    if (!token) {
      setTokenError('This link is missing its token. Request a new reset email.');
      setChecking(false);
      return;
    }
    client
      .get('/reset-password/check', { params: { token } })
      .catch((err) => setTokenError(errorMessage(err, 'This reset link is not valid.')))
      .finally(() => setChecking(false));
  }, [token]);

  async function submit(e) {
    e.preventDefault();
    setError('');

    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }

    setBusy(true);
    try {
      await client.post('/reset-password', { token, new_password: password });
      setDone(true);
      setTimeout(() => navigate('/login', { replace: true }), 2200);
    } catch (err) {
      setError(errorMessage(err, 'Could not reset your password'));
    } finally {
      setBusy(false);
    }
  }

  if (checking) {
    return (
      <div className="center-screen spotlight">
        <Spinner accent />
      </div>
    );
  }

  return (
    <div className="center-screen spotlight">
      <div className="page page--narrow" style={{ padding: 0, width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <h1 style={{ marginBottom: 4 }}>
            Mood<span className="gradient-text">Lens</span>
          </h1>
          <p className="muted">Choose a new password</p>
        </div>

        <div className="card glass fade-in">
          {tokenError ? (
            <>
              <h2>Link no longer works</h2>
              <Alert kind="error">{tokenError}</Alert>
              <Link to="/forgot-password" className="btn btn--primary btn--lg" style={{ marginTop: 16 }}>
                Request a new link
              </Link>
            </>
          ) : done ? (
            <>
              <h2>Password updated</h2>
              <p className="muted">Taking you to the sign-in page…</p>
              <Link to="/login" className="btn btn--primary btn--lg" style={{ marginTop: 12 }}>
                Sign in now
              </Link>
            </>
          ) : (
            <form onSubmit={submit} className="stack">
              <div className="field">
                <label htmlFor="pw">New password</label>
                <input
                  id="pw"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 8 characters"
                  required
                  minLength={8}
                  autoComplete="new-password"
                />
              </div>

              <div className="field">
                <label htmlFor="pw2">Confirm new password</label>
                <input
                  id="pw2"
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="Type it again"
                  required
                  minLength={8}
                  autoComplete="new-password"
                />
              </div>

              <Alert kind="error">{error}</Alert>

              <button
                type="submit"
                className="btn btn--primary btn--lg"
                disabled={busy || password.length < 8}
              >
                {busy ? <Spinner /> : 'Set new password'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
