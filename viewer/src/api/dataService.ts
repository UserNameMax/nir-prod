import type { ObjectMeta, Page, SensorRecord } from '../types/api'

const BASE = import.meta.env.VITE_DATA_API_URL ?? 'http://localhost:8000'

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(`${BASE}${path}`)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v))
    })
  }
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const dataService = {
  getObjects(params: {
    municipality?: string
    facility_type?: string
    q?: string
    offset?: number
    limit?: number
  }): Promise<Page<ObjectMeta>> {
    return get('/objects', params as Record<string, string | number>)
  },

  getObject(object_id: string): Promise<ObjectMeta> {
    return get(`/objects/${object_id}`)
  },

  getSensors(params: {
    object_id: string
    from_ts?: number
    to_ts?: number
    offset?: number
    limit?: number
  }): Promise<Page<SensorRecord>> {
    return get('/sensors', params as Record<string, string | number>)
  },

  getCalendar(object_id: string): Promise<{ dates: string[] }> {
    return get('/sensors/calendar', { object_id })
  },

  getCalendarSummary(params: {
    from_date?: string
    to_date?: string
  }): Promise<Array<{ day: string; objects_count: number }>> {
    return get('/sensors/calendar/summary', params as Record<string, string>)
  },
}
