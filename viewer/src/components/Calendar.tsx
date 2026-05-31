import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

interface Props {
  objectId: string
  dates: Set<string>  // 'YYYY-MM-DD'
}

const MONTHS = [
  'Январь','Февраль','Март','Апрель','Май','Июнь',
  'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь',
]
const DOW = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']

function daysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate()
}

function firstDowOfMonth(year: number, month: number): number {
  // 0=Пн..6=Вс
  return (new Date(year, month, 1).getDay() + 6) % 7
}

function toDateStr(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

export function Calendar({ objectId, dates }: Props) {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth())
  const navigate = useNavigate()

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

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 select-none">
      {/* Навигация */}
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
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((day, i) => {
          if (day === null) return <div key={`empty-${i}`} />

          const dateStr = toDateStr(year, month, day)
          const hasData = dates.has(dateStr)
          const isToday = dateStr === todayStr

          return (
            <button
              key={dateStr}
              disabled={!hasData}
              onClick={() => navigate(`/object/${objectId}/day/${dateStr}`)}
              className={[
                'aspect-square flex items-center justify-center rounded-lg text-sm transition-colors',
                isToday ? 'ring-2 ring-blue-400 ring-offset-1' : '',
                hasData
                  ? 'bg-blue-500 text-white hover:bg-blue-600 cursor-pointer font-medium'
                  : 'text-slate-300 cursor-default',
              ].join(' ')}
            >
              {day}
            </button>
          )
        })}
      </div>
    </div>
  )
}
