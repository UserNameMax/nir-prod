import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { dataService } from '../api/dataService'

const MONTHS = [
  'Январь','Февраль','Март','Апрель','Май','Июнь',
  'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь',
]
const DOW = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']

function daysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate()
}

function firstDowOfMonth(year: number, month: number): number {
  return (new Date(year, month, 1).getDay() + 6) % 7
}

function toDateStr(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function monthRange(year: number, month: number): { from: string; to: string } {
  const from = toDateStr(year, month, 1)
  const to = toDateStr(year, month, daysInMonth(year, month))
  return { from, to }
}

export function GlobalCalendar() {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth())
  // day -> objects_count
  const [summary, setSummary] = useState<Map<string, number>>(new Map())
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true)
    const { from, to } = monthRange(year, month)
    dataService.getCalendarSummary({ from_date: from, to_date: to }).then(rows => {
      setSummary(new Map(rows.map(r => [r.day, r.objects_count])))
      setLoading(false)
    })
  }, [year, month])

  const prevMonth = () => {
    if (month === 0) { setYear(y => y - 1); setMonth(11) }
    else setMonth(m => m - 1)
  }
  const nextMonth = () => {
    if (month === 11) { setYear(y => y + 1); setMonth(0) }
    else setMonth(m => m + 1)
  }

  const totalDays = daysInMonth(year, month)
  const firstDow = firstDowOfMonth(year, month)
  const todayStr = toDateStr(today.getFullYear(), today.getMonth(), today.getDate())

  const cells: (number | null)[] = [
    ...Array(firstDow).fill(null),
    ...Array.from({ length: totalDays }, (_, i) => i + 1),
  ]

  const daysWithData = [...summary.values()].filter(n => n > 0).length

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-slate-800 mb-1">Календарь данных</h1>
      <p className="text-sm text-slate-400 mb-6">Дни, в которые есть показания хотя бы по одному объекту</p>

      <div className="bg-white rounded-xl border border-slate-200 p-5 select-none">
        {/* Навигация по месяцам */}
        <div className="flex items-center justify-between mb-4">
          <button onClick={prevMonth} className="p-1 rounded hover:bg-slate-100 text-slate-500">←</button>
          <span className="font-medium text-slate-700">{MONTHS[month]} {year}</span>
          <button onClick={nextMonth} className="p-1 rounded hover:bg-slate-100 text-slate-500">→</button>
        </div>

        {/* Дни недели */}
        <div className="grid grid-cols-7 mb-1">
          {DOW.map(d => (
            <div key={d} className="text-center text-xs font-medium text-slate-400 py-1">{d}</div>
          ))}
        </div>

        {/* Ячейки */}
        {loading ? (
          <div className="h-40 flex items-center justify-center text-slate-400 text-sm">Загрузка...</div>
        ) : (
          <div className="grid grid-cols-7 gap-0.5">
            {cells.map((day, i) => {
              if (day === null) return <div key={`empty-${i}`} />

              const dateStr = toDateStr(year, month, day)
              const count = summary.get(dateStr) ?? 0
              const hasData = count > 0
              const isToday = dateStr === todayStr

              return (
                <div
                  key={dateStr}
                  title={hasData ? `${count} объектов` : undefined}
                  onClick={hasData ? () => navigate(`/calendar/${dateStr}`) : undefined}
                  className={[
                    'aspect-square flex items-center justify-center rounded-lg text-sm transition-colors',
                    isToday ? 'ring-2 ring-blue-400 ring-offset-1' : '',
                    hasData
                      ? 'bg-blue-500 text-white font-medium cursor-pointer hover:bg-blue-600'
                      : 'text-slate-300 cursor-default',
                  ].join(' ')}
                >
                  {day}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {!loading && (
        <p className="text-sm text-slate-400 mt-3 text-center">
          {daysWithData > 0
            ? <>В этом месяце данные есть за <span className="text-slate-600 font-medium">{daysWithData}</span> {daysWithData === 1 ? 'день' : daysWithData < 5 ? 'дня' : 'дней'}</>
            : 'В этом месяце данных нет'
          }
        </p>
      )}
    </div>
  )
}
