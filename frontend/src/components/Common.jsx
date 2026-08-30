import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import {
  IconBookmark,
  IconChart,
  IconClock,
  IconCompass,
  IconLogout,
  IconMonitor,
  IconMoon,
  IconShield,
  IconSparkles,
  IconStar,
  IconSun,
  IconClock as IconClockGlyph,
} from './Icons';

/* Each genre gets a stable hue, so a poster tile carries a hint of what the
   film is rather than being uniformly purple. */
const GENRE_HUE = {
  Action: 8, Adventure: 30, Animation: 190, "Children's": 45, Comedy: 48,
  Crime: 215, Documentary: 160, Drama: 265, Fantasy: 285, 'Film-Noir': 230,
  Horror: 350, Musical: 320, Mystery: 245, Romance: 335, 'Sci-Fi': 200,
  Thriller: 255, War: 20, Western: 25,
};

function posterStyle(genres) {
  const first = (genres || '').split('|').filter(Boolean)[0];
  const hue = GENRE_HUE[first];
  if (hue === undefined) return undefined;
  return {
    background: `linear-gradient(150deg, hsl(${hue} 62% 52%) 0%, hsl(${(hue + 28) % 360} 68% 66%) 100%)`,
  };
}

export function Poster({ movie, className = '', badge = false, overlay = null }) {
  const initials = (movie?.title || '?')
    .replace(/\s*\(\d{4}\)\s*$/, '')
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();

  const rated = badge && movie?.rating_count > 0;

  return (
    <div className={`poster ${className}`} style={posterStyle(movie?.genres)}>
      {movie?.poster_url ? (
        <img src={movie.poster_url} alt={movie.title} loading="lazy" />
      ) : (
        initials
      )}
      {rated && (
        <span className="poster__badge">
          <IconStar size={11} filled />
          {Number(movie.avg_rating).toFixed(1)}
        </span>
      )}
      {overlay && <span className="poster__overlay">{overlay}</span>}
    </div>
  );
}


export function Stars({ value = 0, onRate, size = 18 }) {
  const rounded = Math.round(Number(value) || 0);

  // Display-only stars are decorative: rendering them as buttons would put
  // five unusable controls per card into the accessibility tree.
  if (!onRate) {
    return (
      <span className="stars" role="img" aria-label={`${Number(value).toFixed(1)} out of 5 stars`}>
        {[1, 2, 3, 4, 5].map((n) => (
          <span key={n} className={`star star--static ${n <= rounded ? 'star--on' : ''}`}>
            <IconStar size={size} filled={n <= rounded} />
          </span>
        ))}
      </span>
    );
  }

  return (
    <span className="stars" role="group" aria-label="Rate this movie">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          className={`star ${n <= rounded ? 'star--on' : ''}`}
          onClick={() => onRate(n)}
          aria-label={`Rate ${n} star${n > 1 ? 's' : ''}`}
        >
          <IconStar size={size + 4} filled={n <= rounded} />
        </button>
      ))}
    </span>
  );
}


export function Spinner({ accent = false }) {
  return <span className={`spinner ${accent ? 'spinner--accent' : ''}`} />;
}

export function Alert({ kind = 'error', children }) {
  if (!children) return null;
  return <div className={`alert alert--${kind}`}>{children}</div>;
}

export function GenreTags({ genres, limit = 4 }) {
  const list = (genres || '').split('|').filter(Boolean).slice(0, limit);
  return (
    <div className="row" style={{ gap: 6 }}>
      {list.map((g) => (
        <span key={g} className="tag">{g}</span>
      ))}
    </div>
  );
}

export function formatRuntime(minutes) {
  if (!minutes) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

/* ------------------------------------------------------------ skeletons */

export function SkeletonCard() {
  return (
    <div className="movie-card" aria-hidden="true">
      <div className="skeleton skeleton--poster" />
      <div style={{ width: '100%' }}>
        <div className="skeleton skeleton--title" />
        <div className="skeleton skeleton--text" style={{ width: '35%' }} />
        <div className="skeleton skeleton--text" style={{ width: '90%' }} />
        <div className="skeleton skeleton--text" style={{ width: '75%' }} />
      </div>
    </div>
  );
}

export function SkeletonGrid({ count = 12 }) {
  return (
    <div className="movie-grid" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i}>
          <div className="skeleton skeleton--poster" />
          <div className="skeleton skeleton--text" style={{ marginTop: 10, width: '85%' }} />
        </div>
      ))}
    </div>
  );
}

