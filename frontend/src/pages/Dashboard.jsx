// Tổng quan cho chủ cửa hàng (FR-RPT-01, SRS 8.2 hình 8.1)
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { money, num } from '../format.js'
import Chart, { seriesChart } from '../ui/Chart.jsx'
import Icon from '../ui/Icon.jsx'
import { Empty, ErrorBox, Loading, useLoad } from '../ui/kit.jsx'
import ProductCell from '../ui/ProductCell.jsx'
import { t } from '../i18n.js'

export function Kpi({ icon, label, value, sub, color = '', featured }) {
  return (
    <div className={`card kpi-card ${featured ? 'featured' : ''}`}>
      <div className={`kpi-icon ${color}`}><Icon name={icon} /></div>
      <div className="min-w-0"><div className="label">{label}</div><div className="value">{value}</div>{sub && <div className="sub">{sub}</div>}</div>
    </div>
  )
}

const dm = (s) => `${s.slice(8)}/${s.slice(5, 7)}`

export default function Dashboard() {
  const { data: d, error, reload } = useLoad(() => api.get('/reports/dashboard'), [])
  const build = useMemo(() => d && seriesChart('line', d.daily_30.map((x) => dm(x.date)), d.daily_30.map((x) => x.revenue)), [d])
  if (error) return <ErrorBox error={error} />
  if (!d) return <Loading />
  const margin = d.month.revenue_net ? ((d.month.gross_profit / d.month.revenue_net) * 100).toFixed(1) : null
  return (
    <div className="stack">
      <div className="grid kpi">
        <Kpi featured icon="wallet" label={t('Doanh thu hôm nay')} value={money(d.today.revenue)} sub={t('{0} hóa đơn', [d.today.invoice_count])} />
        <Kpi icon="calendar" label={t('Doanh thu tháng này')} value={money(d.month.revenue)} sub={t('{0} hóa đơn · VAT {1}', [d.month.invoice_count, money(d.month.vat)])} />
        <Kpi icon="up" label={t('Lãi gộp tháng này')} value={money(d.month.gross_profit)} sub={margin ? t('Biên lãi {0}% trên doanh thu chưa VAT', [margin]) : t('Giá vốn {0}', [money(d.month.cost)])} />
        <Kpi icon="package" label={t('Sản phẩm đang bán')} value={num(d.product_count)} sub={t('{0} khách hàng', [num(d.customer_count)])} />
        <Kpi icon="alert" color={d.low_stock.length ? 'yellow' : ''} label={t('Cần nhập hàng')} value={num(d.low_stock.length)} sub={t('sản phẩm dưới mức tối thiểu')} />
      </div>

      {(d.pending_payment > 0 || d.cancel_requests > 0) && (
        <div className="card">
          <div className="card-head"><h2><Icon name="clock" />{t('Việc cần xử lý')}</h2>
            <button className="btn sm ghost" onClick={reload}><Icon name="refresh" />{t('Làm mới')}</button></div>
          <div className="row" style={{ flexWrap: 'wrap', gap: 'var(--space-3)' }}>
            {d.pending_payment > 0 && <Link className="btn" to="/invoices?status=pending_payment"><Icon name="bank" />{d.pending_payment} {t('hóa đơn chờ chuyển khoản')}</Link>}
            {d.cancel_requests > 0 && <Link className="btn" to="/invoices?cancel=requested"><Icon name="x" />{d.cancel_requests} {t('yêu cầu hủy hóa đơn chờ duyệt')}</Link>}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-head"><h2><Icon name="chart" />{t('Doanh thu 30 ngày gần nhất')}</h2><Link className="btn sm" to="/reports">{t('Xem báo cáo')}</Link></div>
        <Chart build={build} label={t('Biểu đồ doanh thu 30 ngày gần nhất')} />
      </div>

      <div className="grid two">
        <div className="card">
          <div className="card-head"><h2><Icon name="up" />{t('Top 5 bán chạy (30 ngày)')}</h2></div>
          {!d.top_products_30.length ? <Empty title={t('Chưa có sản phẩm bán ra')} /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t('Sản phẩm')}</th><th className="right">{t('SL bán')}</th><th className="right">{t('Doanh thu')}</th></tr></thead>
              <tbody>{d.top_products_30.map((p) => (
                <tr key={p.code}><td><ProductCell p={p} /></td><td className="right">{num(p.quantity)}</td><td className="right num">{money(p.revenue)}</td></tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
        <div className="card">
          <div className="card-head"><h2><Icon name="alert" />{t('Sản phẩm sắp hết hàng')}</h2>
            <Link className="btn sm" to="/purchase-orders" state={{ quickRestock: true }}><Icon name="truck" />{t('Nhập hàng nhanh')}</Link></div>
          {!d.low_stock.length ? <Empty icon="check" title={t('Tồn kho đang ổn')} /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t('Sản phẩm')}</th><th className="right">{t('Tồn / tối thiểu')}</th></tr></thead>
              <tbody>{d.low_stock.map((p) => (
                <tr key={p.code}><td><ProductCell p={p} /></td>
                  <td className="right">{p.stock <= 0 ? <span className="badge red">{t('Hết hàng')}</span> : <span className="badge yellow">{t('Còn {0}', [p.stock])}</span>} <span className="muted">/ {p.min_stock}</span></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      </div>
    </div>
  )
}
