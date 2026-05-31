import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { dataService } from '../api/dataService'
import type { ObjectMeta, Page } from '../types/api'

const PAGE_SIZE = 100

export function ObjectList() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [municipality, setMunicipality] = useState('')
  const [facilityType, setFacilityType] = useState('')
  const [page, setPage] = useState<Page<ObjectMeta> | null>(null)
  const [offset, setOffset] = useState(0)
  const [municipalities, setMunicipalities] = useState<string[]>([])
  const [facilityTypes, setFacilityTypes] = useState<string[]>([])
  const [loading, setLoading] = useState(false)

  // Загружаем фильтры один раз
  useEffect(() => {
    dataService.getObjects({ limit: 5000 }).then(p => {
      const muns = [...new Set(p.items.map(o => o.municipality).filter(Boolean) as string[])].sort()
      const fts = [...new Set(p.items.map(o => o.facility_type).filter(Boolean) as string[])].sort()
      setMunicipalities(muns)
      setFacilityTypes(fts)
    })
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    dataService.getObjects({
      q: q || undefined,
      municipality: municipality || undefined,
      facility_type: facilityType || undefined,
      offset,
      limit: PAGE_SIZE,
    }).then(p => {
      setPage(p)
      setLoading(false)
    })
  }, [q, municipality, facilityType, offset])

  // Debounce поиска
  useEffect(() => {
    const t = setTimeout(() => { setOffset(0); load() }, 300)
    return () => clearTimeout(t)
  }, [q, municipality, facilityType])

  useEffect(() => { load() }, [offset])

  return (
    <div className="max-w-5xl mx-auto p-6">
      <h1 className="text-2xl font-semibold text-slate-800 mb-6">Объекты ЦТП</h1>

      {/* Фильтры */}
      <div className="flex gap-3 mb-5 flex-wrap">
        <input
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-blue-400"
          placeholder="Поиск по названию..."
          value={q}
          onChange={e => setQ(e.target.value)}
        />
        <select
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          value={municipality}
          onChange={e => { setMunicipality(e.target.value); setOffset(0) }}
        >
          <option value="">Все муниципалитеты</option>
          {municipalities.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <select
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          value={facilityType}
          onChange={e => { setFacilityType(e.target.value); setOffset(0) }}
        >
          <option value="">Все типы</option>
          {facilityTypes.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
      </div>

      {/* Таблица */}
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
              <tr><td colSpan={5} className="text-center py-8 text-slate-400">Ничего не найдено</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Пагинация */}
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
