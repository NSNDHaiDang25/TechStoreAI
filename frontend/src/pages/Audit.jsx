// Nhật ký thao tác (UC-06, bảng audit_logs) và nhật ký gửi email
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, openFile } from '../api.js'
import { useAuth } from '../auth.jsx'
import { daysAgo, fmtDateTime, today } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Empty, ErrorBox, Loading, Pager, useLoad, useToast } from '../ui/kit.jsx'
import { numLocale, t } from '../i18n.js'

// Màu nhãn theo loại đối tượng bị tác động
const ENTITY_TONE = {
  users: 'red', branches: 'red', settings: 'red', database: 'red',
  products: 'blue', product_serials: 'blue', import_receipts: 'cyan',
  invoices: 'yellow', returns: 'yellow', promotions: 'yellow',
  customers: 'green', customer_tiers: 'green',
}

const fmtValue = (v) => {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'number') return v.toLocaleString(numLocale)
  if (typeof v === 'boolean') return v ? t('Có') : t('Không')
  return t(String(v))
}

// Trước → Sau: giá trị cũ gạch ngang màu đỏ, giá trị mới màu xanh; chỉ các trường thay đổi
function Changes({ list }) {
  const [open, setOpen] = useState(false)
  if (!list?.length) return <span className="muted">-</span>
  const shown = open ? list : list.slice(0, 3)
  return (
    <div className="audit-changes">
      {shown.map((c, i) => (
        <div key={`${c.field}-${i}`} className="audit-change">
          {c.label && <span className="muted">{t(c.label)}: </span>}
          {c.old !== null && c.old !== undefined && <><s className="audit-old">{fmtValue(c.old)}</s><span className="audit-arrow" aria-label={t('thành')}>→</span></>}
          <span className="audit-new">{fmtValue(c.new)}</span>
        </div>
      ))}
      {list.length > 3 && <button type="button" className="link-btn small" onClick={() => setOpen(!open)}>
        {open ? t('Thu gọn') : t('+{0} thay đổi khác', [list.length - 3])}</button>}
    </div>
  )
}

