import { useRef, useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { ROLE_VI, fmtDateTime } from '../format.js'
import FaceCamera from '../ui/FaceCamera.jsx'
import Icon from '../ui/Icon.jsx'
import { ConfirmDialog, ErrorBox, Loading, Modal, useLoad, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

export function ChangePasswordForm({ forced, onDone }) {
  const toast = useToast()
  const [f, setF] = useState({ old_password: '', new_password: '', confirm: '' })
  const [err, setErr] = useState('')
  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    if (f.new_password !== f.confirm) { setErr(t('Mật khẩu nhập lại không khớp')); return }
    try {
      await api.post('/auth/change-password', { old_password: f.old_password, new_password: f.new_password })
      toast(t('Đã đổi mật khẩu'), 'success')
      setF({ old_password: '', new_password: '', confirm: '' })
      onDone?.()
    } catch (e2) { setErr(e2.message) }
  }
  return (
    <form className="stack" onSubmit={submit}>
      {forced && <p className="note mt-0">{t('Tài khoản mới hoặc vừa được đặt lại mật khẩu: bạn cần đổi mật khẩu trước khi sử dụng.')}</p>}
      <label>{t('Mật khẩu hiện tại')}<input type="password" required value={f.old_password} onChange={(e) => setF({ ...f, old_password: e.target.value })} /></label>
      <label>{t('Mật khẩu mới')}<input type="password" required value={f.new_password} placeholder={t('Tối thiểu 8 ký tự, có chữ và số')}
        onChange={(e) => setF({ ...f, new_password: e.target.value })} /></label>
      <label>{t('Nhập lại mật khẩu mới')}<input type="password" required value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} /></label>
      <p className="error">{err}</p>
      <button className="btn primary" type="submit"><Icon name="key" />{t('Đổi mật khẩu')}</button>
    </form>
  )
}

export function ForcedChange() {
  const { refresh, logout } = useAuth()
  return (
    <section className="auth">
      <main className="auth-main" style={{ margin: '0 auto' }}>
        <div className="auth-card">
          <div className="auth-card-brand"><span className="brand-mark"><Icon name="store" /></span>TechStoreAI</div>
          <h2 className="auth-card-title">{t('Đổi mật khẩu')}</h2>
          <ChangePasswordForm forced onDone={refresh} />
          <button className="link-btn" onClick={logout}>{t('Đăng xuất')}</button>
        </div>
      </main>
    </section>
  )
}

// Thêm ảnh mẫu Face ID: chụp từ webcam hoặc chọn ảnh có sẵn, hỏi lại mật khẩu trước khi lưu
function FaceEnrollDialog({ onClose, onDone }) {
  const toast = useToast()
  const cam = useRef(null)
  const picker = useRef(null)
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const send = async (image) => {
    if (!image) return
    setErr(''); setBusy(true)
    const form = new FormData()
    form.append('file', image, image.name || 'face.jpg')
    form.append('password', password)
    try {
      const r = await api.upload('/auth/face', form)
      toast(t(r.message), 'success'); onDone(); onClose()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <Modal title={t('Thêm khuôn mặt Face ID')} onClose={onClose} size="narrow" footer={<>
      <input ref={picker} type="file" accept="image/jpeg,image/png,image/webp" hidden
        onChange={(e) => { send(e.target.files[0]); e.target.value = '' }} />
      <button className="btn" disabled={!password || busy} onClick={() => picker.current.click()}>
        <Icon name="upload" />{t('Chọn ảnh')}</button>
      <button className="btn primary" disabled={!password || busy} onClick={async () => send(await cam.current?.capture())}>
        <Icon name="camera" />{busy ? t('Đang xử lý...') : t('Chụp và lưu')}
      </button>
    </>}>
      <div className="stack">
        <FaceCamera ref={cam} />
        <p className="muted face-hint">{t('Nhìn thẳng vào camera, đủ sáng, chỉ một người trong khung. Thêm 2-3 ảnh ở góc hơi khác nhau để nhận diện chính xác hơn.')}</p>
        <label>{t('Mật khẩu hiện tại')}<input type="password" value={password} autoComplete="current-password"
          onChange={(e) => setPassword(e.target.value)} /></label>
        <p className="error">{err}</p>
      </div>
    </Modal>
  )
}

function FaceIdCard() {
  const toast = useToast()
  const { data, error, reload } = useLoad(() => api.get('/auth/face'), [])
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState(false)
  const remove = async () => {
    try { toast(t((await api.del('/auth/face')).message), 'success'); reload() } catch (e) { toast(e.message, 'error') }
  }
  return (
    <div className="card">
      <div className="card-head"><h2><Icon name="scan" />Face ID</h2></div>
      <ErrorBox error={error} />
      {!data ? <Loading /> : <>
        <div className="info-list">
          <div><span className="muted">{t('Trạng thái')}</span>
            <span className={data.count ? 'strong' : ''}>{data.count ? t('Đã đăng ký') : t('Chưa đăng ký')}</span></div>
          <div><span className="muted">{t('Số ảnh mẫu')}</span><span>{data.count} / {data.max}</span></div>
          {data.updated_at && <div><span className="muted">{t('Cập nhật gần nhất')}</span><span>{fmtDateTime(data.updated_at)}</span></div>}
        </div>
        {!data.enabled && <p className="note">{t('Quản trị viên đang tắt đăng nhập Face ID.')}</p>}
        {!data.installed && <p className="note">{t('Máy chủ chưa cài OpenCV nên chưa dùng được Face ID.')}</p>}
        <p className="muted face-hint">{t('Sau khi đăng ký, bấm "Đăng nhập bằng Face ID" ở màn hình đăng nhập để vào hệ thống không cần mật khẩu.')}</p>
        <div className="row">
          <button className="btn primary" disabled={data.count >= data.max || !data.installed} onClick={() => setAdding(true)}>
            <Icon name="plus" />{t('Thêm khuôn mặt')}</button>
          {data.count > 0 && <button className="btn danger" onClick={() => setRemoving(true)}><Icon name="trash" />{t('Xóa Face ID')}</button>}
        </div>
      </>}
      {adding && <FaceEnrollDialog onClose={() => setAdding(false)} onDone={reload} />}
      {removing && <ConfirmDialog title={t('Xóa Face ID')} danger confirmText={t('Xóa')}
        message={t('Xóa toàn bộ ảnh mẫu khuôn mặt? Bạn sẽ chỉ đăng nhập được bằng mật khẩu cho đến khi đăng ký lại.')}
        onConfirm={remove} onClose={() => setRemoving(false)} />}
    </div>
  )
}

export default function Account() {
  const { user } = useAuth()
  return (
    <div className="grid two w-lg">
      <div className="card">
        <div className="card-head"><h2><Icon name="user" />{t('Thông tin tài khoản')}</h2></div>
        <div className="info-list">
          <div><span className="muted">{t('Tên đăng nhập')}</span><span className="strong">{user.username}</span></div>
          <div><span className="muted">{t('Họ tên')}</span><span>{user.full_name}</span></div>
          <div><span className="muted">{t('Vai trò')}</span><span>{ROLE_VI[user.role]}</span></div>
          <div><span className="muted">Email</span><span>{user.email || t('Chưa có')}</span></div>
          <div><span className="muted">{t('Đăng nhập gần nhất')}</span><span>{fmtDateTime(user.last_login_at)}</span></div>
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h2><Icon name="key" />{t('Đổi mật khẩu')}</h2></div>
        <ChangePasswordForm />
      </div>
      {['owner', 'admin'].includes(user.role) && <FaceIdCard />}
    </div>
  )
}
