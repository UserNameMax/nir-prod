import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import type { SensorRecord } from '../types/api'

interface Props {
  data: SensorRecord[]
  field: 't_supply' | 't_return' | 'p_supply' | 'p_return'
  label: string
  unit: string
  color: string
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function formatTooltipTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('ru-RU')
}

export function SensorChart({ data, field, label, unit, color }: Props) {
  const chartData = data.map(r => ({
    ts: r.ts_measurement,
    value: r[field],
  }))

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="text-sm font-medium text-slate-600 mb-3">
        {label} <span className="text-slate-400">({unit})</span>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis
            dataKey="ts"
            tickFormatter={formatTime}
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            minTickGap={60}
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            width={40}
          />
          <Tooltip
            labelFormatter={(v) => formatTooltipTime(v as number)}
            formatter={(v) => (v == null ? ['—', label] : [`${v} ${unit}`, label])}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
