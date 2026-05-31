export interface SensorRecord {
  record_id: string
  object_id: string
  ts_measurement: number
  t_supply: number | null
  t_return: number | null
  p_supply: number | null
  p_return: number | null
  ts_recorded: number
}

export interface ObjectMeta {
  object_id: string
  object_type: string | null
  facility_type: string | null
  facility_name: string | null
  municipality: string | null
  rso: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}

export interface IngestStats {
  xlsx_files_found: number
  sensors_inserted: number
  sensors_duplicates: number
  objects_upserted: number
  period_from: string | null
  period_to: string | null
  objects_count: number
}

export interface IngestJob {
  job_id: string
  filename: string
  status: 'queued' | 'processing' | 'done' | 'error'
  created_at: string
  finished_at: string | null
  stats: IngestStats | null
  error: string | null
  files_total: number | null
  files_processed: number | null
  current_file: string | null
  rows_processed: number | null
  merge_total: number | null
  merge_processed: number | null
}
