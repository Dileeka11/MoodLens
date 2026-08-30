import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import client, { errorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { Alert, Spinner } from '../components/Common';

/** Screen 4 — onboarding, one question at a time. */
export default function Onboarding() {
  const [questions, setQuestions] = useState([]);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const navigate = useNavigate();
  const { refresh } = useAuth();

  useEffect(() => {
    client
      .get('/onboarding/questions')
      .then(({ data }) => setQuestions(data))
      .catch((err) => setError(errorMessage(err, 'Could not load the questions')))
      .finally(() => setLoading(false));
  }, []);

  const total = questions.length;
  const question = questions[index];
  const selected = question ? answers[question.id] : undefined;
  const isLast = index === total - 1;

  async function finish(finalAnswers) {
    setSubmitting(true);
    setError('');
    try {
      await client.post('/onboarding', { answers: finalAnswers });
      await refresh();
      navigate('/', { replace: true });
    } catch (err) {
      setError(errorMessage(err, 'Could not save your answers'));
      setSubmitting(false);
    }
  }

  function choose(optionId) {
    const next = { ...answers, [question.id]: optionId };
    setAnswers(next);
    // Small pause so the selection is visible before advancing.
    setTimeout(() => {
      if (isLast) finish(next);
      else setIndex((i) => i + 1);
    }, 180);
  }

  function skip() {
    if (isLast) finish(answers);
    else setIndex((i) => i + 1);
  }

  if (loading) {
    return (
      <div className="center-screen">
        <Spinner accent />
      </div>
    );
  }

  if (!question) {
    return (
      <div className="page page--narrow">
        <Alert kind="error">{error || 'No questions available.'}</Alert>
      </div>
    );
  }

  return (
    <div className="page page--narrow">
      <div className="row row--between small muted" style={{ marginBottom: 10 }}>
        <span>Question {index + 1} of {total}</span>
        <button className="btn--link small" onClick={() => finish(answers)} disabled={submitting}>
          Skip all
        </button>
      </div>

      <div className="progress" aria-label={`Progress: question ${index + 1} of ${total}`}>
        <div className="progress__bar" style={{ width: `${((index + 1) / total) * 100}%` }} />
      </div>

      <h1 style={{ marginTop: 28 }}>{question.question}</h1>

      <div className="stack" style={{ marginTop: 20 }}>
        {question.options.map((opt) => (
          <button
            key={opt.id}
            className={`option ${selected === opt.id ? 'option--selected' : ''}`}
            onClick={() => choose(opt.id)}
            disabled={submitting}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <Alert kind="error">{error}</Alert>

      <div className="row row--between" style={{ marginTop: 28 }}>
        <button
          className="btn btn--ghost"
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
          disabled={index === 0 || submitting}
        >
          Back
        </button>
        <div className="row" style={{ gap: 10 }}>
          <button className="btn btn--ghost" onClick={skip} disabled={submitting}>
            Skip
          </button>
          <button
            className="btn btn--primary"
            onClick={() => (isLast ? finish(answers) : setIndex((i) => i + 1))}
            disabled={submitting || !selected}
          >
            {submitting ? <Spinner /> : isLast ? 'Finish' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  );
}
