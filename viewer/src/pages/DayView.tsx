import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { dataService } from '../api/dataService'
import { SensorChart } from '../components/SensorChart'
import type { SensorRecord } from '../types/api'

const CHARTS: Array<{
  field: 't_supply' | 't_return' | 'p_supply' | 'p_return'
  label: string
  unit: string
  color: string
}> = [
  { field: 't_supply', label: 'Температура подачи',    unit: '°C',  color: '#ef4444' },
  { field: 't_return', label: 'Температура обратная',  unit: '°C',  color: '#f97316' },
  { field: 'p_supply', label: 'Давление подачи',       unit: 'МПа', color: '#3b82f6' },
  { field: 'p_return', label: 'Давление обратное',     unit: 'МПа', color: '#8b5cf6' },
]

function dayToTs(dateStr: string): { from: number; to: number } {
  const d = new Date(dateStr)
  const from = Math.floor(d.getTime() / 1000)
  const to = from + 86400 - 1
  return { from, to }
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}


function getCachedCalendar(object_id: string): string[] | null {
  try {
    const raw = sessionStorage.getItem(`cal:${object_id}`)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function setCachedCalendar(object_id: string, dates: string[]) {
  try { sessionStorage.setItem(`cal:${object_id}`, JSON.stringify(dates)) } catch { /* ignore */ }
}

export function DayView() {
  const { object_id, date } = useParams<{ object_id: string; date: string }>()
  const navigate = useNavigate()
  const [records, setRecords] = useState<SensorRecord[]>([])
  const [dates, setDates] = useState<string[]>([])
  const [loadingData, setLoadingData] = useState(true)

  useEffect(() => {
    if (!object_id || !date) return
    setLoadingData(true)

    const { from, to } = dayToTs(date)

    // Графики не ждут календарь
    dataService.getSensors({ object_id, from_ts: from, to_ts: to, limit: 10000 })
      .then(page => {
        setRecords(page.items)
        setLoadingData(false)
      })

    // Календарь — из кеша или по сети, не блокирует рендер
    const cached = getCachedCalendar(object_id)
    if (cached) {
      setDates(cached)
    } else {
      dataService.getCalendar(object_id).then(cal => {
        setDates(cal.dates)
        setCachedCalendar(object_id, cal.dates)
      })
    }
  }, [object_id, date])

  const currentIdx = dates.indexOf(date ?? '')
  const prevDate = currentIdx > 0 ? dates[currentIdx - 1] : null
  const nextDate = currentIdx < dates.length - 1 ? dates[currentIdx + 1] : null

  return (
    <div className="max-w-5xl mx-auto p-6">
      {/* Навигация */}
      <div className="flex items-center gap-4 mb-5">
        <button
          onClick={() => navigate(`/object/${object_id}`)}
          className="text-sm text-blue-500 hover:underline"
        >← Календарь</button>
        <span className="text-slate-300">|</span>
        <button
          disabled={!prevDate}
          onClick={() => navigate(`/object/${object_id}/day/${prevDate}`)}
          className="text-sm text-slate-600 hover:text-blue-500 disabled:text-slate-300 disabled:cursor-default"
        >← Предыдущий день</button>
        <h2 className="flex-1 text-center text-lg font-semibold text-slate-700">
          {date ? formatDate(date) : ''}
        </h2>
        <button
          disabled={!nextDate}
          onClick={() => navigate(`/object/${object_id}/day/${nextDate}`)}
          className="text-sm text-slate-600 hover:text-blue-500 disabled:text-slate-300 disabled:cursor-default"
        >Следующий день →</button>
      </div>

      {/* Инфо */}
      <div className="text-sm text-slate-400 mb-5 text-center">
        {loadingData ? 'Загрузка...' : `${records.length} измерений`}
      </div>

      {/* Графики 2×2 */}
      {!loadingData && records.length > 0 && (
        <div className="grid grid-cols-2 gap-4">
          {CHARTS.map(c => (
            <SensorChart
              key={c.field}
              data={records}
              field={c.field}
              label={c.label}
              unit={c.unit}
              color={c.color}
            />
          ))}
        </div>
      )}

      {!loadingData && records.length === 0 && (
        <div className="text-center text-slate-400 py-16">Нет данных за этот день</div>
      )}
    </div>
  )
}
