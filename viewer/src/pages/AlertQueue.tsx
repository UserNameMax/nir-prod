import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlService } from '../api/mlService'
import type { AlertQueue as Queue, TriggerConfig } from '../types/ml'

/**
 * Слои 2+3: ежедневная очередь нарядов на осмотр.
 *
 * Наряд — это не «алерт за день»: серия срабатываний объекта в пределах cooldown
 * схлопывается в одну заявку, потому что открытый наряд не переоткрывают
 * ежедневно. Профиль триггера и гейтинг переключаются здесь же — κ* показывает,
 * во сколько раз авария должна быть дороже осмотра, чтобы правило окупалось.
 */
export function AlertQueue() {
  const navigate = useNavigate()
  const [config, setConfig] = useState<TriggerConfig | null>(null)
  const [dates, setDates] = useState<string[]>([])
  const [date, setDate] = useState<string>('')
  const [profile, setProfile] = useState<string>('')
  const [gate, setGate] = useState(false)
  const [queue, setQueue] = useState<Queue | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([mlService.getTriggerConfig(), mlService.getDates()])
      .then(([cfg, ds]) => {
        setConfig(cfg)
        setProfile(cfg.default)
        setDates(ds)
        setDate(ds[ds.length - 1] ?? '')
      })
      .catch(e => setError(String(e)))
  }, [])

  useEffect(() => {
    if (!profile) return
    setLoading(true)
    setError(null)
    mlService.getQueue({ date: date || undefined, profile, gate, top_n: 200 })
      .then(q => setQueue(q))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [date, profile, gate])

  const spec = config && profile ? config.profiles[profile] : undefined

  if (error) {
    return (
      <div className="max-w-5xl mx-auto p-6">
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
          Модель недоступна: {error}
          <div className="mt-1 text-amber-700">
            Убедитесь, что бандл обучен и опубликован (training-service).
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h1 className="text-2xl font-semibold text-slate-800 mb-1">Очередь на осмотр</h1>
      <p className="text-sm text-slate-500 mb-5">
        Приоритизация внимания диспетчера, а не автодиспетчеризация: система отбирает
        объекты для разбора человеком.
      </p>

      <div className="flex gap-3 mb-5 flex-wrap items-center">
        <select
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          value={date}
          onChange={e => setDate(e.target.value)}
        >
          {dates.map(d => <option key={d} value={d}>{d}</option>)}
        </select>

        <select
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          value={profile}
          onChange={e => setProfile(e.target.value)}
        >
          {config && Object.entries(config.profiles).map(([name, p]) => (
            <option key={name} value={name}>
              {name}{p.kappa_star != null ? ` · κ*=${p.kappa_star}` : ''}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={gate}
            onChange={e => setGate(e.target.checked)}
            className="rounded border-slate-300"
          />
          Гейтинг по хронике
        </label>

        {queue && (
          <span className="text-sm text-slate-500 ml-auto">
            нарядов: <span className="font-medium text-slate-700">{queue.total_orders}</span>
            {' · '}cooldown {queue.cooldown_days} дн
          </span>
        )}
      </div>

      {spec && (
        <div className="bg-white border border-slate-200 rounded-xl p-4 mb-5 text-sm text-slate-600">
          <span className="font-medium text-slate-700">Правило:</span>{' '}
          {describeProfile(spec.type, spec.n, spec.span, spec.chronic_top)}
          {spec.kappa_star != null && (
            <>
              {' · '}
              <span title="Во сколько раз авария должна быть дороже осмотра, чтобы правило окупилось">
                порог окупаемости κ* = <span className="font-medium">{spec.kappa_star}</span>
              </span>
            </>
          )}
          {spec.lead_within_H != null && (
            <>{' · '}раннесть {(spec.lead_within_H * 100).toFixed(0)}%</>
          )}
        </div>
      )}

      {loading && <div className="text-sm text-slate-400">Загрузка…</div>}

      {queue && !loading && (
        queue.orders.length === 0 ? (
          <div className="text-sm text-slate-500">На эту дату открытых нарядов нет.</div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="text-left font-medium px-4 py-2">Объект</th>
                  <th className="text-left font-medium px-4 py-2">Открыт</th>
                  <th className="text-left font-medium px-4 py-2">Последний алерт</th>
                  <th className="text-right font-medium px-4 py-2">Дней в алерте</th>
                  <th className="text-right font-medium px-4 py-2">Пик риска</th>
                  <th className="text-right font-medium px-4 py-2">Хроника</th>
                </tr>
              </thead>
              <tbody>
                {queue.orders.map(o => (
                  <tr
                    key={`${o.object_id}-${o.opened_at}`}
                    className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                    onClick={() => navigate(`/risk/${o.object_id}`)}
                  >
                    <td className="px-4 py-2 font-medium text-slate-700">{o.object_id}</td>
                    <td className="px-4 py-2 text-slate-600">{o.opened_at}</td>
                    <td className="px-4 py-2 text-slate-600">{o.last_alert_at}</td>
                    <td className="px-4 py-2 text-right text-slate-600">{o.alert_days}</td>
                    <td className="px-4 py-2 text-right text-slate-700">{o.peak_score.toFixed(3)}</td>
                    <td className="px-4 py-2 text-right text-slate-500">
                      {o.chronic_rank != null ? `#${o.chronic_rank}` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </div>
  )
}

function describeProfile(type: string, n?: number, span?: number, chronicTop?: string): string {
  if (type === 'persist') return `риск выше порога ${n} наблюдений подряд`
  if (type === 'ewma') return `EWMA-сглаживание риска (span ${span})`
  if (type === 'gate') return `острый сигнал И объект в ${chronicTop} хроники`
  return 'порог по риску без сглаживания'
}
