import { useState, useCallback } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Area, AreaChart
} from 'recharts';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

/**
 * StatsChart — Real-time requests/second line chart
 *
 * Displays the last 60 seconds of request traffic as a smooth area chart.
 * Data comes from the parent Dashboard component via props.
 */
export default function StatsChart({ rpsHistory = [], rps = 0 }) {
  // Transform the array of counts into chart-friendly data
  const chartData = rpsHistory.map((count, index) => ({
    time: `${60 - index}s`,
    requests: count,
  }));

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div style={{
          background: 'rgba(18, 18, 28, 0.95)',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          borderRadius: '8px',
          padding: '8px 12px',
          fontSize: '0.75rem',
          fontFamily: "'JetBrains Mono', monospace",
        }}>
          <p style={{ color: '#8b8ba3', marginBottom: '4px' }}>{label} ago</p>
          <p style={{ color: '#818cf8', fontWeight: 600 }}>
            {payload[0].value} req{payload[0].value !== 1 ? 's' : ''}
          </p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="chart-container">
      {chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="rpsGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#818cf8" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#818cf8" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="rgba(255,255,255,0.04)"
              vertical={false}
            />
            <XAxis
              dataKey="time"
              stroke="#55556a"
              fontSize={10}
              tickLine={false}
              axisLine={false}
              interval={9}
            />
            <YAxis
              stroke="#55556a"
              fontSize={10}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="requests"
              stroke="#818cf8"
              strokeWidth={2}
              fill="url(#rpsGradient)"
              dot={false}
              activeDot={{
                r: 4,
                fill: '#818cf8',
                stroke: '#0a0a0f',
                strokeWidth: 2,
              }}
            />
          </AreaChart>
        </ResponsiveContainer>
      ) : (
        <div className="empty-state">
          <div className="empty-state-icon">📊</div>
          <div className="empty-state-text">
            No traffic data yet. Send some requests to see the chart.
          </div>
        </div>
      )}
    </div>
  );
}
