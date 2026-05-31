import { useEffect, useRef, useState } from 'react'
import { ingestService } from '../api/ingestService'
import type { IngestJob } from '../types/api'

function StatusBadge({ status }: { status: IngestJob['status'] }) {
  const styles = {
    processing: 'bg-yellow-100 text-yellow-700',
    done: 'bg-green-100 text-green-700',
    error: 'bg-red-100 text-red-700',
  }
  const labels = { processing: 'Обработка', done: 'Готово', error: 'Ошибка' }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  )
}

export function IngestPage() {
  const [dragging, setDragging] = useState(false)
  const [activeJob, setActiveJob] = useState<IngestJob | null>(null)
  const [history, setHistory] = useState<IngestJob[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    ingestService.listJobs().then(setHistory).catch(() => {})
  }, [])

  useEffect(() => {
    if (activeJob?.status === 'processing') {
      pollRef.current = setInterval(async () => {
        const job = await ingestService.getJob(activeJob.job_id)
        setActiveJob(job)
        if (job.status !== 'processing') {
          clearInterval(pollRef.current!)
          ingestService.listJobs().then(setHistory)
        }
      }, 2000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [activeJob?.job_id, activeJob?.status])

  async function handleFile(file: File) {
    setError(null)
    setUploading(true)
    try {
      const { job_id } = await ingestService.upload(file)
      const job = await ingestService.getJob(job_id)
      setActiveJob(job)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setUploading(false)
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  const progress = activeJob?.files_total
    ? Math.round((activeJob.files_processed ?? 0) / activeJob.files_total * 100)
    : null

  return (
    <div className="max-w-3xl mx-auto p-6">
      <h1 className="text-2xl font-semibold text-slate-800 mb-6">Загрузка выгрузки</h1>

      {/* Зона загрузки */}
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={[
          'border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors mb-6',
          dragging ? 'border-blue-400 bg-blue-50' : 'border-slate-300 hover:border-blue-400 hover:bg-slate-50',
        ].join(' ')}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".rar,.zip"
          className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
        />
        <div className="text-3xl mb-2">📦</div>
        <div className="text-slate-600 font-medium">Перетащите архив сюда или нажмите</div>
        <div className="text-slate-400 text-sm mt-1">Форматы: .rar, .zip</div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 mb-4">
          {error}
        </div>
      )}

      {uploading && (
        <div className="text-slate-500 text-sm text-center mb-4">Загрузка файла...</div>
      )}

      {/* Прогресс активной задачи */}
      {activeJob && (
        <div className="bg-white rounded-xl border border-slate-200 p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <span className="font-medium text-slate-700 text-sm">{activeJob.filename}</span>
            <StatusBadge status={activeJob.status} />
          </div>

          {activeJob.status === 'processing' && progress !== null && (
            <>
              <div className="w-full bg-slate-100 rounded-full h-2 mb-2">
                <div
                  className="bg-blue-500 h-2 rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="text-xs text-slate-400">
                Файлов: {activeJob.files_processed}/{activeJob.files_total}
                {activeJob.current_file && <> · {activeJob.current_file}</>}
                {activeJob.rows_processed !== null && (
                  <> · Строк: {activeJob.rows_processed.toLocaleString()}</>
                )}
              </div>
            </>
          )}

          {activeJob.status === 'done' && activeJob.stats && (
            <div className="grid grid-cols-2 gap-2 text-sm">
              {[
                ['Файлов xlsx', activeJob.stats.xlsx_files_found],
                ['Новых записей', activeJob.stats.sensors_inserted.toLocaleString()],
                ['Дубликатов', activeJob.stats.sensors_duplicates.toLocaleString()],
                ['Объектов', activeJob.stats.objects_count],
                ['Период', activeJob.stats.period_from
                  ? `${activeJob.stats.period_from.slice(0, 10)} — ${activeJob.stats.period_to?.slice(0, 10)}`
                  : '—'],
              ].map(([label, value]) => (
                <div key={label as string}>
                  <span className="text-slate-400">{label}: </span>
                  <span className="text-slate-700 font-medium">{value}</span>
                </div>
              ))}
            </div>
          )}

          {activeJob.status === 'error' && (
            <div className="text-red-600 text-sm">{activeJob.error}</div>
          )}
        </div>
      )}

      {/* История */}
      {history.length > 0 && (
        <>
          <h2 className="text-base font-medium text-slate-700 mb-3">История загрузок</h2>
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  {['Файл', 'Статус', 'Дата', 'Записей', 'Период'].map(h => (
                    <th key={h} className="px-4 py-2 text-left text-xs font-medium text-slate-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {history.map(job => (
                  <tr key={job.job_id}>
                    <td className="px-4 py-2 text-slate-700">{job.filename}</td>
                    <td className="px-4 py-2"><StatusBadge status={job.status} /></td>
                    <td className="px-4 py-2 text-slate-400 text-xs">{job.created_at.slice(0, 16).replace('T', ' ')}</td>
                    <td className="px-4 py-2 text-slate-600">{job.stats?.sensors_inserted.toLocaleString() ?? '—'}</td>
                    <td className="px-4 py-2 text-slate-400 text-xs">
                      {job.stats?.period_from
                        ? `${job.stats.period_from.slice(0, 10)} — ${job.stats.period_to?.slice(0, 10)}`
                        : '—'}
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
