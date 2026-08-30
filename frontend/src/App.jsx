import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { Nav, Spinner } from './components/Common';

import AdminDashboard from './pages/AdminDashboard';
import Browse from './pages/Browse';
import ForgotPassword from './pages/ForgotPassword';
import History from './pages/History';
import Login from './pages/Login';
import MoodInput from './pages/MoodInput';
import MovieDetails from './pages/MovieDetails';
import Onboarding from './pages/Onboarding';
import Recommendations from './pages/Recommendations';
import ResetPassword from './pages/ResetPassword';
import TasteProfile from './pages/TasteProfile';
import Watchlist from './pages/Watchlist';

function RequireAuth({ children, adminOnly = false }) {
  const { user, loading, isAdmin } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="center-screen">
        <Spinner accent />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (adminOnly && !isAdmin) return <Navigate to="/" replace />;
  return children;
}

function RedirectIfAuthed({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="center-screen">
        <Spinner accent />
      </div>
    );
  }
  return user ? <Navigate to="/" replace /> : children;
}

function Shell() {
  return (
    <>
      <Nav />
      <Routes>
        <Route
          path="/login"
          element={
            <RedirectIfAuthed>
              <Login />
            </RedirectIfAuthed>
          }
        />
        {/* Public: reaching these means you cannot sign in, so they must not
            require a session. */}
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/" element={<RequireAuth><MoodInput /></RequireAuth>} />
        <Route path="/onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
        <Route path="/recommendations" element={<RequireAuth><Recommendations /></RequireAuth>} />
        <Route path="/movie/:id" element={<RequireAuth><MovieDetails /></RequireAuth>} />
        <Route path="/browse" element={<RequireAuth><Browse /></RequireAuth>} />
        <Route path="/watchlist" element={<RequireAuth><Watchlist /></RequireAuth>} />
        <Route path="/profile" element={<RequireAuth><TasteProfile /></RequireAuth>} />
        <Route path="/history" element={<RequireAuth><History /></RequireAuth>} />
        <Route path="/admin" element={<RequireAuth adminOnly><AdminDashboard /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <Shell />
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
