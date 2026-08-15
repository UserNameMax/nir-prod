import { useEffect, useState } from 'react'
import { mlService } from '../api/mlService'
import type { Kpi, MlHealth } from '../types/ml'

/**
 * Честная отчётность системы.
 *
 * Главное правило экрана: детекция НИКОГДА не показывается в одиночку. Метрика
 * «сработал ли алерт хоть раз за десятки предаварийных дней» насыщается
 * геометрией окна — случайное алертирование при том же бюджете даёт высокий
 * «нулевой пол». Осмысленная величина — превышение над этим полом (lift), и
 * рядом с ней всегда стоит p-value.
 *
 * Приводятся только числа временного форкаста (обучение на прошлом, проверка на
 * будущем) — object-split завышает оценку и в интерфейс не выносится.
 */
export function KpiPanel() {
  const [kpi, setKpi] = useState<Kpi | null>(null)
  const [health, setHealth] = useState<MlHealth | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([mlService.getKpi(), mlService.health()])
      .then(([k, h]) => { setKpi(k); setHealth(h) })
      .catch(e => setError(String(e)))
  }, [])

  if (error) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">{error}</div>
      </div>
    )
  }
  if (!kpi) return <div className="max-w-4xl mx-auto p-6 text-sm text-slate-400">Загрузка…</div>

  const significant = kpi.lift_p_value != null && kpi.lift_p_value < 0.05

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-semibold text-slate-800 mb-1">Качество системы</h1>
      <p className="text-sm text-slate-500 mb-5">
        Проверка на будущем: модель обучена на прошлых месяцах и оценена на следующих,
        которых не видела.
      </p>

      <div className={`rounded-xl border p-5 mb-5 ${significant
        ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'}`}>
        <div className="text-sm text-slate-600 mb-1">Превышение над случайным алертированием</div>
        <div className={`text-3xl font-semibold ${significant ? 'text-emerald-700' : 'text-amber-700'}`}>
          {kpi.detection_lift >= 0 ? '+' : ''}{(kpi.detection_lift * 100).toFixed(1)} п.п.
        </div>
        <div className="text-sm mt-2 text-slate-600">
          {significant
            ? 'Преимущество над случайным выбором статистически значимо.'
            : 'Преимущество над случайным выбором статистически НЕ значимо — на этих данных система не отличается от случайного отбора объектов.'}
          {kpi.lift_p_value != null && <> (p = {kpi.lift_p_value.toFixed(3)})</>}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
        <Metric
          label="Найдено аварий"
          value={`${(kpi.detection * 100).toFixed(0)}%`}
          hint={kpi.detection_lo != null
            ? `доверительный интервал ${(kpi.detection_lo * 100).toFixed(0)}–${(kpi.detection_hi! * 100).toFixed(0)}%`
            : undefined}
        />
        <Metric
          label="Нашёл бы случайный отбор"
          value={`${(kpi.detection_null * 100).toFixed(0)}%`}
          hint="нулевой пол при том же бюджете"
          muted
        />
        <Metric
          label="Аварий в проверке"
          value={String(kpi.n_events)}
          hint="объектов с подтверждённой аварией"
          muted
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
        <Metric
          label="ROC-AUC"
          value={kpi.roc_auc.toFixed(3)}
          hint={kpi.roc_lo != null ? `${kpi.roc_lo.toFixed(3)}–${kpi.roc_hi!.toFixed(3)}` : undefined}
          muted
        />
        <Metric
          label="Раннесть"
          value={kpi.lead_within_H != null ? `${(kpi.lead_within_H * 100).toFixed(0)}%` : '—'}
          hint="алертов привязано к началу аварии"
          muted
        />
        <Metric
          label="Алертов в день"
          value={kpi.alerts_per_day != null ? kpi.alerts_per_day.toFixed(0) : '—'}
          hint="ставка 2% объект-дней"
          muted
        />
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-4 text-sm text-slate-600 mb-4">
        <div className="font-medium text-slate-700 mb-2">Как читать эти числа</div>
        <p className="mb-2">
          Долю найденных аварий нельзя оценивать саму по себе: алерт засчитывается,
          если сработал хотя бы раз за десятки предаварийных дней, а такое случается
          и при случайном отборе. Поэтому рядом всегда стоит «нулевой пол», а выводы
          делаются по превышению над ним.
        </p>
        <p>
          Система — очередь на разбор, а не оракул: она сокращает объём внимания
          диспетчера, но не заменяет решение человека.
        </p>
      </div>

      {health && (
        <div className="text-xs text-slate-400">
          Бандл {health.bundle_version} · горизонт {health.horizon_days} дн ·
          объектов {health.cached_objects} · правило по умолчанию {health.trigger_default}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value, hint, muted }: {
  label: string; value: string; hint?: string; muted?: boolean
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-2xl font-semibold mt-1 ${muted ? 'text-slate-600' : 'text-slate-800'}`}>
        {value}
      </div>
      {hint && <div className="text-xs text-slate-400 mt-1">{hint}</div>}
    </div>
  )
}
