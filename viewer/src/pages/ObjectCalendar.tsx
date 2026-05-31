import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { dataService } from '../api/dataService'
import { Calendar } from '../components/Calendar'
import type { ObjectMeta } from '../types/api'

export function ObjectCalendar() {
  const { object_id } = useParams<{ object_id: string }>()
  const navigate = useNavigate()
  const [meta, setMeta] = useState<ObjectMeta | null>(null)
  const [dates, setDates] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!object_id) return
    Promise.all([
      dataService.getObject(object_id),
      dataService.getCalendar(object_id),
    ]).then(([m, cal]) => {
      setMeta(m)
      setDates(new Set(cal.dates))
      setLoading(false)
    })
  }, [object_id])

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-slate-400">Загрузка...</div>
  )

  return (
    <div className="max-w-3xl mx-auto p-6">
      <button
        onClick={() => navigate('/')}
        className="text-sm text-blue-500 hover:underline mb-4 block"
      >← К списку объектов</button>

      {/* Метаданные */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 mb-6">
        <h1 className="text-xl font-semibold text-slate-800 mb-3">
          {meta?.facility_name ?? `Объект ${object_id}`}
        </h1>
        <div className="grid grid-cols-2 gap-2 text-sm">
          {[
            ['ID', meta?.object_id],
            ['Муниципалитет', meta?.municipality],
            ['Тип объекта', meta?.object_type],
            ['Тип здания', meta?.facility_type],
            ['РСО', meta?.rso],
          ].map(([label, value]) => value ? (
            <div key={label as string}>
              <span className="text-slate-400">{label}: </span>
              <span className="text-slate-700">{value}</span>
            </div>
          ) : null)}
        </div>
        <div className="mt-3 text-sm text-slate-400">
          Дней с данными: <span className="text-slate-600 font-medium">{dates.size}</span>
        </div>
      </div>

      {/* Календарь */}
      {object_id && <Calendar objectId={object_id} dates={dates} />}
    </div>
  )
}
