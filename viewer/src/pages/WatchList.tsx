import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlService } from '../api/mlService'
import type { Watchlist } from '../types/ml'

/**
 * Слой 1: хронический риск объекта — для планового ТО, вне суточной динамики.
 *
 * Модель подписана как «класс нелинейных», а не «лучшая»: доверительные
 * интервалы C-index перекрываются с другими нелинейными методами, и выделять
 * победителя статистически необоснованно.
 */
export function WatchList() {
  const navigate = useNavigate()
  const [data, setData] = useState<Watchlist | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    mlService.getWatchlist(100).then(setData).catch(e => setError(String(e)))
  }, [])

  if (error) {
    return (
      <div className="max-w-5xl mx-auto p-6">
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
          Модель недоступна: {error}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto p-6">
      <h1 className="text-2xl font-semibold text-slate-800 mb-1">Хронический риск</h1>
      <p className="text-sm text-slate-500 mb-5">
        Ранжирование объектов для планового обслуживания. Не суточный алерт —
        накопленная предрасположенность объекта к отказу.
      </p>

      {data && (
        <>
          <div className="bg-white border border-slate-200 rounded-xl p-4 mb-5 text-sm text-slate-600">
            {data.model_note} · объектов в рейтинге: {data.total_objects}
          </div>

          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="text-left font-medium px-4 py-2 w-20">Ранг</th>
                  <th className="text-left font-medium px-4 py-2">Объект</th>
                  <th className="text-right font-medium px-4 py-2">Скор хроники</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(item => (
                  <tr
                    key={item.object_id}
                    className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                    onClick={() => navigate(`/risk/${item.object_id}`)}
                  >
                    <td className="px-4 py-2 text-slate-500">#{item.rank}</td>
                    <td className="px-4 py-2 font-medium text-slate-700">{item.object_id}</td>
                    <td className="px-4 py-2 text-right text-slate-600">
                      {item.chronic_score.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
