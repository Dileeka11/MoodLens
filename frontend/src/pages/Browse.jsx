import { useCallback, useEffect, useState } from 'react';
import client, { errorMessage } from '../api/client';
import { Alert, MovieTile, SkeletonGrid } from '../components/Common';

const GENRES = [
  'Action', 'Adventure', 'Animation', "Children's", 'Comedy', 'Crime',
  'Documentary', 'Drama', 'Fantasy', 'Film-Noir', 'Horror', 'Musical',
  'Mystery', 'Romance', 'Sci-Fi', 'Thriller', 'War', 'Western',
];

const SORTS = [
  { value: 'popular', label: 'Most rated' },
  { value: 'rating', label: 'Highest rated' },
  { value: 'year_desc', label: 'Newest first' },
  { value: 'year_asc', label: 'Oldest first' },
  { value: 'title', label: 'Title A–Z' },
];

const EMPTY = { q: '', genre: '', year_from: '', year_to: '', sort: 'popular' };

export default function Browse() {
  const [filters, setFilters] = useState(EMPTY);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, per_page: 24, sort: filters.sort };
      if (filters.q.trim()) params.q = filters.q.trim();
      if (filters.genre) params.genre = filters.genre;
      if (filters.year_from) params.year_from = Number(filters.year_from);
      if (filters.year_to) params.year_to = Number(filters.year_to);

      const { data } = await client.get('/browse', { params });
      setData(data);
      setError('');
    } catch (err) {
      setError(errorMessage(err, 'Could not load movies'));
    } finally {
      setLoading(false);
    }
  }, [filters, page]);

  // Debounced so typing in the search box does not fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(load, 280);
    return () => clearTimeout(t);
  }, [load]);

  const set = (key) => (e) => {
    setFilters((f) => ({ ...f, [key]: e.target.value }));
    setPage(1);
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1;
  const filtered = filters.q || filters.genre || filters.year_from || filters.year_to;

  return (
    <div className="page">
      <h1>Browse</h1>
      <p className="muted">All {data ? data.total.toLocaleString() : '—'} films in the catalogue.</p>

      <div className="card card--flat card--pad-sm" style={{ marginTop: 20 }}>
        <div className="filter-grid">
          <div className="field">
            <label htmlFor="f-q">Search</label>
            <input id="f-q" value={filters.q} onChange={set('q')} placeholder="Title…" />
          </div>
          <div className="field">
            <label htmlFor="f-genre">Genre</label>
            <select id="f-genre" value={filters.genre} onChange={set('genre')}>
              <option value="">All genres</option>
              {GENRES.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-from">From year</label>
            <input id="f-from" type="number" value={filters.year_from} onChange={set('year_from')} placeholder="1920" />
          </div>
          <div className="field">
            <label htmlFor="f-to">To year</label>
            <input id="f-to" type="number" value={filters.year_to} onChange={set('year_to')} placeholder="2000" />
          </div>
          <div className="field">
            <label htmlFor="f-sort">Sort by</label>
            <select id="f-sort" value={filters.sort} onChange={set('sort')}>
              {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
        </div>

        {filtered && (
          <button
            className="btn--link small"
            style={{ marginTop: 12 }}
            onClick={() => { setFilters(EMPTY); setPage(1); }}
          >
            Clear filters
          </button>
        )}
      </div>

      <Alert kind="error">{error}</Alert>

      <div style={{ marginTop: 26 }}>
        {loading && !data ? (
          <SkeletonGrid count={12} />
        ) : data?.items.length ? (
          <div className="movie-grid stagger" style={{ opacity: loading ? 0.45 : 1, transition: 'opacity .18s' }}>
            {data.items.map((m) => (
              <MovieTile
                key={m.movie_id}
                movie={m}
                subtitle={[m.release_year, m.rating_count > 0 ? `★ ${Number(m.avg_rating).toFixed(1)}` : null]
                  .filter(Boolean)
                  .join(' · ')}
              />
            ))}
          </div>
        ) : (
          <div className="empty">No films match those filters.</div>
        )}
      </div>

      {data && data.total > data.per_page && (
        <div className="row row--between" style={{ marginTop: 26 }}>
          <span className="muted small">Page {data.page} of {pages}</span>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn btn--ghost btn--sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
              Previous
            </button>
            <button className="btn btn--ghost btn--sm" onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page >= pages}>
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
