// Khách hàng, hạng và điểm (UC-14 đến UC-17)
import { useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { INVOICE_STATUS, fmtDate, fmtDateTime, money, num } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Badge, Empty, ErrorBox, Field, Loading, Modal, Pager, useLoad, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

const TXN_VI = { earn: t('Tích điểm'), redeem: t('Dùng điểm'), reverse_earn: t('Trừ do hủy / trả'), reverse_redeem: t('Hoàn điểm đã dùng'), adjust: t('Điều chỉnh') }

function CustomerForm({ initial, onClose, onSaved }) {
  const { user } = useAuth()
  const toast = useToast()
  const [f, setF] = useState(initial || { name: '', phone: '', email: '', address: '', birthday: '', note: '' })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const save = async () => {
    const body = { ...f, birthday: f.birthday || null, email: f.email || null }
    try {
      const c = initial?.id ? await api.put(`/customers/${initial.id}`, body) : await api.post('/customers', body)
      toast(t('Đã lưu khách hàng'), 'success'); onSaved(c)
    } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={initial?.id ? t('Sửa khách hàng') : t('Thêm khách hàng')} onClose={onClose} footer={<button className="btn primary" onClick={save}>{t('Lưu')}</button>}>
      <div className="form-grid">
        <Field label={t('Họ tên')}><input value={f.name} onChange={set('name')} /></Field>
        <Field label={t('Số điện thoại')}><input value={f.phone} onChange={set('phone')} placeholder={t('10 số, bắt đầu bằng 0')} /></Field>
        <Field label="Email"><input value={f.email || ''} onChange={set('email')} /></Field>
        <Field label={t('Ngày sinh')}><input type="date" value={f.birthday || ''} onChange={set('birthday')} /></Field>
        <Field label={t('Địa chỉ')} full><input value={f.address || ''} onChange={set('address')} /></Field>
        <Field label={t('Ghi chú')} full><input value={f.note || ''} onChange={set('note')} /></Field>
        {initial?.id && user.role === 'owner' && (
          <label className="checkbox full"><input type="checkbox" checked={f.is_active ?? true} onChange={set('is_active')} />{t('Đang hoạt động (bỏ chọn để vô hiệu hóa thay cho xóa)')}</label>
        )}
      </div>
    </Modal>
  )
}

function PointsDialog({ customer, onClose, onDone }) {
  const toast = useToast()
  const [points, setPoints] = useState('')
  const [reason, setReason] = useState('')
  const save = async () => {
    try { await api.post(`/customers/${customer.id}/points`, { points: Number(points), reason }); toast(t('Đã điều chỉnh điểm'), 'success'); onDone() } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={t('Điều chỉnh điểm: {0}', [customer.name])} onClose={onClose} size="narrow" footer={<button className="btn primary" onClick={save} disabled={!Number(points) || reason.trim().length < 5}>{t('Lưu')}</button>}>
      <div className="stack">
        <p className="muted m-0">{t('Điểm hiện có:')} <span className="strong">{num(customer.loyalty_points)}</span>{t('. Nhập số âm để trừ điểm.')}</p>
        <label>{t('Số điểm')}<input value={points} onChange={(e) => setPoints(e.target.value.replace(/[^\d-]/g, ''))} placeholder={t('VD: 100 hoặc -50')} /></label>
        <label>{t('Lý do (bắt buộc, ghi vào nhật ký)')}<textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      </div>
    </Modal>
  )
}

function CustomerDetail({ id, onClose, onChanged }) {
  const { user } = useAuth()
  const { data: c, reload } = useLoad(() => api.get(`/customers/${id}`), [id])
  const [edit, setEdit] = useState(false)
  const [pts, setPts] = useState(false)
  if (!c) return <Modal title={t('Khách hàng')} onClose={onClose}><Loading /></Modal>
  return (
    <Modal title={c.name} onClose={onClose} size="wide" footer={<>
      {user.role === 'owner' && <button className="btn" onClick={() => setPts(true)}><Icon name="award" />{t('Điều chỉnh điểm')}</button>}
      <button className="btn primary" onClick={() => setEdit(true)}><Icon name="edit" />{t('Sửa')}</button>
    </>}>
      <div className="grid kpi">
        <div className="card kpi-card"><div className="kpi-icon"><Icon name="award" /></div><div><div className="label">{t('Hạng')}</div><div className="value">{t(c.tier_name)}</div><div className="sub">{t('Hệ số điểm x')}{c.points_multiplier}</div></div></div>
        <div className="card kpi-card"><div className="kpi-icon green"><Icon name="sparkles" /></div><div><div className="label">{t('Điểm hiện có')}</div><div className="value">{num(c.loyalty_points)}</div></div></div>
        <div className="card kpi-card"><div className="kpi-icon yellow"><Icon name="wallet" /></div><div><div className="label">{t('Tổng chi tiêu')}</div><div className="value">{money(c.total_spent)}</div><div className="sub">{c.invoice_count} {t('hóa đơn')}</div></div></div>
      </div>
      <div className="info-list mt-3">
        <div><span className="muted">{t('Mã')}</span><span>{c.code}</span></div>
        <div><span className="muted">{t('Điện thoại')}</span><span className="strong">{c.phone}</span></div>
        <div><span className="muted">Email</span><span>{c.email || '-'}</span></div>
        <div><span className="muted">{t('Ngày sinh')}</span><span>{fmtDate(c.birthday) || '-'}</span></div>
        <div><span className="muted">{t('Địa chỉ')}</span><span>{c.address || '-'}</span></div>
        <div><span className="muted">{t('Trạng thái')}</span><span>{c.is_active ? t('Đang hoạt động') : <span className="badge red">{t('Đã vô hiệu')}</span>}</span></div>
      </div>
      <div className="grid two">
        <div>
          <h3>{t('Thiết bị đang bảo hành')}</h3>
          {!c.warranties.length ? <p className="muted">{t('Không có')}</p> : (
            <div className="table-wrap"><table><thead><tr><th>{t('Sản phẩm')}</th><th>Serial</th><th>{t('Hết hạn')}</th></tr></thead>
              <tbody>{c.warranties.map((w) => <tr key={w.id}><td>{t(w.product_name)}</td><td>{w.serial_no || '-'}</td><td>{fmtDate(w.end_date)}</td></tr>)}</tbody></table></div>
          )}
        </div>
        <div>
          <h3>{t('Biến động điểm')}</h3>
          {!c.points_history.length ? <p className="muted">{t('Chưa có')}</p> : (
            <div className="table-wrap"><table><thead><tr><th>{t('Thời gian')}</th><th>{t('Loại')}</th><th className="right">{t('Điểm')}</th><th className="right">{t('Số dư')}</th></tr></thead>
              <tbody>{c.points_history.slice(0, 15).map((tt) => (
                <tr key={tt.id} title={tt.note || ''}><td>{fmtDateTime(tt.created_at)}</td><td>{TXN_VI[tt.txn_type]}</td>
                  <td className={`right num ${tt.points > 0 ? 'text-success' : 'text-danger'}`}>{tt.points > 0 ? '+' : ''}{num(tt.points)}</td><td className="right num">{num(tt.balance_after)}</td></tr>
              ))}</tbody></table></div>
          )}
        </div>
      </div>
      <h3 className="mt-3">{t('Lịch sử mua hàng')}</h3>
      {!c.invoices.length ? <p className="muted">{t('Chưa mua hàng')}</p> : (
        <div className="table-wrap"><table><thead><tr><th>{t('Mã')}</th><th>{t('Thời gian')}</th><th>{t('Sản phẩm')}</th><th className="right">{t('Tổng')}</th><th>{t('Trạng thái')}</th></tr></thead>
          <tbody>{c.invoices.map((i) => <tr key={i.id}><td>{i.code}</td><td>{fmtDateTime(i.created_at)}</td><td className="small">{i.items}</td>
            <td className="right num">{money(i.total)}</td><td><Badge map={INVOICE_STATUS} value={i.status} /></td></tr>)}</tbody></table></div>
      )}
      {edit && <CustomerForm initial={c} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); reload(); onChanged() }} />}
      {pts && <PointsDialog customer={c} onClose={() => setPts(false)} onDone={() => { setPts(false); reload(); onChanged() }} />}
    </Modal>
  )
}

