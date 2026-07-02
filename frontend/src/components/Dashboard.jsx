import { useState, useEffect, useCallback, useRef } from 'react';
import StatsChart from './StatsChart';
import JobTable from './JobTable';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

/**
 * Dashboard — Main layout component
 *
 * Combines stats cards, RPS chart, job submission form,
 * rate limit tester, and job history table.
 * Auto-refreshes stats and jobs every 5 seconds.
 */
export default function Dashboard() {
  // ─── State ──────────────────────────────────────────────────
  const [stats, setStats] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Job submission form
  const [jobPayload, setJobPayload] = useState('{"task": "process_data", "target": "users"}');
  const [jobPriority, setJobPriority] = useState('medium');
  const [submitting, setSubmitting] = useState(false);

  // Rate limit test
  const [testRunning, setTestRunning] = useState(false);
  const [testResults, setTestResults] = useState([]);

  // Toast notifications
  const [toasts, setToasts] = useState([]);
  const toastId = useRef(0);

  // ─── Toast Helper ───────────────────────────────────────────
  const addToast = useCallback((message, type = 'success') => {
    const id = toastId.current++;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 3000);
  }, []);

  // ─── Fetch Stats ────────────────────────────────────────────
  const fetchStats = useCallback(async () => {
    try {
      const [statsRes, jobsRes] = await Promise.all([
        fetch(`${API_URL}/api/stats`),
        fetch(`${API_URL}/api/jobs?limit=50`),
      ]);

      if (statsRes.ok) {
        const statsData = await statsRes.json();
        setStats(statsData);
      }

      if (jobsRes.ok) {
        const jobsData = await jobsRes.json();
        setJobs(jobsData.jobs || []);
      }

      setError(null);
      setLoading(false);
    } catch (err) {
      setError('Cannot connect to backend. Is the server running?');
      setLoading(false);
    }
  }, []);

  // Auto-refresh every 5 seconds
  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 5000);
    return () => clearInterval(interval);
  }, [fetchStats]);

  // ─── Submit Job ─────────────────────────────────────────────
  const handleSubmitJob = async (e) => {
    e.preventDefault();
    setSubmitting(true);

    try {
      let payload;
      try {
        payload = JSON.parse(jobPayload);
      } catch {
        payload = { raw: jobPayload };
      }

      const res = await fetch(`${API_URL}/api/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload, priority: jobPriority }),
      });

      const data = await res.json();

      if (res.ok) {
        addToast(`Job submitted: ${data.job_id.substring(0, 8)}…`, 'success');
        fetchStats(); // Refresh immediately
      } else {
        addToast(data.error || 'Failed to submit job', 'error');
      }
    } catch (err) {
      addToast('Network error — is the backend running?', 'error');
    }

    setSubmitting(false);
  };

  // ─── Rate Limit Test ───────────────────────────────────────
  const runRateLimitTest = async () => {
    setTestRunning(true);
    setTestResults([]);
    const results = [];

    for (let i = 0; i < 10; i++) {
      try {
        const res = await fetch(`${API_URL}/api/request`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Client-ID': 'rate-limit-test-client',
          },
          body: JSON.stringify({ test: true, request_num: i + 1 }),
        });

        const data = await res.json();
        results.push({
          num: i + 1,
          status: res.status,
          allowed: data.allowed,
          remaining: data.remaining_requests,
          retry_after: data.retry_after,
        });
      } catch (err) {
        results.push({
          num: i + 1,
          status: 0,
          allowed: false,
          error: 'Network error',
        });
      }

      // Small delay between requests to make the test visible
      await new Promise(r => setTimeout(r, 50));

      // Update results in real-time
      setTestResults([...results]);
    }

    const allowed = results.filter(r => r.allowed).length;
    const rejected = results.filter(r => !r.allowed).length;
    addToast(`Rate limit test: ${allowed} allowed, ${rejected} rejected`, allowed > 0 ? 'success' : 'error');

    setTestRunning(false);
    fetchStats();
  };

  // ─── Render ─────────────────────────────────────────────────
  return (
    <div className="app">
      {/* Header */}
      <header className="header animate-fade-in">
        <div className="header-brand">
          <div className="header-logo">🛡️</div>
          <div>
            <div className="header-title">FlowGuard</div>
            <div className="header-subtitle">Rate Limiter & Job Queue Dashboard</div>
          </div>
        </div>
        <div className="header-status">
          <span className={`status-dot ${error ? '' : ''}`} style={error ? { background: '#fb7185' } : {}} />
          {error ? 'Disconnected' : 'Connected'}
        </div>
      </header>

      {/* Error Banner */}
      {error && (
        <div style={{
          background: 'rgba(251, 113, 133, 0.1)',
          border: '1px solid rgba(251, 113, 133, 0.2)',
          borderRadius: 'var(--radius-md)',
          padding: 'var(--space-4) var(--space-5)',
          marginBottom: 'var(--space-6)',
          color: '#fb7185',
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
        }}>
          ⚠️ {error}
          <button className="btn btn--ghost btn--sm" onClick={fetchStats} style={{ marginLeft: 'auto' }}>
            Retry
          </button>
        </div>
      )}

      {/* Stats Cards */}
      <div className="stats-grid stagger-children">
        <div className="stat-card stat-card--indigo">
          <div className="stat-card-icon">⚡</div>
          <div className="stat-card-label">Requests / Second</div>
          <div className="stat-card-value">
            {loading ? <div className="skeleton" style={{ width: 60, height: 32 }} /> : stats?.requests_per_second ?? '0'}
          </div>
          <div className="stat-card-detail">Averaged over 60s window</div>
        </div>

        <div className="stat-card stat-card--emerald">
          <div className="stat-card-icon">✅</div>
          <div className="stat-card-label">Success Rate</div>
          <div className="stat-card-value">
            {loading ? <div className="skeleton" style={{ width: 60, height: 32 }} /> : `${stats?.rate_limiter?.success_rate ?? 100}%`}
          </div>
          <div className="stat-card-detail">
            {stats?.rate_limiter?.rejected_requests ?? 0} rejected
          </div>
        </div>

        <div className="stat-card stat-card--amber">
          <div className="stat-card-icon">📦</div>
          <div className="stat-card-label">Queue Depth</div>
          <div className="stat-card-value">
            {loading ? <div className="skeleton" style={{ width: 60, height: 32 }} /> : stats?.job_queue?.queue_depth ?? 0}
          </div>
          <div className="stat-card-detail">
            {stats?.job_queue?.completed ?? 0} completed
          </div>
        </div>

        <div className="stat-card stat-card--rose">
          <div className="stat-card-icon">🔥</div>
          <div className="stat-card-label">Total Requests</div>
          <div className="stat-card-value">
            {loading ? <div className="skeleton" style={{ width: 60, height: 32 }} /> : stats?.rate_limiter?.total_requests ?? 0}
          </div>
          <div className="stat-card-detail">
            {stats?.rate_limiter?.active_clients ?? 0} active clients
          </div>
        </div>

        <div className="stat-card stat-card--sky">
          <div className="stat-card-icon">🏭</div>
          <div className="stat-card-label">Jobs Processed</div>
          <div className="stat-card-value">
            {loading ? <div className="skeleton" style={{ width: 60, height: 32 }} /> : stats?.job_queue?.total_jobs ?? 0}
          </div>
          <div className="stat-card-detail">
            {stats?.job_queue?.failed ?? 0} failed
          </div>
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="content-grid">
        {/* Left Column: Chart + Job Form */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
          {/* RPS Chart */}
          <div className="panel animate-slide-up">
            <div className="panel-header">
              <div className="panel-title">
                📈 Requests Per Second
              </div>
              <span className="panel-badge panel-badge--live">● Live</span>
            </div>
            <StatsChart
              rpsHistory={stats?.rps_history || []}
              rps={stats?.requests_per_second || 0}
            />
          </div>

          {/* Submit Job Form */}
          <div className="panel animate-slide-up" style={{ animationDelay: '0.1s' }}>
            <div className="panel-header">
              <div className="panel-title">🚀 Submit Job</div>
            </div>
            <div className="panel-body">
              <form onSubmit={handleSubmitJob}>
                <div className="form-group" style={{ marginBottom: 'var(--space-4)' }}>
                  <label className="form-label" htmlFor="job-payload">Payload (JSON)</label>
                  <textarea
                    id="job-payload"
                    className="form-textarea"
                    value={jobPayload}
                    onChange={(e) => setJobPayload(e.target.value)}
                    rows={3}
                  />
                </div>
                <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'flex-end' }}>
                  <div className="form-group" style={{ flex: 1 }}>
                    <label className="form-label" htmlFor="job-priority">Priority</label>
                    <select
                      id="job-priority"
                      className="form-select"
                      value={jobPriority}
                      onChange={(e) => setJobPriority(e.target.value)}
                    >
                      <option value="high">🔴 High</option>
                      <option value="medium">🟡 Medium</option>
                      <option value="low">🔵 Low</option>
                    </select>
                  </div>
                  <button
                    type="submit"
                    className="btn btn--primary"
                    disabled={submitting}
                    style={{ height: 42 }}
                  >
                    {submitting ? '⟳ Submitting…' : '📤 Submit Job'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>

        {/* Right Column: Rate Limit Test + Job Table */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
          {/* Rate Limit Tester */}
          <div className="panel animate-slide-up" style={{ animationDelay: '0.15s' }}>
            <div className="panel-header">
              <div className="panel-title">🧪 Rate Limit Test</div>
              <button
                className="btn btn--danger btn--sm"
                onClick={runRateLimitTest}
                disabled={testRunning}
              >
                {testRunning ? '⟳ Running…' : '🔥 Fire 10 Requests'}
              </button>
            </div>
            <div className="panel-body">
              {testResults.length > 0 ? (
                <div className="test-results">
                  {testResults.map((r) => (
                    <div
                      key={r.num}
                      className={`test-result-row ${r.allowed ? 'test-result-row--allowed' : 'test-result-row--rejected'}`}
                    >
                      <span className="test-result-num">#{r.num}</span>
                      <span className="test-result-status">
                        {r.allowed ? '✓ 200' : `✗ ${r.status}`}
                      </span>
                      <span style={{ color: 'var(--text-muted)' }}>
                        {r.allowed
                          ? `${r.remaining} remaining`
                          : r.retry_after
                            ? `retry in ${r.retry_after}s`
                            : r.error || 'rejected'
                        }
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state" style={{ padding: 'var(--space-6)' }}>
                  <div className="empty-state-text">
                    Click "Fire 10 Requests" to test rate limiting.
                    Requests beyond the limit will get 429 responses.
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Job History Table */}
          <div className="panel animate-slide-up" style={{ animationDelay: '0.2s' }}>
            <div className="panel-header">
              <div className="panel-title">📋 Recent Jobs</div>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {jobs.length} job{jobs.length !== 1 ? 's' : ''}
              </span>
            </div>
            <div className="panel-body panel-body--flush">
              <JobTable jobs={jobs} />
            </div>
          </div>
        </div>
      </div>

      {/* Toast Notifications */}
      <div className="toast-container">
        {toasts.map(toast => (
          <div key={toast.id} className={`toast toast--${toast.type}`}>
            {toast.type === 'success' ? '✅' : '❌'} {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
}
