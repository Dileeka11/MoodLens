import axios from 'axios';

const TOKEN_KEY = 'moodlens_token';

// Vite proxies /api -> http://localhost:8000 in dev (see vite.config.js).
const client = axios.create({ baseURL: '/api' });

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// An expired or invalid token should drop the session rather than leave the
// UI in a half-authenticated state.
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && getToken()) {
      setToken(null);
      localStorage.removeItem('moodlens_user');
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

/** Pull a readable message out of a FastAPI error response. */
export function errorMessage(error, fallback = 'Something went wrong') {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    // Pydantic validation errors arrive as a list of {loc, msg}.
    return detail.map((d) => d.msg).join('. ');
  }
  if (error?.message === 'Network Error') return 'Cannot reach the API. Is the backend running?';

  // A 500 is a server-side crash, not a problem with what the user typed.
  // The most common cause in local dev is MySQL not running, and reporting
  // the caller's fallback ("could not send the email") sends people hunting
  // in the wrong place.
  if (error?.response?.status >= 500) {
    return 'The server hit an error. Check the backend log — is MySQL running?';
  }

  return fallback;
}

export default client;
