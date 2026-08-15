export interface WatchlistItem {
  rank: number
  object_id: string
  chronic_score: number
}

export interface Watchlist {
  total_objects: number
  model_note: string
  items: WatchlistItem[]
}

export interface RankingItem {
  rank: number
  object_id: string
  risk_score: number
  calibrated: number
}

export interface Ranking {
  date: string
  total_objects: number
  items: RankingItem[]
}

export interface TimelinePoint {
  date: string
  risk_score: number
  calibrated: number
  rank: number
}

export interface ObjectTimeline {
  object_id: string
  timeline: TimelinePoint[]
}

export interface ObjectThresholds {
  p75: number
  p90: number
}

export interface Order {
  object_id: string
  opened_at: string
  last_alert_at: string
  alert_days: number
  peak_score: number
  chronic_rank: number | null
}

export interface AlertQueue {
  date: string | null
  profile: string
  cooldown_days: number
  kappa_star: number | null
  total_orders: number
  orders: Order[]
}

export interface TriggerProfile {
  type: string
  kappa_star?: number | null
  threshold?: number
  detection?: number
  inspections?: number
  lead_within_H?: number | null
  n?: number
  span?: number
  chronic_top?: string
}

export interface TriggerConfig {
  default: string
  cooldown_days: number
  target_detection: number
  profiles: Record<string, TriggerProfile>
}

export interface ProfilePoint {
  ts: string
  t_supply: number | null
  t_return: number | null
  p_supply: number | null
  p_return: number | null
}

export interface ObjectCard {
  object_id: string
  date: string
  raw_score: number
  calibrated_prob: number
  calibration_note: string
  alert_threshold: number
  rank: number
  p75: number | null
  p90: number | null
  chronic_rank: number | null
  aft_median_days: number | null
  meta: Record<string, string | null>
  daily_profile: ProfilePoint[]
}

/** Отчётность бандла — только temporal-форкаст. */
export interface Kpi {
  split: string
  detection: number
  detection_null: number
  detection_lift: number
  lift_p_value: number | null
  roc_auc: number
  pr_auc?: number
  n_events: number
  lead_within_H: number | null
  alerts_per_day?: number
  detection_lo?: number
  detection_hi?: number
  roc_lo?: number
  roc_hi?: number
  note: string
}

export interface MlHealth {
  status: string
  bundle_version?: string
  feature_schema_version?: string
  horizon_days?: number
  trigger_default?: string
  cached_objects?: number
  cached_dates?: number
}