function AuditLogs() {
  const { user } = useAuth()
  const toast = useToast()
  const [query] = useSearchParams()
  const [f, setF] = useState({ user_id: '', entity: '', action: '', date_from: daysAgo(29), date_to: today(), branch_id: query.get('branch') || '' })
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  useEffect(() => { const tt = setTimeout(() => { setPage(1); setQ(search.trim()) }, 300); return () => clearTimeout(tt) }, [search])
  const params = { ...f, q }
  const { data, error } = useLoad(() => api.get('/audit-logs', { ...params, page, size: 50 }), [JSON.stringify(params), page])
  const set = (k) => (e) => { setPage(1); setF({ ...f, [k]: e.target.value }) }
  const pick = (id) => { setPage(1); setF({ ...f, branch_id: id }) }
  const branches = data?.branches || []
  const counts = data?.branch_counts || {}
  const all = Object.values(counts).reduce((a, b) => a + b, 0)
  const showBranch = user.role === 'admin' && f.branch_id === '' && branches.length > 0  // cột chi nhánh khi xem tất cả
  const exportXlsx = () => openFile('/audit-logs/export', params, `nhat-ky-thao-tac-${today()}.xlsx`).catch((e) => toast(e.message, 'error'))

  return <>
    <div className="audit-head">
      <p className="muted m-0">{data?.branch_name
        ? <>{t('Thao tác nghiệp vụ tại chi nhánh')} <span className="strong">{data.branch_name}</span></>
        : t('Mọi thao tác trên tài khoản, giá, kho, hóa đơn, khách hàng và cấu hình, chia theo chi nhánh nơi thực hiện')}</p>
      <button className="btn" onClick={exportXlsx}><Icon name="download" />{t('Xuất Excel')}</button>
    </div>

    {/* Quản trị viên: tab từng chi nhánh kèm số thao tác; "Hệ thống" = không thuộc chi nhánh nào */}
    {branches.length > 0 && (
      <div className="tabs-line" role="tablist" aria-label={t('Chi nhánh')}>
        {[['', t('Tất cả'), all], ...branches.map((b) => [String(b.id), b.name, counts[b.id] || 0]), ['0', t('Hệ thống'), counts[0] || 0]].map(([id, name, n]) => (
          <button key={id} type="button" role="tab" aria-selected={f.branch_id === id} className={f.branch_id === id ? 'active' : ''} onClick={() => pick(id)}>
            {name} <span className="tab-count">({n})</span></button>
        ))}
      </div>
    )}

    <div className="audit-filters">
      <select value={f.user_id} onChange={set('user_id')} aria-label={t('Người thực hiện')}>
        <option value="">{t('Người thực hiện: Tất cả')}</option>
        {(data?.users || []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        {user.role === 'admin' && <option value="0">{t('Hệ thống')}</option>}
      </select>
      <select value={f.entity} onChange={set('entity')} aria-label={t('Đối tượng')}>
        <option value="">{t('Đối tượng: Tất cả')}</option>
        {(data?.entities || []).map((e) => <option key={e.value} value={e.value}>{t(e.label)}</option>)}
      </select>
      <select value={f.action} onChange={set('action')} aria-label={t('Thao tác')}>
        <option value="">{t('Thao tác: Tất cả')}</option>
        {(data?.actions || []).map((a) => <option key={a.value} value={a.value}>{t(a.label)}</option>)}
      </select>
      <div className="date-range">
        <input type="date" value={f.date_from} onChange={set('date_from')} aria-label={t('Từ ngày')} />
        <span className="muted">–</span>
        <input type="date" value={f.date_to} onChange={set('date_to')} aria-label={t('Đến ngày')} />
      </div>
      <div className="input-icon audit-search"><Icon name="search" />
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('Tìm theo tên, mã sản phẩm, hóa đơn, khách hàng')} aria-label={t('Tìm trong nhật ký')} /></div>
    </div>

    <ErrorBox error={error} />
    {!data ? <Loading /> : !data.items.length ? <Empty icon="clipboard" title={t('Không có thao tác nào phù hợp')} /> : <>
      <div className="table-wrap"><table className="audit-table">
        <thead><tr><th>{t('Thời điểm')}</th>{showBranch && <th>{t('Chi nhánh')}</th>}<th>{t('Người thực hiện')}</th><th>{t('Đối tượng')}</th>
          <th>{t('Thao tác')}</th><th>{t('Trên')}</th><th>{t('Trước → Sau')}</th></tr></thead>
        <tbody>{data.items.map((r) => (
          <tr key={r.id}>
            <td className="small nowrap" title={r.ip_address ? `IP ${r.ip_address}` : undefined}>{fmtDateTime(r.created_at)}</td>
            {showBranch && <td className="small">{r.branch_name || <span className="muted">{t('Hệ thống')}</span>}</td>}
            <td className="strong">{r.user_name || <span className="muted">{t('Hệ thống')}</span>}</td>
            <td><span className={`badge ${ENTITY_TONE[r.entity] || ''}`}>{t(r.entity_label)}</span></td>
            <td className="strong">{t(r.action_label)}</td>
            <td className="small audit-target">{r.target || <span className="muted">-</span>}</td>
            <td className="small"><Changes list={r.changes} /></td>
          </tr>
        ))}</tbody>
      </table></div>
      <Pager page={page} size={50} total={data.total} onPage={setPage} />
    </>}
  </>
}

const MAIL_STATUS = { sent: [t('Đã gửi'), 'green'], failed: [t('Lỗi'), 'red'] }

function EmailLogs() {
  const [page, setPage] = useState(1)
  const { data, error } = useLoad(() => api.get('/email-logs', { page, size: 50 }), [page])
  return <>
    <ErrorBox error={error} />
    {!data ? <Loading /> : !data.items.length ? <Empty icon="mail" title={t('Chưa gửi email nào')} /> : <>
      <div className="table-wrap"><table>
        <thead><tr><th>{t('Thời gian')}</th><th>{t('Người nhận')}</th><th>{t('Tiêu đề')}</th><th>{t('Loại')}</th><th>{t('Trạng thái')}</th></tr></thead>
        <tbody>{data.items.map((r) => (
          <tr key={r.id}><td className="small nowrap">{fmtDateTime(r.created_at)}</td><td>{r.to_email}</td><td>{r.subject}</td><td className="small">{r.mail_type}</td>
            <td><span className={`badge ${(MAIL_STATUS[r.status] || [])[1] || ''}`}>{(MAIL_STATUS[r.status] || [r.status])[0]}</span>
              {r.error_message && <div className="muted small">{r.error_message}</div>}</td></tr>
        ))}</tbody>
      </table></div>
      <Pager page={page} size={50} total={data.total} onPage={setPage} />
    </>}
  </>
}

export default function Audit() {
  const [tab, setTab] = useState('audit')
  return (
    <div className="card">
      <div className="chips mb-4">
        <button className={`chip ${tab === 'audit' ? 'active' : ''}`} onClick={() => setTab('audit')}><Icon name="clipboard" />{t('Thao tác')}</button>
        <button className={`chip ${tab === 'email' ? 'active' : ''}`} onClick={() => setTab('email')}><Icon name="mail" />{t('Email đã gửi')}</button>
      </div>
      {tab === 'audit' ? <AuditLogs /> : <EmailLogs />}
    </div>
  )
}
