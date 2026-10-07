// Báo cáo doanh thu (UC-41, UC-42, FR-RPT-02..05, FR-EXP-01..04)
import { useMemo, useState } from 'react'
import { api, openFile } from '../api.js'
import { daysAgo, money, num, today } from '../format.js'
import Chart, { seriesChart, shareChart } from '../ui/Chart.jsx'
import Icon from '../ui/Icon.jsx'
import { Empty, ErrorBox, Loading, useLoad } from '../ui/kit.jsx'
import ProductCell from '../ui/ProductCell.jsx'
import RangePicker from '../ui/RangePicker.jsx'
import { Kpi } from './Dashboard.jsx'
import { t } from '../i18n.js'

const dm = (s) => `${s.slice(8)}/${s.slice(5, 7)}`

function MonthlyCard() {
  const year = new Date().getFullYear()
  const [y, setY] = useState(year)
  const { data, error } = useLoad(() => api.get('/reports/monthly', { year: y }), [y])
  const build = useMemo(() => data && seriesChart('bar', data.map((m) => `Th ${Number(m.month.slice(5))}`), data.map((m) => m.revenue)), [data])
  const total = (data || []).reduce((s, m) => s + m.revenue, 0)
  return (
    <div className="card">
      <div className="card-head"><h2><Icon name="calendar" />{t('Doanh thu theo tháng')}</h2>
        {data && <span className="muted small">{t('Cả năm:')} <span className="strong">{money(total)}</span></span>}
        <select value={y} onChange={(e) => setY(Number(e.target.value))} aria-label={t('Năm')}>
          {[year, year - 1, year - 2].map((v) => <option key={v} value={v}>{v}</option>)}</select></div>
      <ErrorBox error={error} />
      {!data ? <Loading /> : <Chart build={build} label={t('Doanh thu theo tháng năm {0}', [y])} />}
    </div>
  )
}

function ProductTable({ rows, cols }) {
  if (!rows.length) return <Empty title={t('Không có dữ liệu trong kỳ')} />
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>{t('Sản phẩm')}</th>{cols.map(([label]) => <th key={label} className="right">{label}</th>)}</tr></thead>
      <tbody>{rows.map((p) => (
        <tr key={p.code}><td><ProductCell p={p} /></td>{cols.map(([label, fn]) => <td key={label} className="right num">{fn(p)}</td>)}</tr>
      ))}</tbody>
    </table></div>
  )
}

export default function Reports() {
  const [range, setRange] = useState({ date_from: daysAgo(29), date_to: today() })
  const { data: d, loading, error } = useLoad(() => api.get('/reports/revenue', range), [range.date_from, range.date_to])
  const dayChart = useMemo(() => d && seriesChart('bar', d.by_day.map((x) => dm(x.date)), d.by_day.map((x) => x.revenue)), [d])
  const catChart = useMemo(() => d && shareChart(d.by_category), [d])
  const exportFile = (format) => openFile('/reports/export/revenue', { ...range, format }, `bao-cao-doanh-thu-${range.date_from}-${range.date_to}.${format}`)
  const s = d?.summary
  return (
    <div className="stack">
      <div className="card">
        <RangePicker value={range} onChange={setRange} busy={loading}>
          <div className="btn-group">
            <button type="button" className="btn" onClick={() => exportFile('xlsx')}><Icon name="download" />Excel</button>
            <button type="button" className="btn" onClick={() => exportFile('pdf')}>PDF</button>
            <button type="button" className="btn" onClick={() => exportFile('csv')}>CSV</button>
          </div>
        </RangePicker>
      </div>
      <ErrorBox error={error} />
      {!d ? <Loading /> : <>
        <div className="grid kpi">
          <Kpi featured icon="wallet" label={t('Doanh thu (gồm VAT)')} value={money(s.revenue)} sub={t('{0} hóa đơn', [num(s.invoice_count)])} />
          <Kpi icon="undo" label={t('Hoàn tiền đổi trả')} value={money(s.refunds)} sub={t('Doanh số {0}', [money(s.gross_sales)])} />
          <Kpi icon="percent" label={t('Giảm giá')} value={money(s.discount)} sub={`VAT ${money(s.vat)}`} />
          <Kpi icon="package" label={t('Giá vốn')} value={money(s.cost)} sub={t('Chưa VAT {0}', [money(s.revenue_net)])} />
          <Kpi icon="up" label={t('Lãi gộp')} value={money(s.gross_profit)}
            sub={s.revenue_net ? t('Biên lãi {0}%', [((s.gross_profit / s.revenue_net) * 100).toFixed(1)]) : ''} />
        </div>
        <div className="grid two">
          <div className="card"><div className="card-head"><h2><Icon name="chart" />{t('Doanh thu theo ngày')}</h2></div>
            <Chart build={dayChart} label={t('Doanh thu theo ngày trong kỳ')} /></div>
          <div className="card"><div className="card-head"><h2><Icon name="tag" />{t('Tỉ trọng theo nhóm hàng')}</h2></div>
            {d.by_category.length ? <Chart build={catChart} label={t('Tỉ trọng doanh thu theo nhóm hàng')} /> : <Empty title={t('Chưa có doanh thu')} />}</div>
        </div>
        <div className="grid two">
          <div className="card"><div className="card-head"><h2><Icon name="up" />{t('Sản phẩm bán chạy')}</h2></div>
            <ProductTable rows={d.top_products} cols={[[t('SL'), (p) => num(p.quantity)], [t('Doanh thu'), (p) => money(p.revenue)]]} /></div>
          <div className="card"><div className="card-head"><h2><Icon name="down" />{t('Bán chậm (còn tồn)')}</h2></div>
            <ProductTable rows={d.slow_products} cols={[[t('SL bán'), (p) => num(p.quantity)], [t('Tồn'), (p) => num(p.stock)]]} /></div>
        </div>
      </>}
      <MonthlyCard />
    </div>
  )
}
