import { useMemo } from 'react';

/**
 * JobTable — Displays recent jobs with status badges and priority colors
 *
 * Shows the last 50 jobs from the queue, sorted newest first.
 * Color-coded status badges: green (completed), blue (processing),
 * amber (queued), red (failed).
 */
export default function JobTable({ jobs = [] }) {
  // Format a UTC timestamp to a readable relative time
  const formatTime = (isoString) => {
    if (!isoString) return '—';
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);

    if (diffSec < 5) return 'just now';
    if (diffSec < 60) return `${diffSec}s ago`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    return date.toLocaleTimeString();
  };

  // Truncate job ID for display
  const shortId = (id) => id ? id.substring(0, 8) : '—';

  // Truncate payload for display
  const shortPayload = (payload) => {
    if (!payload) return '—';
    const str = typeof payload === 'string' ? payload : JSON.stringify(payload);
    return str.length > 40 ? str.substring(0, 40) + '…' : str;
  };

  if (jobs.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">📋</div>
        <div className="empty-state-text">
          No jobs yet. Submit a job using the form above.
        </div>
      </div>
    );
  }

  return (
    <div className="job-table-scroll">
      <table className="job-table">
        <thead>
          <tr>
            <th>Job ID</th>
            <th>Priority</th>
            <th>Status</th>
            <th>Payload</th>
            <th>Created</th>
            <th>Retries</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job, index) => (
            <tr
              key={job.id}
              className="animate-fade-in"
              style={{ animationDelay: `${index * 0.02}s` }}
            >
              <td className="job-id">{shortId(job.id)}</td>
              <td>
                <span className={`badge badge--${job.priority}`}>
                  {job.priority}
                </span>
              </td>
              <td>
                <span className={`badge badge--${job.status}`}>
                  {job.status === 'processing' ? '⟳ ' : ''}
                  {job.status}
                </span>
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>
                {shortPayload(job.payload)}
              </td>
              <td style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {formatTime(job.created_at)}
              </td>
              <td style={{ textAlign: 'center', fontFamily: 'var(--font-mono)' }}>
                {job.retries > 0 ? (
                  <span style={{ color: 'var(--accent-amber)' }}>{job.retries}/3</span>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>0</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
