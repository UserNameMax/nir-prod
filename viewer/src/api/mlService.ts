import type {
  AlertQueue, Kpi, MlHealth, ObjectCard, ObjectThresholds, ObjectTimeline,
  Ranking, TriggerConfig, Watchlist,
} from '../types/ml'

const BASE = import.meta.env.VITE_ML_API_URL ?? 'http://localhost:8005'

async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
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

export const mlService = {
  health(): Promise<MlHealth> {
    return get('/health')
  },

  /** Слой 1 — хронический watch-list для планового ТО. */
  getWatchlist(top_n = 50): Promise<Watchlist> {
    return get('/risk/watchlist', { top_n })
  },

  getDates(): Promise<string[]> {
    return get('/risk/dates')
  },

  getRanking(params: { date?: string; top_n?: number }): Promise<Ranking> {
    return get('/risk/ranking', params)
  },

  getObjectTimeline(object_id: string, params?: { date_from?: string; date_to?: string }): Promise<ObjectTimeline> {
    return get(`/risk/object/${object_id}`, params)
  },

  getObjectThresholds(object_id: string): Promise<ObjectThresholds> {
    return get(`/risk/object/${object_id}/thresholds`)
  },

  /** Слои 2+3 — наряды после триггера устойчивости, cooldown и гейтинга. */
  getQueue(params: { date?: string; profile?: string; gate?: boolean; top_n?: number }): Promise<AlertQueue> {
    return get('/alerts/queue', params)
  },

  getTriggerConfig(): Promise<TriggerConfig> {
    return get('/alerts/config')
  },

  /** Слой 4 — срок AFT, вероятность для показа, суточный профиль. */
  getObjectCard(object_id: string, params?: { date?: string; with_profile?: boolean }): Promise<ObjectCard> {
    return get(`/explain/${object_id}`, params)
  },

  getKpi(): Promise<Kpi> {
    return get('/kpi')
  },
}
