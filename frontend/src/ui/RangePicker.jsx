// Chọn kỳ báo cáo: hai ô ngày và các nút nhanh (7 ngày, 30 ngày, tháng này, tháng trước)
import { useState } from 'react'
import { daysAgo, isoDate, today } from '../format.js'
import Icon from './Icon.jsx'
import { t } from '../i18n.js'

export function quickRanges() {
  const d = new Date()
  return [
    [t('7 ngày'), daysAgo(6), today()],
    [t('30 ngày'), daysAgo(29), today()],
    [t('Tháng này'), isoDate(new Date(d.getFullYear(), d.getMonth(), 1)), today()],
    [t('Tháng trước'), isoDate(new Date(d.getFullYear(), d.getMonth() - 1, 1)), isoDate(new Date(d.getFullYear(), d.getMonth(), 0))],
  ]
}

export default function RangePicker({ value, onChange, submitLabel = t('Xem'), busy, children }) {
  const [f, setF] = useState(value)
  const submit = (e) => {
    e.preventDefault()
    if (f.date_from && f.date_to && f.date_from > f.date_to) return
    onChange({ ...f })
  }
  const invalid = f.date_from && f.date_to && f.date_from > f.date_to
  return (
    <form className="toolbar mb-0" onSubmit={submit}>
      <label>{t('Từ ngày')}<input type="date" value={f.date_from} max={f.date_to || undefined} onChange={(e) => setF({ ...f, date_from: e.target.value })} /></label>
      <label>{t('Đến ngày')}<input type="date" value={f.date_to} min={f.date_from || undefined} onChange={(e) => setF({ ...f, date_to: e.target.value })} /></label>
      <div className="btn-group">
        {quickRanges().map(([label, from, to]) => (
          <button key={label} type="button" className={`btn ${f.date_from === from && f.date_to === to ? 'active' : ''}`}
            onClick={() => { const r = { date_from: from, date_to: to }; setF(r); onChange(r) }}>{label}</button>
        ))}
      </div>
      <button className="btn primary" type="submit" disabled={busy || invalid}><Icon name="search" />{submitLabel}</button>
      {invalid && <span className="error small">{t('Ngày bắt đầu phải trước ngày kết thúc')}</span>}
      {children && <div className="actions">{children}</div>}
    </form>
  )
}
