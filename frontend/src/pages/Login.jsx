import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { errorMessage } from '../api/client';
import { Alert, Spinner } from '../components/Common';

/** Screen 1 — Login / Register. */
export default function Login() {
  const [mode, setMode] = useState('login');       // 'login' | 'register'
  const [form, setForm] = useState({ username: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from || '/';

  const isRegister = mode === 'register';
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      if (isRegister) {
        await register(form.username.trim(), form.email.trim(), form.password);
        // New accounts go straight to onboarding to beat the cold start.
        navigate('/onboarding', { replace: true });
      } else {
        await login(form.email.trim(), form.password);
        navigate(from, { replace: true });
      }
    } catch (err) {
      setError(errorMessage(err, isRegister ? 'Could not create account' : 'Could not sign in'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-screen spotlight">
      <div className="page page--narrow" style={{ padding: 0, width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <h1 style={{ marginBottom: 6 }}>
            Mood<span className="gradient-text">Lens</span>
          </h1>
          <p className="muted">Tell us how you feel. We'll find the film.</p>
        </div>

        <div className="card glass fade-in">
          <h2>{isRegister ? 'Create your account' : 'Welcome back'}</h2>

          <form onSubmit={submit} className="stack" style={{ marginTop: 20 }}>
            {isRegister && (
              <div className="field">
                <label htmlFor="username">Name</label>
                <input
                  id="username"
                  value={form.username}
                  onChange={set('username')}
                  placeholder="Your name"
                  required
                  minLength={2}
                  autoComplete="name"
                />
              </div>
            )}

            <div className="field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={form.email}
                onChange={set('email')}
                placeholder="you@example.com"
                required
                autoComplete="email"
              />
            </div>

            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={form.password}
                onChange={set('password')}
                placeholder={isRegister ? 'At least 8 characters' : '••••••••'}
                required
                minLength={isRegister ? 8 : undefined}
                autoComplete={isRegister ? 'new-password' : 'current-password'}
              />
            </div>

            <Alert kind="error">{error}</Alert>

            <button type="submit" className="btn btn--primary btn--lg" disabled={busy}>
              {busy ? <Spinner /> : isRegister ? 'Create account' : 'Sign in'}
            </button>
          </form>

          {!isRegister && (
            <div style={{ textAlign: 'center', marginTop: 16 }}>
              <Link to="/forgot-password" className="small">
                Forgot password?
              </Link>
            </div>
          )}
        </div>

        <div style={{ textAlign: 'center', marginTop: 20 }}>
          <span className="muted small">
            {isRegister ? 'Already have an account?' : 'New to MoodLens?'}{' '}
          </span>
          <button
            type="button"
            className="btn--link small"
            onClick={() => {
              setMode(isRegister ? 'login' : 'register');
              setError('');
                      }}
          >
            {isRegister ? 'Sign in' : 'Create New Account'}
          </button>
        </div>
      </div>
    </div>
  );
}
