// Quản lý người dùng (UC-03 đến UC-05, FR-USR-01..05), chỉ quản trị viên
import { useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { ROLE_VI, fmtDateTime } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { ConfirmDialog, Empty, ErrorBox, Field, Loading, Modal, useLoad, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

function UserForm({ initial, branches, onClose, onSaved, onDelete }) {
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
      footer={<>
        {initial && onDelete && <button className="btn danger left" onClick={onDelete}><Icon name="trash" />{t('Xóa tài khoản')}</button>}
        <button className="btn primary" disabled={busy} onClick={save}><Icon name="save" />{t('Lưu')}</button>
      </>}>
      <div className="form-grid">
        {!initial && <Field label={t('Tên đăng nhập')}><input value={f.username} onChange={set('username')} autoComplete="off" /></Field>}
        <Field label={t('Họ tên')}><input value={f.full_name} onChange={set('full_name')} /></Field>
        {!initial && <Field label={t('Mật khẩu')} hint={t('Tối thiểu 8 ký tự, có chữ và số')}><input type="text" value={f.password} onChange={set('password')} autoComplete="new-password" /></Field>}
        <Field label={t('Vai trò')}><select value={f.role} onChange={set('role')}>
          {Object.entries(ROLE_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        {f.role !== 'admin' && <Field label={t('Chi nhánh')} hint={t('Tài khoản chỉ làm việc với dữ liệu của chi nhánh này')}>
          <select value={f.branch_id} onChange={set('branch_id')} required><option value="" disabled>{t('Chọn chi nhánh')}</option>
            {(branches || []).filter((b) => b.is_active || b.id === initial?.branch_id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field>}
        <Field label="Email" hint={t('Dùng để nhận mã khi quên mật khẩu')}><input type="email" value={f.email} onChange={set('email')} /></Field>
        <Field label={t('Số điện thoại')}><input value={f.phone} onChange={set('phone')} inputMode="tel" /></Field>
        {initial && <Field label={t('Trạng thái')}><select value={f.is_active ? '1' : '0'} onChange={(e) => setF({ ...f, is_active: e.target.value === '1' })}>
          <option value="1">{t('Đang hoạt động')}</option><option value="0">{t('Đã khóa')}</option></select></Field>}
      </div>
    </Modal>
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
  const [approveTo, setApproveTo] = useState({})  // id tài khoản chờ duyệt -> chi nhánh được chọn
  const activeBranches = (branches.data || []).filter((b) => b.is_active)
  return (
    <div className="stack">
      {pending.length > 0 && (
        <div className="card">
          <div className="card-head"><h2><Icon name="clock" />{t('Yêu cầu tạo tài khoản chờ duyệt')}</h2></div>
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Tên đăng nhập')}</th><th>{t('Họ tên')}</th><th>Email</th><th>{t('Vai trò yêu cầu')}</th><th>{t('Chi nhánh')}</th><th /></tr></thead>
            <tbody>{pending.map((u) => (
              <tr key={u.id}><td className="strong">{u.username}</td><td>{u.full_name}</td><td>{u.email}</td><td>{ROLE_VI[u.role]}</td>
                <td><select value={approveTo[u.id] || ''} onChange={(e) => setApproveTo({ ...approveTo, [u.id]: e.target.value })} aria-label={t('Chi nhánh')}>
                  <option value="" disabled>{t('Chọn chi nhánh')}</option>
                  {activeBranches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></td>
                <td className="right nowrap">
                  <button className="btn sm primary" disabled={!approveTo[u.id]} title={approveTo[u.id] ? undefined : t('Chọn chi nhánh trước khi duyệt')}
                    onClick={() => act(() => api.put(`/users/${u.id}`, { is_active: true, branch_id: Number(approveTo[u.id]) }), t('Đã duyệt {0}', [u.username]))}>{t('Duyệt')}</button>
                  <button className="btn sm danger" onClick={() => setDialog({ reject: u })}>{t('Từ chối')}</button></td></tr>
            ))}</tbody>
          </table></div>
        </div>
      )}
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
                  {u.id !== me.id && <button className="btn sm danger" title={t('Xóa tài khoản')} aria-label={t('Xóa tài khoản {0}', [u.username])}
                    onClick={() => setDialog({ remove: u })}><Icon name="trash" /></button>}
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      {dialog?.form && <UserForm initial={dialog.form.u} branches={branches.data} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); reload(); branches.reload() }}
        onDelete={dialog.form.u && dialog.form.u.id !== me.id ? () => setDialog({ remove: dialog.form.u }) : null} />}
      {dialog?.remove && <ConfirmDialog danger title={t('Xóa tài khoản')} confirmText={t('Xóa tài khoản')}
        message={t('Xóa tài khoản {0} ({1})? Người này sẽ không đăng nhập được nữa. Nếu tài khoản đã có hóa đơn, phiếu nhập... thì lịch sử đó vẫn được giữ và ghi tên người này.', [dialog.remove.username, dialog.remove.full_name])}
        onClose={() => setDialog(null)}
        onConfirm={async () => {
          try {
            const r = await api.del(`/users/${dialog.remove.id}`)
            toast(t(r.message), 'success'); reload(); branches.reload()
          } catch (e) { toast(e.message, 'error'); throw e }
        }} />}
      {dialog?.reset && <ResetPassword u={dialog.reset} onClose={() => setDialog(null)} />}
      {dialog?.reject && <ConfirmDialog danger title={t('Từ chối yêu cầu')} confirmText={t('Từ chối')} message={t('Xóa yêu cầu tạo tài khoản {0}?', [dialog.reject.username])}
        onClose={() => setDialog(null)} onConfirm={() => act(() => api.del(`/users/${dialog.reject.id}`), t('Đã từ chối yêu cầu'))} />}
    </div>
  )
}
