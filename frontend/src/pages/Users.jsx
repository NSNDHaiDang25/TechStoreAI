// Quản lý người dùng (UC-03 đến UC-05, FR-USR-01..05), chỉ quản trị viên
import { useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { ROLE_VI, fmtDateTime } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { ConfirmDialog, Empty, ErrorBox, Field, Loading, Modal, useLoad, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

function UserForm({ initial, branches, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState(initial
    ? { full_name: initial.full_name, role: initial.role, email: initial.email || '', phone: initial.phone || '', is_active: initial.is_active, branch_id: initial.branch_id || '' }
    : { username: '', full_name: '', password: '', role: 'staff', email: '', phone: '', branch_id: '' })
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const save = async () => {
    setBusy(true)
    try {
      const body = { ...f, email: f.email.trim() || null, phone: f.phone.trim() || null,
        branch_id: f.role === 'admin' ? null : Number(f.branch_id) || null }
      initial ? await api.put(`/users/${initial.id}`, body) : await api.post('/users', body)
      toast(initial ? t('Đã cập nhật tài khoản') : t('Đã tạo tài khoản {0}', [f.username]), 'success')
      onSaved()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  return (
    <Modal title={initial ? t('Sửa tài khoản {0}', [initial.username]) : t('Tạo tài khoản')} onClose={onClose}
      footer={<button className="btn primary" disabled={busy} onClick={save}><Icon name="save" />{t('Lưu')}</button>}>
      <div className="form-grid">
        {!initial && <Field label={t('Tên đăng nhập')}><input value={f.username} onChange={set('username')} autoComplete="off" /></Field>}
        <Field label={t('Họ tên')}><input value={f.full_name} onChange={set('full_name')} /></Field>
        {!initial && <Field label={t('Mật khẩu')} hint={t('Tối thiểu 8 ký tự, có chữ và số')}><input type="text" value={f.password} onChange={set('password')} autoComplete="new-password" /></Field>}
        <Field label={t('Vai trò')}><select value={f.role} onChange={set('role')}>
          {Object.entries(ROLE_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        {f.role !== 'admin' && <Field label={t('Chi nhánh')} hint={t('Thao tác của tài khoản này được ghi nhật ký vào chi nhánh này')}>
          <select value={f.branch_id} onChange={set('branch_id')}><option value="">{t('Chưa gán chi nhánh')}</option>
            {(branches || []).filter((b) => b.is_active || b.id === initial?.branch_id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field>}
        <Field label="Email" hint={t('Dùng để nhận mã khi quên mật khẩu')}><input type="email" value={f.email} onChange={set('email')} /></Field>
        <Field label={t('Số điện thoại')}><input value={f.phone} onChange={set('phone')} inputMode="tel" /></Field>
        {initial && <Field label={t('Trạng thái')}><select value={f.is_active ? '1' : '0'} onChange={(e) => setF({ ...f, is_active: e.target.value === '1' })}>
          <option value="1">{t('Đang hoạt động')}</option><option value="0">{t('Đã khóa')}</option></select></Field>}
      </div>
    </Modal>
  )
}

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

// Chi nhánh: mỗi chủ cửa hàng / nhân viên thuộc một chi nhánh để nhật ký thao tác tách theo từng cơ sở
function Branches({ data, onEdit }) {
  return (
    <div className="card">
      <div className="card-head"><h2><Icon name="building" />{t('Chi nhánh')}</h2>
        <button className="btn sm primary" onClick={() => onEdit({})}><Icon name="plus" />{t('Thêm chi nhánh')}</button></div>
      {!data ? <Loading /> : !data.length ? (
        <p className="muted m-0">{t('Chưa có chi nhánh. Thêm chi nhánh rồi gán chủ cửa hàng, nhân viên vào từng chi nhánh để xem nhật ký thao tác riêng từng cơ sở.')}</p>
      ) : (
        <div className="table-wrap"><table>
          <thead><tr><th>{t('Tên chi nhánh')}</th><th>{t('Địa chỉ')}</th><th className="right">{t('Số tài khoản')}</th><th>{t('Trạng thái')}</th><th /></tr></thead>
          <tbody>{data.map((b) => (
            <tr key={b.id}><td className="strong">{b.name}</td><td className="small">{b.address || <span className="muted">-</span>}</td>
              <td className="right num">{b.user_count}</td>
              <td>{b.is_active ? <span className="badge green">{t('Hoạt động')}</span> : <span className="badge">{t('Ngừng hoạt động')}</span>}</td>
              <td className="right"><button className="btn sm" title={t('Sửa')} onClick={() => onEdit({ b })}><Icon name="edit" /></button></td></tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  )
}

function ResetPassword({ u, onClose }) {
  const toast = useToast()
  const [pw, setPw] = useState('')
  const save = async () => {
    try { toast((await api.post(`/users/${u.id}/reset-password`, { new_password: pw })).message, 'success'); onClose() } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={t('Đặt lại mật khẩu cho {0}', [u.username])} size="narrow" onClose={onClose}
      footer={<button className="btn primary" disabled={pw.length < 8} onClick={save}><Icon name="key" />{t('Đặt lại mật khẩu')}</button>}>
      <Field label={t('Mật khẩu mới')} hint={t('Tối thiểu 8 ký tự, có chữ và số')}><input value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></Field>
    </Modal>
  )
}

export default function Users() {
  const { user: me } = useAuth()
  const toast = useToast()
  const { data, error, reload } = useLoad(() => api.get('/users'), [])
  const branches = useLoad(() => api.get('/branches'), [])
  const [dialog, setDialog] = useState(null)
  const act = async (fn, msg) => { try { await fn(); toast(msg, 'success'); reload() } catch (e) { toast(e.message, 'error') } }
  const locked = (u) => u.locked_until && new Date(u.locked_until) > new Date()
  const pending = (data || []).filter((u) => u.pending)
  return (
    <div className="stack">
      {pending.length > 0 && (
        <div className="card">
          <div className="card-head"><h2><Icon name="clock" />{t('Yêu cầu tạo tài khoản chờ duyệt')}</h2></div>
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Tên đăng nhập')}</th><th>{t('Họ tên')}</th><th>Email</th><th>{t('Vai trò yêu cầu')}</th><th /></tr></thead>
            <tbody>{pending.map((u) => (
              <tr key={u.id}><td className="strong">{u.username}</td><td>{u.full_name}</td><td>{u.email}</td><td>{ROLE_VI[u.role]}</td>
                <td className="right nowrap">
                  <button className="btn sm primary" onClick={() => act(() => api.put(`/users/${u.id}`, { is_active: true }), t('Đã duyệt {0}', [u.username]))}>{t('Duyệt')}</button>
                  <button className="btn sm danger" onClick={() => setDialog({ reject: u })}>{t('Từ chối')}</button></td></tr>
            ))}</tbody>
          </table></div>
        </div>
      )}
      <Branches data={branches.data} onEdit={(x) => setDialog({ branch: x })} />
      <div className="card">
        <div className="toolbar"><div className="actions"><button className="btn primary" onClick={() => setDialog({ form: {} })}><Icon name="plus" />{t('Tạo tài khoản')}</button></div></div>
        <ErrorBox error={error} />
        {!data ? <Loading /> : !data.length ? <Empty title={t('Chưa có người dùng')} /> : (
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Tên đăng nhập')}</th><th>{t('Họ tên')}</th><th>{t('Vai trò')}</th><th>{t('Chi nhánh')}</th><th>{t('Liên hệ')}</th><th>{t('Trạng thái')}</th><th>{t('Đăng nhập gần nhất')}</th><th /></tr></thead>
            <tbody>{data.filter((u) => !u.pending).map((u) => (
              <tr key={u.id}>
                <td className="strong">{u.username}{u.id === me.id && <span className="badge blue">{t('Bạn')}</span>}</td>
                <td>{u.full_name}</td><td>{ROLE_VI[u.role]}</td>
                <td className="small">{u.role === 'admin' ? <span className="muted">{t('Toàn hệ thống')}</span> : u.branch_name || <span className="muted">{t('Chưa gán')}</span>}</td>
                <td className="small">{u.email}<div className="muted">{u.phone}</div></td>
                <td>{!u.is_active ? <span className="badge red">{t('Đã khóa')}</span> : locked(u) ? <span className="badge yellow" title={t('Đến {0}', [fmtDateTime(u.locked_until)])}>{t('Khóa tạm')}</span> : <span className="badge green">{t('Hoạt động')}</span>}</td>
                <td className="small">{fmtDateTime(u.last_login_at) || '-'}</td>
                <td className="right nowrap">
                  {locked(u) && <button className="btn sm" onClick={() => act(() => api.put(`/users/${u.id}`, { unlock: true }), t('Đã mở khóa {0}', [u.username]))}>{t('Mở khóa')}</button>}
                  <button className="btn sm" title={t('Đặt lại mật khẩu')} onClick={() => setDialog({ reset: u })}><Icon name="key" /></button>
                  <button className="btn sm" title={t('Sửa')} onClick={() => setDialog({ form: { u } })}><Icon name="edit" /></button>
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      {dialog?.form && <UserForm initial={dialog.form.u} branches={branches.data} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); reload(); branches.reload() }} />}
      {dialog?.branch && <BranchForm initial={dialog.branch.b} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); branches.reload() }} />}
      {dialog?.reset && <ResetPassword u={dialog.reset} onClose={() => setDialog(null)} />}
      {dialog?.reject && <ConfirmDialog danger title={t('Từ chối yêu cầu')} confirmText={t('Từ chối')} message={t('Xóa yêu cầu tạo tài khoản {0}?', [dialog.reject.username])}
        onClose={() => setDialog(null)} onConfirm={() => act(() => api.del(`/users/${dialog.reject.id}`), t('Đã từ chối yêu cầu'))} />}
    </div>
  )
}