/** Compact poster + title tile used by Browse, Watchlist and "More like this". */
export function MovieTile({ movie, subtitle }) {
  const runtime = formatRuntime(movie.runtime_minutes);
  return (
    <Link to={`/movie/${movie.movie_id}`} className="grid-card">
      <Poster
        movie={movie}
        badge
        overlay={
          runtime ? (
            <>
              <IconClockGlyph size={13} />
              {runtime}
            </>
          ) : null
        }
      />
      <div className="grid-card__title">{movie.title}</div>
      {subtitle && <div className="tiny muted">{subtitle}</div>}
    </Link>
  );
}

/** Counts up to `value` on mount — makes dashboard numbers feel alive.
 *  Skipped entirely when the user prefers reduced motion. */
export function CountUp({ value, duration = 900 }) {
  const target = Number(value) || 0;
  const reduced =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const [shown, setShown] = useState(reduced ? target : 0);
  const frame = useRef();

  useEffect(() => {
    if (reduced) {
      setShown(target);
      return undefined;
    }
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1);
      // ease-out cubic, matching --ease-out
      setShown(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [target, duration, reduced]);

  return <span className="count-up">{shown.toLocaleString()}</span>;
}

/** Fades a section in the first time it scrolls into view. */
export function Reveal({ children, className = '' }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return undefined;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          io.disconnect();      // one-shot: re-animating on every scroll is noise
        }
      },
      { rootMargin: '0px 0px -12% 0px' }
    );
    io.observe(node);
    return () => io.disconnect();
  }, []);

  return (
    <div ref={ref} className={`reveal ${visible ? 'is-visible' : ''} ${className}`}>
      {children}
    </div>
  );
}

/* ----------------------------------------------------------------- nav */

const THEME_ICON = { system: IconMonitor, dark: IconMoon, light: IconSun };
const THEME_LABEL = { system: 'Following your system', dark: 'Dark', light: 'Light' };

export function ThemeToggle() {
  const { theme, cycle } = useTheme();
  const Glyph = THEME_ICON[theme];
  return (
    <button
      className="theme-toggle"
      onClick={cycle}
      title={`Theme: ${THEME_LABEL[theme]} — click to change`}
      aria-label={`Theme: ${THEME_LABEL[theme]}. Click to change.`}
    >
      <Glyph size={18} />
    </button>
  );
}

export function Nav() {
  const { user, isAdmin, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;

  const cls = ({ isActive }) => `nav__link ${isActive ? 'nav__link--active' : ''}`;

  return (
    <nav className="nav">
      <div className="nav__inner">
        <Link to="/" className="nav__brand">
          <IconSparkles size={20} />
          <span>
            Mood<span className="gradient-text">Lens</span>
          </span>
        </Link>

        <div className="nav__links">
          <NavLink to="/" end className={cls}>
            <IconSparkles size={17} />
            <span>Find</span>
          </NavLink>
          <NavLink to="/browse" className={cls}>
            <IconCompass size={17} />
            <span>Browse</span>
          </NavLink>
          <NavLink to="/watchlist" className={cls}>
            <IconBookmark size={17} />
            <span>List</span>
          </NavLink>
          <NavLink to="/profile" className={cls}>
            <IconChart size={17} />
            <span>Taste</span>
          </NavLink>
          <NavLink to="/history" className={cls}>
            <IconClock size={17} />
            <span>History</span>
          </NavLink>
          {isAdmin && (
            <NavLink to="/admin" className={cls}>
              <IconShield size={17} />
              <span>Admin</span>
            </NavLink>
          )}

          <ThemeToggle />

          <button
            className="nav__link"
            onClick={() => {
              logout();
              navigate('/login');
            }}
            aria-label="Sign out"
          >
            <IconLogout size={17} />
            <span>Sign out</span>
          </button>
        </div>
      </div>
    </nav>
  );
}
