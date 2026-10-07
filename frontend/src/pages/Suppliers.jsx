// Nhà cung cấp (UC-35)
import { useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { PO_STATUS, fmtDateTime, money } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Badge, Empty, ErrorBox, Field, Loading, Modal, useLoad, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

function SupplierForm({ initial, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState(initial || { code: '', name: '', contact_name: '', phone: '', email: '', address: '', tax_code: '', status: 'active' })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const save = async () => {
    const body = { ...f, phone: f.phone || null, email: f.email || null, code: f.code || null }
    try { initial ? await api.put(`/suppliers/${initial.id}`, body) : await api.post('/suppliers', body); toast(t('Đã lưu nhà cung cấp'), 'success'); onSaved() } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={initial ? t('Sửa nhà cung cấp') : t('Thêm nhà cung cấp')} onClose={onClose} footer={<button className="btn primary" onClick={save}>{t('Lưu')}</button>}>
      <div className="form-grid">
        <Field label={t('Mã')} hint={t('Bỏ trống: tự sinh NCC01...')}><input value={f.code || ''} onChange={set('code')} /></Field>
        <Field label={t('Tên')}><input value={f.name} onChange={set('name')} /></Field>
        <Field label={t('Người liên hệ')}><input value={f.contact_name || ''} onChange={set('contact_name')} /></Field>
        <Field label={t('Điện thoại')}><input value={f.phone || ''} onChange={set('phone')} /></Field>
        <Field label="Email"><input value={f.email || ''} onChange={set('email')} /></Field>
        <Field label={t('Mã số thuế')}><input value={f.tax_code || ''} onChange={set('tax_code')} /></Field>
        <Field label={t('Địa chỉ')} full><input value={f.address || ''} onChange={set('address')} /></Field>
        <Field label={t('Trạng thái')}><select value={f.status} onChange={set('status')}><option value="active">{t('Đang hợp tác')}</option><option value="inactive">{t('Ngừng hợp tác')}</option></select></Field>
      </div>
    </Modal>
  )
}

function SupplierHistory({ id, onClose }) {
  const { user } = useAuth()
  const { data } = useLoad(() => api.get(`/suppliers/${id}`), [id])
  return (
    <Modal title={data ? `${data.code} · ${data.name}` : t('Nhà cung cấp')} onClose={onClose} size="wide">
      {!data ? <Loading /> : <>
        <div className="info-list">
          <div><span className="muted">{t('Liên hệ')}</span><span>{data.contact_name || '-'}</span></div>
          <div><span className="muted">{t('Điện thoại')}</span><span>{data.phone || '-'}</span></div>
          <div><span className="muted">Email</span><span>{data.email || '-'}</span></div>
          <div><span className="muted">{t('Mã số thuế')}</span><span>{data.tax_code || '-'}</span></div>
        </div>
        <h3>{t('Lịch sử phiếu nhập')}</h3>
        {!data.purchase_orders.length ? <p className="muted">{t('Chưa có phiếu nhập')}</p> : (
          <div className="table-wrap"><table><thead><tr><th>{t('Mã phiếu')}</th><th>{t('Ngày lập')}</th><th className="right">{t('Số lượng')}</th>{user.role !== 'staff' && <th className="right">{t('Tổng tiền')}</th>}<th>{t('Trạng thái')}</th></tr></thead>
            <tbody>{data.purchase_orders.map((o) => <tr key={o.id}><td>{o.code}</td><td>{fmtDateTime(o.created_at)}</td><td className="right">{o.quantity}</td>
              {user.role !== 'staff' && <td className="right num">{money(o.total)}</td>}<td><Badge map={PO_STATUS} value={o.status} /></td></tr>)}</tbody></table></div>
        )}
      </>}
    </Modal>
  )
}

export default function Suppliers() {
  const { user } = useAuth()
  const owner = user.role === 'owner'
  const toast = useToast()
  const [q, setQ] = useState('')
  const [dialog, setDialog] = useState(null)
  const { data, loading, error, reload } = useLoad(() => api.get('/suppliers', { q }), [q])
  const remove = async (s) => { try { toast((await api.del(`/suppliers/${s.id}`)).message, 'success'); reload() } catch (e) { toast(e.message, 'error') } }
  return (
    <div className="card">
      <div className="toolbar">
        <label className="grow">{t('Tìm nhà cung cấp')}<input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('Mã, tên, số điện thoại')} /></label>
        {owner && <div className="actions"><button className="btn primary" onClick={() => setDialog({ type: 'form' })}><Icon name="plus" />{t('Thêm nhà cung cấp')}</button></div>}
      </div>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : data && (!data.length ? <Empty title={t('Chưa có nhà cung cấp')} /> : (
        <div className="table-wrap"><table>
          <thead><tr><th>{t('Mã')}</th><th>{t('Tên')}</th><th>{t('Liên hệ')}</th><th>{t('Điện thoại')}</th>{owner && <><th className="right">{t('Số phiếu')}</th><th className="right">{t('Tổng nhập')}</th></>}<th>{t('Trạng thái')}</th>{owner && <th />}</tr></thead>
          <tbody>{data.map((s) => (
            <tr key={s.id} className="clickable" onClick={() => setDialog({ type: 'history', id: s.id })}>
              <td>{s.code}</td><td className="strong">{s.name}</td><td>{s.contact_name || '-'}</td><td>{s.phone || '-'}</td>
              {owner && <><td className="right">{s.order_count}</td><td className="right num">{money(s.total_amount)}</td></>}
              <td>{s.status === 'active' ? <span className="badge green">{t('Đang hợp tác')}</span> : <span className="badge">{t('Ngừng')}</span>}</td>
              {owner && <td className="right nowrap" onClick={(e) => e.stopPropagation()}>
                <button className="btn sm" onClick={() => setDialog({ type: 'form', s })}><Icon name="edit" /></button>
                <button className="btn sm danger" onClick={() => remove(s)}><Icon name="trash" /></button></td>}
            </tr>
          ))}</tbody>
        </table></div>
      ))}
      {dialog?.type === 'form' && <SupplierForm initial={dialog.s} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); reload() }} />}
      {dialog?.type === 'history' && <SupplierHistory id={dialog.id} onClose={() => setDialog(null)} />}
    </div>
  )
}
