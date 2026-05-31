import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { dataService } from '../api/dataService'
import type { ObjectMeta, Page } from '../types/api'

const PAGE_SIZE = 100

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

export function DayObjects() {
  const { date } = useParams<{ date: string }>()
  const navigate = useNavigate()
  const [page, setPage] = useState<Page<ObjectMeta> | null>(null)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    if (!date) return
    setLoading(true)
    dataService.getObjectsByDay({ date, offset, limit: PAGE_SIZE }).then(p => {
      setPage(p)
      setLoading(false)
    })
  }, [date, offset])

  useEffect(() => { load() }, [load])

  return (
    <div className="max-w-5xl mx-auto p-6">
      <button
        onClick={() => navigate('/calendar')}
        className="text-sm text-blue-500 hover:underline mb-4 block"
      >← К календарю</button>

      <h1 className="text-2xl font-semibold text-slate-800 mb-1">
        Объекты за {date ? formatDate(date) : '—'}
      </h1>
      {page && (
        <p className="text-sm text-slate-400 mb-6">
          Всего объектов с данными: <span className="text-slate-600 font-medium">{page.total}</span>
        </p>
      )}

      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              {['ID', 'Название', 'Муниципалитет', 'Тип объекта', 'Тип здания'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr><td colSpan={5} className="text-center py-8 text-slate-400">Загрузка...</td></tr>
            )}
            {!loading && page?.items.map(obj => (
              <tr
                key={obj.object_id}
                className="hover:bg-blue-50 cursor-pointer transition-colors"
                onClick={() => navigate(`/object/${obj.object_id}`)}
              >
                <td className="px-4 py-3 text-slate-500 font-mono text-xs">{obj.object_id}</td>
                <td className="px-4 py-3 font-medium text-slate-700">{obj.facility_name ?? '—'}</td>
                <td className="px-4 py-3 text-slate-500">{obj.municipality ?? '—'}</td>
                <td className="px-4 py-3 text-slate-500">{obj.object_type ?? '—'}</td>
                <td className="px-4 py-3 text-slate-500">{obj.facility_type ?? '—'}</td>
              </tr>
            ))}
            {!loading && page?.items.length === 0 && (
              <tr><td colSpan={5} className="text-center py-8 text-slate-400">Нет данных</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {page && page.total > PAGE_SIZE && (
        <div className="flex items-center justify-between mt-4 text-sm text-slate-500">
          <span>Показано {offset + 1}–{Math.min(offset + PAGE_SIZE, page.total)} из {page.total}</span>
          <div className="flex gap-2">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
              className="px-3 py-1.5 rounded border border-slate-300 disabled:opacity-40 hover:bg-slate-50"
            >← Назад</button>
            <button
              disabled={offset + PAGE_SIZE >= page.total}
              onClick={() => setOffset(o => o + PAGE_SIZE)}
              className="px-3 py-1.5 rounded border border-slate-300 disabled:opacity-40 hover:bg-slate-50"
            >Вперёд →</button>
          </div>
        </div>
      )}
    </div>
  )
}
