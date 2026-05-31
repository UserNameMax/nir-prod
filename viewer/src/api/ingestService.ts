import type { IngestJob } from '../types/api'

const BASE = import.meta.env.VITE_INGEST_API_URL ?? 'http://localhost:8001'

export const ingestService = {
  async upload(file: File): Promise<{ job_id: string; status: string }> {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/ingest/upload`, { method: 'POST', body: form })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail ?? `${res.status}`)
    }
    return res.json()
  },

  async getJob(job_id: string): Promise<IngestJob> {
    const res = await fetch(`${BASE}/ingest/jobs/${job_id}`)
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },

  async listJobs(): Promise<IngestJob[]> {
    const res = await fetch(`${BASE}/ingest/jobs`)
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
}