export default function Customers() {
  const [q, setQ] = useState('')
  const [tier, setTier] = useState('')
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(null)
  const [adding, setAdding] = useState(false)
  const tiers = useLoad(() => api.get('/customer-tiers'), [])
  const { data, loading, error, reload } = useLoad(() => api.get('/customers', { q, tier_id: tier, page, size: 20 }), [q, tier, page])
  return (
    <div className="card">
      <div className="toolbar">
        <label className="grow">{t('Tìm khách hàng')}<input placeholder={t('SĐT hoặc tên (không cần dấu)')} value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></label>
        <label>{t('Hạng')}<select value={tier} onChange={(e) => { setTier(e.target.value); setPage(1) }}>
          <option value="">{t('Tất cả')}</option>{(tiers.data || []).map((tt) => <option key={tt.id} value={tt.id}>{t(tt.name)} ({tt.customer_count})</option>)}
        </select></label>
        <div className="actions"><button className="btn primary" onClick={() => setAdding(true)}><Icon name="plus" />{t('Thêm khách hàng')}</button></div>
      </div>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : data && (!data.items.length ? <Empty title={t('Không có khách hàng')} /> : <>
        <div className="table-wrap"><table>
          <thead><tr><th>{t('Mã')}</th><th>{t('Họ tên')}</th><th>{t('Điện thoại')}</th><th>{t('Hạng')}</th><th className="right">{t('Điểm')}</th><th className="right">{t('Tổng chi tiêu')}</th><th className="right">{t('Số HĐ')}</th></tr></thead>
          <tbody>{data.items.map((c) => (
            <tr key={c.id} className="clickable" onClick={() => setOpen(c.id)}>
              <td>{c.code}</td><td className="strong">{c.name}{!c.is_active && <span className="badge red">{t('Vô hiệu')}</span>}</td><td>{c.phone}</td>
              <td><span className="badge cyan">{t(c.tier_name)}</span></td><td className="right num">{num(c.loyalty_points)}</td>
              <td className="right num">{money(c.total_spent)}</td><td className="right">{c.invoice_count}</td>
            </tr>
          ))}</tbody>
        </table></div>
        <Pager page={page} size={20} total={data.total} onPage={setPage} />
      </>)}
      {open && <CustomerDetail id={open} onClose={() => setOpen(null)} onChanged={reload} />}
      {adding && <CustomerForm onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload() }} />}
    </div>
  )
}
