import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { mlService } from '../api/mlService'
import { RiskChart } from '../components/RiskChart'
import type { ObjectCard, ObjectThresholds, ObjectTimeline } from '../types/ml'

/**
 * Слой 4: всё про объект на одном экране — риск, срок, драйверы физики.
 *
 * Калиброванная вероятность подписана как ориентир: при слабом сигнале изотоника
 * схлопывается к базовой ставке, поэтому решение о пороге принимается по рангу
 * сырого скора, а не по этой величине.
 */
export function ObjectDrilldown() {
  const { object_id = '' } = useParams()
  const navigate = useNavigate()
  const [card, setCard] = useState<ObjectCard | null>(null)
  const [timeline, setTimeline] = useState<ObjectTimeline | null>(null)
  const [thresholds, setThresholds] = useState<ObjectThresholds | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!object_id) return
    setError(null)
    Promise.all([
      mlService.getObjectCard(object_id),
      mlService.getObjectTimeline(object_id),
      mlService.getObjectThresholds(object_id).catch(() => null),
    ])
      .then(([c, t, th]) => { setCard(c); setTimeline(t); setThresholds(th) })
      .catch(e => setError(String(e)))
  }, [object_id])

  if (error) {
    return (
      <div className="max-w-5xl mx-auto p-6">
        <button onClick={() => navigate(-1)} className="text-sm text-blue-600 mb-4">← назад</button>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">{error}</div>
      </div>
    )
  }

  if (!card || !timeline) {
    return <div className="max-w-5xl mx-auto p-6 text-sm text-slate-400">Загрузка…</div>
  }

  const meta = card.meta ?? {}

  return (
    <div className="max-w-6xl mx-auto p-6">
      <button onClick={() => navigate(-1)} className="text-sm text-blue-600 mb-4">← назад</button>

      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-slate-800">
          {meta.facility_name || `Объект ${card.object_id}`}
        </h1>
        <div className="text-sm text-slate-500 mt-1">
          {[meta.facility_type, meta.object_type, meta.municipality, meta.rso]
            .filter(Boolean).join(' · ') || `ID ${card.object_id}`}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Tile
          label="Риск на дату"
          value={card.raw_score.toFixed(3)}
          hint={`${card.date} · ранг #${card.rank}`}
          accent={card.raw_score >= card.alert_threshold}
        />
        <Tile
          label="Срок до аварии"
          value={card.aft_median_days != null ? `${Math.round(card.aft_median_days)} дн` : '—'}
          hint="медиана параметрической модели"
        />
        <Tile
          label="Вероятность"
          value={`${(card.calibrated_prob * 100).toFixed(1)}%`}
          hint="для ориентира, не порог"
        />
        <Tile
          label="Хроника"
          value={card.chronic_rank != null ? `#${card.chronic_rank}` : '—'}
          hint="ранг планового ТО"
        />
      </div>

      <div className="bg-slate-50 border border-slate-200 rounded-xl p-3 mb-5 text-xs text-slate-500">
        {card.calibration_note}
      </div>

      <div className="mb-5">
        <RiskChart
          data={timeline.timeline}
          p75={thresholds?.p75 ?? card.p75}
          p90={thresholds?.p90 ?? card.p90}
          threshold={card.alert_threshold}
        />
      </div>

      {card.daily_profile.length > 0 && <DailyProfile points={card.daily_profile} date={card.date} />}
    </div>
  )
}

function Tile({ label, value, hint, accent }: {
  label: string; value: string; hint?: string; accent?: boolean
}) {
  return (
    <div className={`rounded-xl border p-4 ${accent ? 'border-rose-200 bg-rose-50' : 'border-slate-200 bg-white'}`}>
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-xl font-semibold mt-1 ${accent ? 'text-rose-700' : 'text-slate-800'}`}>{value}</div>
      {hint && <div className="text-xs text-slate-400 mt-1">{hint}</div>}
    </div>
  )
}

/** Сырой суточный профиль: ночной провал давления — визуальная проверка физики. */
function DailyProfile({ points, date }: { points: ObjectCard['daily_profile']; date: string }) {
  const data = points.map(p => ({
    time: new Date(p.ts).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }),
    p_supply: p.p_supply,
    p_return: p.p_return,
    t_supply: p.t_supply,
    t_return: p.t_return,
  }))

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="text-sm font-medium text-slate-600 mb-3">
        Суточный профиль <span className="text-slate-400">({date}, сырые показания)</span>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="time" tick={{ fontSize: 11, fill: '#94a3b8' }} minTickGap={50} />
          <YAxis yAxisId="p" tick={{ fontSize: 11, fill: '#94a3b8' }} width={40} />
          <YAxis yAxisId="t" orientation="right" tick={{ fontSize: 11, fill: '#94a3b8' }} width={40} />
          <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line yAxisId="p" type="monotone" dataKey="p_supply" name="P подача" stroke="#2563eb" strokeWidth={1.5} dot={false} />
          <Line yAxisId="p" type="monotone" dataKey="p_return" name="P обратка" stroke="#38bdf8" strokeWidth={1.5} dot={false} />
          <Line yAxisId="t" type="monotone" dataKey="t_supply" name="T подача" stroke="#f97316" strokeWidth={1} dot={false} />
          <Line yAxisId="t" type="monotone" dataKey="t_return" name="T обратка" stroke="#fbbf24" strokeWidth={1} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
