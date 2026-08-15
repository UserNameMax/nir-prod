import {
  Area, ComposedChart, CartesianGrid, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import type { TimelinePoint } from '../types/ml'

interface Props {
  data: TimelinePoint[]
  p75: number | null
  p90: number | null
  threshold: number
}

/**
 * История дневного риска объекта.
 *
 * Уровни p75/p90 — ПООБЪЕКТНЫЕ: «высоко» для зарегулированного ЦТП и для
 * шумного — разные величины. Розовая заливка отмечает зону выше p75, пунктир —
 * общесетевой порог алерта.
 */
export function RiskChart({ data, p75, p90, threshold }: Props) {
  const chartData = data.map(p => ({
    date: p.date,
    risk: p.risk_score,
    above: p75 != null && p.risk_score >= p75 ? p.risk_score : null,
  }))

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="text-sm font-medium text-slate-600 mb-3">
        Риск по дням <span className="text-slate-400">(сырой скор модели)</span>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            minTickGap={40}
          />
          <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: '#94a3b8' }} width={40} />
          <Tooltip
            formatter={(v) => (v == null ? ['—', 'риск'] : [Number(v).toFixed(3), 'риск'])}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
          />
          <Area
            type="monotone"
            dataKey="above"
            stroke="none"
            fill="#fecdd3"
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="risk"
            stroke="#2563eb"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          {p75 != null && (
            <ReferenceLine y={p75} stroke="#fb7185" strokeDasharray="4 4"
              label={{ value: 'p75', fontSize: 10, fill: '#fb7185', position: 'right' }} />
          )}
          {p90 != null && (
            <ReferenceLine y={p90} stroke="#e11d48" strokeDasharray="4 4"
              label={{ value: 'p90', fontSize: 10, fill: '#e11d48', position: 'right' }} />
          )}
          <ReferenceLine y={threshold} stroke="#64748b" strokeDasharray="2 6"
            label={{ value: 'порог алерта', fontSize: 10, fill: '#64748b', position: 'insideTopRight' }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
