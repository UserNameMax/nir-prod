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

  // Всегда 6 строк × 7 столбцов = 42 ячейки
  const cells: (number | null)[] = [
    ...Array(firstDow).fill(null),
    ...Array.from({ length: totalDays }, (_, i) => i + 1),
    ...Array(42 - firstDow - totalDays).fill(null),
  ]

  const daysWithData = [...summary.values()].filter(n => n > 0).length

  return (
    <div className="h-full flex flex-col p-4 gap-3 select-none">
      {/* Заголовок */}
      <div className="flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">Календарь данных</h1>
          {!loading && (
            <p className="text-xs text-slate-400 mt-0.5">
              {daysWithData > 0
                ? <>Данные за <span className="text-slate-600 font-medium">{daysWithData}</span> {daysWithData === 1 ? 'день' : daysWithData < 5 ? 'дня' : 'дней'} в этом месяце</>
                : 'В этом месяце данных нет'}
            </p>
          )}
        </div>
        {/* Навигация по месяцам */}
        <div className="flex items-center gap-3">
          <button onClick={prevMonth} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-white border border-transparent hover:border-slate-200 text-slate-500 transition-colors">←</button>
          <span className="font-medium text-slate-700 w-36 text-center">{MONTHS[month]} {year}</span>
          <button onClick={nextMonth} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-white border border-transparent hover:border-slate-200 text-slate-500 transition-colors">→</button>
        </div>
      </div>

      {/* Карточка календаря */}
      <div className="flex-1 min-h-0 bg-white rounded-xl border border-slate-200 p-4 flex flex-col gap-1">
        {/* Дни недели */}
        <div className="grid grid-cols-7 shrink-0">
          {DOW.map(d => (
            <div key={d} className="text-center text-xs font-medium text-slate-400 py-1">{d}</div>
          ))}
        </div>

        {/* Сетка дней — flex-1, всегда 6 строк */}
        {loading ? (
          <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">Загрузка...</div>
        ) : (
          <div className="flex-1 min-h-0 grid grid-cols-7 grid-rows-6 gap-1">
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
                    'flex items-center justify-center rounded-lg text-sm font-medium transition-colors',
                    isToday ? 'ring-2 ring-blue-400 ring-offset-1' : '',
                    hasData
                      ? 'bg-blue-500 text-white cursor-pointer hover:bg-blue-600'
                      : 'text-slate-200 cursor-default',
                  ].join(' ')}
                >
                  {day}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
