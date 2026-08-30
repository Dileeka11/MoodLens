import { useState } from 'react';
import { Link } from 'react-router-dom';
import client, { errorMessage } from '../api/client';
import { Alert, Spinner } from '../components/Common';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(null);   // null | { message, email_sent }
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const { data } = await client.post('/forgot-password', { email: email.trim() });
      setSent(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not send the reset email'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-screen spotlight">
      <div className="page page--narrow" style={{ padding: 0, width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <h1 style={{ marginBottom: 4 }}>
            Mood<span className="gradient-text">Lens</span>
          </h1>
          <p className="muted">Reset your password</p>
        </div>

        <div className="card glass fade-in">
          {sent ? (
            <>
              <h2>Check your email</h2>
              <p className="muted">{sent.message}</p>

              {/* Honest about what happened: with no SMTP server configured the
                  email was only written to disk, and saying "sent" would be a lie. */}
              {!sent.email_sent && (
                <Alert kind="warn">
                  No mail server is configured, so nothing was actually sent. The email was
                  written to <code>backend/cache/sent_emails/</code> and printed in the backend
                  log — open the link from there. Set <code>SMTP_HOST</code> in
                  <code> backend/.env</code> to send real emails.
                </Alert>
              )}

              <p className="small muted" style={{ marginTop: 16 }}>
                The link works for 60 minutes and can be used once.
              </p>
              <Link to="/login" className="btn btn--ghost btn--lg" style={{ marginTop: 12 }}>
                Back to sign in
              </Link>
            </>
          ) : (
            <>
              <h2>Forgot your password?</h2>
              <p className="muted small">
                Enter the email on your account and we'll send a link to choose a new password.
              </p>

              <form onSubmit={submit} className="stack" style={{ marginTop: 20 }}>
                <div className="field">
                  <label htmlFor="email">Email</label>
                  <input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    required
                    autoComplete="email"
                  />
                </div>

                <Alert kind="error">{error}</Alert>

                <button type="submit" className="btn btn--primary btn--lg" disabled={busy}>
                  {busy ? <Spinner /> : 'Send reset link'}
                </button>
              </form>

              <div style={{ textAlign: 'center', marginTop: 16 }}>
                <Link to="/login" className="small">Back to sign in</Link>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
