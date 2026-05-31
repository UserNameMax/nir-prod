import { useEffect, useRef, useState } from 'react'
import { ingestService } from '../api/ingestService'
import type { IngestJob } from '../types/api'

function StatusBadge({ status }: { status: IngestJob['status'] }) {
  const styles: Record<IngestJob['status'], string> = {
    queued:     'bg-slate-100 text-slate-600',
    processing: 'bg-yellow-100 text-yellow-700',
    done:       'bg-green-100 text-green-700',
    error:      'bg-red-100 text-red-700',
  }
  const labels: Record<IngestJob['status'], string> = {
    queued:     'В очереди',
    processing: 'Обработка',
    done:       'Готово',
    error:      'Ошибка',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  )
}

function JobProgress({ job }: { job: IngestJob }) {
  const isMerging = job.merge_total !== null && job.status === 'processing'
  const isParsing = !isMerging && job.files_total !== null && job.status === 'processing'

  let pct = 0
  let label = ''

  if (isParsing && job.files_total) {
    pct = Math.round((job.files_processed ?? 0) / job.files_total * 100)
    label = `Файлов: ${job.files_processed}/${job.files_total}`
    if (job.current_file) label += ` · ${job.current_file}`
    if (job.rows_processed) label += ` · Строк: ${job.rows_processed.toLocaleString()}`
  } else if (isMerging && job.merge_total) {
    pct = Math.round((job.merge_processed ?? 0) / job.merge_total * 100)
    label = `Сохранение: ${(job.merge_processed ?? 0).toLocaleString()} / ${job.merge_total.toLocaleString()} строк`
  }

  if (job.status === 'queued') {
    return <div className="text-xs text-slate-400 mt-2">Ожидание в очереди...</div>
  }

  if (job.status !== 'processing') return null

  return (
    <div className="mt-3">
      <div className="w-full bg-slate-100 rounded-full h-1.5 mb-1.5">
        <div
          className="bg-blue-500 h-1.5 rounded-full transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-xs text-slate-400">{label}</div>
    </div>
  )
}

function JobCard({ job }: { job: IngestJob }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-700 text-sm truncate mr-3">{job.filename}</span>
        <StatusBadge status={job.status} />
      </div>

      <JobProgress job={job} />

      {job.status === 'done' && job.stats && (
        <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          {([
            ['Файлов xlsx', job.stats.xlsx_files_found],
            ['Новых записей', job.stats.sensors_inserted.toLocaleString()],
            ['Дубликатов', job.stats.sensors_duplicates.toLocaleString()],
            ['Объектов', job.stats.objects_count],
            ['Период', job.stats.period_from
              ? `${job.stats.period_from.slice(0, 10)} — ${job.stats.period_to?.slice(0, 10)}`
              : '—'],
          ] as [string, string | number][]).map(([label, value]) => (
            <div key={label}>
              <span className="text-slate-400">{label}: </span>
              <span className="text-slate-700 font-medium">{value}</span>
            </div>
          ))}
        </div>
      )}

      {job.status === 'error' && (
        <div className="mt-2 text-red-600 text-sm">{job.error}</div>
      )}
    </div>
  )
}

const ACTIVE_STATUSES: IngestJob['status'][] = ['queued', 'processing']

export function IngestPage() {
  const [dragging, setDragging] = useState(false)
  const [jobs, setJobs] = useState<IngestJob[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Загрузить историю + запустить поллинг если есть активные задачи
  function startPollingIfNeeded(jobList: IngestJob[]) {
    const hasActive = jobList.some(j => ACTIVE_STATUSES.includes(j.status))
    if (hasActive && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        const updated = await ingestService.listJobs().catch(() => null)
        if (!updated) return
        setJobs(updated)
        const stillActive = updated.some(j => ACTIVE_STATUSES.includes(j.status))
        if (!stillActive) {
          clearInterval(pollRef.current!)
          pollRef.current = null
        }
      }, 2000)
    }
  }

  useEffect(() => {
    ingestService.listJobs().then(list => {
      setJobs(list)
      startPollingIfNeeded(list)
    }).catch(() => {})
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  async function handleFiles(files: File[]) {
    if (!files.length) return
    setError(null)
    setUploading(true)
    try {
      await ingestService.upload(files)
      const list = await ingestService.listJobs()
      setJobs(list)
      startPollingIfNeeded(list)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const files = Array.from(e.dataTransfer.files).filter(
      f => f.name.endsWith('.rar') || f.name.endsWith('.zip')
    )
    handleFiles(files)
  }

  const activeJobs = jobs.filter(j => ACTIVE_STATUSES.includes(j.status))
  const historyJobs = jobs.filter(j => !ACTIVE_STATUSES.includes(j.status))

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
          multiple
          className="hidden"
          onChange={e => {
            const files = Array.from(e.target.files ?? [])
            if (files.length) handleFiles(files)
            e.target.value = ''
          }}
        />
        <div className="text-3xl mb-2">📦</div>
        <div className="text-slate-600 font-medium">Перетащите архивы сюда или нажмите</div>
        <div className="text-slate-400 text-sm mt-1">Форматы: .rar, .zip · можно выбрать несколько</div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 mb-4">
          {error}
        </div>
      )}

      {uploading && (
        <div className="text-slate-500 text-sm text-center mb-4">Загрузка файлов...</div>
      )}

      {/* Активные задачи */}
      {activeJobs.length > 0 && (
        <div className="mb-6 flex flex-col gap-3">
          {activeJobs.map(job => <JobCard key={job.job_id} job={job} />)}
        </div>
      )}

      {/* История */}
      {historyJobs.length > 0 && (
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
                {historyJobs.map(job => (
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
