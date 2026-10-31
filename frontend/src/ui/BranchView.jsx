// Chi nhánh chính tổng hợp số liệu: chủ cửa hàng ở chi nhánh chính chọn xem tất cả chi nhánh, chi nhánh mình
// hoặc một chi nhánh khác ở Tổng quan, Báo cáo, Hóa đơn (chỉ xem). Lựa chọn giữ nguyên khi chuyển trang.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { money, num } from '../format.js'
import Icon from './Icon.jsx'
import { useLoad } from './kit.jsx'
import { t } from '../i18n.js'

const KEY = 'branch-view'
const read = () => { try { return sessionStorage.getItem(KEY) } catch { return null } }

// Trả về [giá trị, đổi giá trị, được phép]. Giá trị: 'all' | id chi nhánh | '' (chi nhánh của mình).
// Chủ cửa hàng chi nhánh chính mặc định xem tất cả chi nhánh; người khác luôn là ''.
export function useBranchView() {
  const { user } = useAuth()
  const enabled = user?.role === 'owner' && !!user.branch_is_main
  const [value, setValue] = useState(() => read() ?? 'all')
  const set = (v) => {
    setValue(v)
    try { sessionStorage.setItem(KEY, v) } catch { /* trình duyệt chặn lưu trữ */ }
  }
  return [enabled ? value : '', set, enabled]
}

export function BranchPicker({ value, onChange }) {
  const { user } = useAuth()
  const { data } = useLoad(() => api.get('/branches/options'), [])
  return (
    <label>{t('Xem số liệu')}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="all">{t('Tất cả chi nhánh')}</option>
        <option value="">{t('Chi nhánh của tôi')}{user.branch_name ? ` (${user.branch_name})` : ''}</option>
        {(data || []).filter((b) => b.id !== user.branch_id).map((b) => (
          <option key={b.id} value={String(b.id)}>{b.name}{b.is_active ? '' : ` · ${t('Ngừng hoạt động')}`}</option>
        ))}
      </select>
    </label>
  )
}

// Bảng doanh thu từng chi nhánh (khi xem tất cả chi nhánh)
// Liên kết sang trang Hóa đơn: hóa đơn tính doanh thu (lọc theo ngày thanh toán) trong kỳ, đúng chi nhánh.
// branch: 'all' | '' (chi nhánh của mình) | id chi nhánh | null (không chọn chi nhánh).
export function invoicesLink(from, to, branch) {
  const p = new URLSearchParams({ status: 'revenue', date_from: from, date_to: to })
  if (branch != null) p.set('branch', String(branch))
  return `/invoices?${p}`
}

export function BranchRevenue({ rows, title = t('Doanh thu theo chi nhánh'), from, to }) {
  const { user } = useAuth()
  if (!rows?.length) return null
  const total = rows.reduce((s, r) => s + r.revenue, 0)
  return (
    <div className="card">
      <div className="card-head"><h2><Icon name="store" />{title}</h2></div>
      <div className="table-wrap"><table>
        <thead><tr><th>{t('Chi nhánh')}</th><th className="right">{t('Số hóa đơn')}</th><th className="right">{t('Doanh thu')}</th>
          <th className="right">{t('Tỉ trọng')}</th><th className="right">{t('Lãi gộp')}</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.branch_id ?? 'none'}><td className="strong">{r.branch_name}</td><td className="right">{from && r.branch_id != null
            ? <Link to={invoicesLink(from, to, r.branch_id === user.branch_id ? '' : r.branch_id)} title={t('Xem các hóa đơn này')}>{num(r.invoice_count)}</Link>
            : num(r.invoice_count)}</td>
            <td className="right num">{money(r.revenue)}</td>
            <td className="right muted">{total ? `${((r.revenue / total) * 100).toFixed(1)}%` : '-'}</td>
            <td className="right num">{money(r.gross_profit)}</td></tr>
        ))}</tbody>
      </table></div>
    </div>
  )
}
