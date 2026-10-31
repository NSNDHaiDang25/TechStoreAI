// Chi nhánh (chỉ quản trị viên): thêm, sửa chi nhánh; xem và gán tài khoản chủ cửa hàng / nhân viên của từng chi nhánh;
// mở nhật ký thao tác riêng của chi nhánh.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { ROLE_VI } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Empty, ErrorBox, Field, Loading, Modal, useLoad, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

function BranchForm({ initial, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState({ name: initial?.name || '', address: initial?.address || '', is_active: initial ? initial.is_active : true })
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    try {
      initial ? await api.put(`/branches/${initial.id}`, f) : await api.post('/branches', f)
      toast(initial ? t('Đã cập nhật chi nhánh') : t('Đã thêm chi nhánh {0}', [f.name.trim()]), 'success')
      onSaved()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  return (
    <Modal title={initial ? t('Sửa chi nhánh') : t('Thêm chi nhánh')} size="narrow" onClose={onClose}
      footer={<button className="btn primary" disabled={busy || !f.name.trim()} onClick={save}><Icon name="save" />{t('Lưu')}</button>}>
      <div className="stack">
        <Field label={t('Tên chi nhánh')}><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={t('VD: Cơ sở Cầu Giấy')} /></Field>
        <Field label={t('Địa chỉ')}><input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></Field>
        {initial && <Field label={t('Trạng thái')}><select value={f.is_active ? '1' : '0'} onChange={(e) => setF({ ...f, is_active: e.target.value === '1' })}>
          <option value="1">{t('Đang hoạt động')}</option><option value="0">{t('Ngừng hoạt động')}</option></select></Field>}
      </div>
    </Modal>
  )
}

// Chi tiết một chi nhánh: danh sách tài khoản, thêm tài khoản vào chi nhánh, bỏ tài khoản khỏi chi nhánh
function BranchDetail({ id, onClose, onEdit, onChanged }) {
  const toast = useToast()
  const navigate = useNavigate()
  const { data, error, reload } = useLoad(() => api.get(`/branches/${id}`), [id])
  const users = useLoad(() => api.get('/users'), [])
  const [pick, setPick] = useState('')
  const candidates = (users.data || []).filter((u) => !u.pending && u.role !== 'admin' && u.branch_id !== id)
  const move = async (u, branchId, msg) => {
    try {
      await api.put(`/users/${u.id}`, { branch_id: branchId })
      toast(msg, 'success'); setPick(''); reload(); users.reload(); onChanged()
    } catch (e) { toast(e.message, 'error') }
  }
  const add = () => {
    const u = candidates.find((x) => String(x.id) === pick)
    if (u) move(u, id, t('Đã thêm {0} vào chi nhánh', [u.full_name]))
  }
  return (
    <Modal title={data?.name || t('Chi nhánh')} icon="store" size="wide" onClose={onClose} footer={<>
      <button className="btn" onClick={() => navigate(`/audit?branch=${id}`)}><Icon name="clipboard" />{t('Nhật ký thao tác')}</button>
      {data && <button className="btn primary" onClick={() => onEdit(data)}><Icon name="edit" />{t('Sửa thông tin')}</button>}
    </>}>
      <ErrorBox error={error} />
      {!data ? <Loading /> : <div className="stack">
        <div className="branch-meta">
          <span className="muted">{data.address || t('Chưa có địa chỉ')}</span>
          {data.is_active ? <span className="badge green">{t('Hoạt động')}</span> : <span className="badge">{t('Ngừng hoạt động')}</span>}
        </div>
        <div className="branch-stats">
          <div><span className="value">{data.owner_count}</span><span className="label">{t('Chủ cửa hàng')}</span></div>
          <div><span className="value">{data.staff_count}</span><span className="label">{t('Nhân viên')}</span></div>
          <div><span className="value">{data.actions_30d}</span><span className="label">{t('Thao tác 30 ngày')}</span></div>
        </div>
        <div className="branch-add">
          <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label={t('Chọn tài khoản để thêm vào chi nhánh')}>
            <option value="">{t('Chọn tài khoản để thêm vào chi nhánh...')}</option>
            {candidates.map((u) => <option key={u.id} value={u.id}>
              {u.full_name} · {ROLE_VI[u.role]} · {u.branch_name ? t('đang ở {0}', [u.branch_name]) : t('chưa gán chi nhánh')}</option>)}
          </select>
          <button className="btn primary" disabled={!pick} onClick={add}><Icon name="plus" />{t('Thêm vào chi nhánh')}</button>
        </div>
        <p className="muted small m-0">{t('Chuyển tài khoản sang chi nhánh này thì từ lúc đó tài khoản chỉ thấy và làm việc với dữ liệu của chi nhánh này.')}</p>
        {!data.users.length ? <Empty icon="users" title={t('Chi nhánh chưa có tài khoản nào')} /> : (
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Họ tên')}</th><th>{t('Tên đăng nhập')}</th><th>{t('Vai trò')}</th><th>{t('Trạng thái')}</th></tr></thead>
            <tbody>{data.users.map((u) => (
              <tr key={u.id}><td className="strong">{u.full_name}</td><td>{u.username}</td><td>{ROLE_VI[u.role]}</td>
                <td>{u.is_active ? <span className="badge green">{t('Hoạt động')}</span> : <span className="badge red">{t('Đã khóa')}</span>}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>}
    </Modal>
  )
}

export default function Branches() {
  const { data, error, reload } = useLoad(() => api.get('/branches'), [])
  const [dialog, setDialog] = useState(null)  // { form: branch | {} } | { detail: id }
  return (
    <div className="card">
      <div className="card-head"><h2><Icon name="store" />{t('Chi nhánh')}</h2>
        <button className="btn primary" onClick={() => setDialog({ form: {} })}><Icon name="plus" />{t('Thêm chi nhánh')}</button></div>
      <p className="muted mt-0">{t('Mỗi chi nhánh độc lập: sản phẩm, kho, hóa đơn, khách hàng, khuyến mãi, báo cáo và cấu hình cửa hàng riêng. Chủ cửa hàng và nhân viên chỉ thấy dữ liệu chi nhánh của mình.')}</p>
      <ErrorBox error={error} />
      {!data ? <Loading /> : !data.length ? <Empty icon="store" title={t('Chưa có chi nhánh')} /> : (
        <div className="branch-grid">{data.map((b) => (
          <button key={b.id} type="button" className={`branch-card ${b.is_active ? '' : 'inactive'}`} onClick={() => setDialog({ detail: b.id })}>
            <span className="branch-card-top">
              <span className="branch-icon"><Icon name="store" /></span>
              <span className="branch-name">{b.name}</span>
              {!b.is_active && <span className="badge">{t('Ngừng hoạt động')}</span>}
            </span>
            <span className="muted small branch-address">{b.address || t('Chưa có địa chỉ')}</span>
            <span className="branch-counts">
              <span><Icon name="user" />{b.owner_count} {t('chủ')}</span>
              <span><Icon name="users" />{b.staff_count} {t('nhân viên')}</span>
              <span><Icon name="clipboard" />{b.actions_30d} {t('thao tác')}</span>
            </span>
          </button>
        ))}</div>
      )}
      {dialog?.detail && <BranchDetail id={dialog.detail} onClose={() => setDialog(null)} onChanged={reload}
        onEdit={(b) => setDialog({ form: b, back: b.id })} />}
      {dialog?.form && <BranchForm initial={dialog.form.id ? dialog.form : null}
        onClose={() => setDialog(dialog.back ? { detail: dialog.back } : null)}
        onSaved={() => { reload(); setDialog(dialog.back ? { detail: dialog.back } : null) }} />}
    </div>
  )
}
