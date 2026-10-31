import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { ROLE_VI } from '../format.js'
import { ThemeToggle } from '../Shell.jsx'
import BrandLogo from '../ui/BrandLogo.jsx'
import FaceCamera from '../ui/FaceCamera.jsx'
import Icon from '../ui/Icon.jsx'
import LangToggle from '../ui/LangToggle.jsx'
import { Modal, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

const FRAME_GAP = 150       // ms nghỉ giữa hai khung hình gửi lên máy chủ (mỗi khung máy chủ chấm khoảng 50 ms)
const GREET_MS = 1500       // hiện lời chào kèm vai trò một lúc rồi mới vào hệ thống
const STEP_LABEL = { center: t('Nhìn thẳng'), left: t('Quay trái'), right: t('Quay phải') }
const ROLE_ICON = { owner: 'store', admin: 'shield' }

// Đăng nhập Face ID (chủ cửa hàng, quản trị viên) kèm kiểm tra người thật: máy chủ ra thử thách
// nhìn thẳng rồi quay đầu trái / phải theo thứ tự ngẫu nhiên, trình duyệt gửi liên tục từng khung hình để chấm.
function FaceLoginDialog({ remember, onClose }) {
  const { acceptLogin } = useAuth()
  const cam = useRef(null)
  const run = useRef(0)  // tăng mỗi lần bắt đầu / đóng để vòng gửi khung hình cũ tự dừng
  const [steps, setSteps] = useState([])
  const [step, setStep] = useState(0)
  const [hint, setHint] = useState(t('Nhìn thẳng vào camera'))
  const [who, setWho] = useState(null)       // { full_name, role } khi đã nhận diện được
  const [phase, setPhase] = useState('scanning')  // scanning | done | failed
  const [photo, setPhoto] = useState('')     // khung hình lúc nhận diện ra người, làm ảnh đại diện (chỉ giữ trong trình duyệt)
  const photoRef = useRef('')
  const setPhotoUrl = (url) => { if (photoRef.current) URL.revokeObjectURL(photoRef.current); photoRef.current = url; setPhoto(url) }

  const scan = useCallback(async () => {
    const id = ++run.current
    setPhase('scanning'); setWho(null); setStep(0); setSteps([]); setHint(t('Nhìn thẳng vào camera')); setPhotoUrl('')
    try {
      const s = await api.post('/auth/face-login/start')
      if (run.current !== id) return
      setSteps(s.steps); setHint(t(s.hint))
      while (run.current === id) {
        const image = await cam.current?.capture()
        if (run.current !== id) return
        if (image) {
          const form = new FormData()
          form.append('session', s.session)
          form.append('file', image, 'face.jpg')
          const r = await api.upload('/auth/face-login/frame', form)
          if (run.current !== id) return
          setStep(r.step)
          if (r.user) {
            if (!photoRef.current) setPhotoUrl(URL.createObjectURL(image))
            setWho({ full_name: r.user.full_name, role: r.user.role })
          }
          if (r.done) {
            setPhase('done')
            setTimeout(() => { if (run.current === id) acceptLogin(r, remember) }, GREET_MS)
            return
          }
          setHint(t(r.hint))
        }
        await new Promise((ok) => setTimeout(ok, FRAME_GAP))
      }
    } catch (e) {
      if (run.current === id) { setPhase('failed'); setHint(e.message) }
    }
  }, [acceptLogin, remember])

  useEffect(() => () => {  // đóng hộp thoại thì dừng gửi và bỏ ảnh tạm
    run.current += 1
    if (photoRef.current) URL.revokeObjectURL(photoRef.current)
  }, [])

  const camState = phase === 'done' ? 'ok' : phase === 'failed' ? 'miss' : 'scanning'
  const name = !who ? t('Đang nhận diện...') : phase === 'done' ? t('Xin chào, {name}', { name: who.full_name }) : who.full_name
  // Dòng trạng thái dưới tên cũng là lời hướng dẫn (camera không còn thanh chữ đè lên hình)
  const sub = phase === 'failed' || !who ? hint
    : phase === 'done' ? `${ROLE_VI[who.role]} · ${t('Đang vào hệ thống...')}`
    : `${ROLE_VI[who.role]} · ${hint}`
  return (
    <Modal title={t('Đăng nhập bằng Face ID')} icon="scan" onClose={onClose} size="narrow face-modal">
      <div className={`face-who ${who ? 'known' : ''} ${phase}`} aria-live="polite">
        <span className="face-who-avatar">
          {photo ? <img src={photo} alt="" /> : <Icon name={who ? ROLE_ICON[who.role] || 'user' : 'user'} />}
          {who && <span className="face-who-badge" />}
        </span>
        <span className="face-who-text">
          <span className="face-who-name">{name}</span>
          <span className="face-who-status"><span className="face-who-dot" />{sub}</span>
        </span>
      </div>
      <FaceCamera ref={cam} state={camState} onReady={scan} />
      {steps.length > 1 && (
        <ol className="face-steps">
          {steps.map((s, i) => {
            const done = i < step || phase === 'done'
            return (
              <li key={s} className={done ? 'done' : i === step && phase === 'scanning' ? 'active' : ''} aria-current={!done && i === step ? 'step' : undefined}>
                <span className="face-step-dot">{done ? <Icon name="check" /> : i + 1}</span>{STEP_LABEL[s]}
              </li>
            )
          })}
        </ol>
      )}
      <p className="face-hint">{t('Dành cho chủ cửa hàng và quản trị viên đã đăng ký Face ID. Nhìn thẳng để nhận diện, sau đó quay đầu theo hướng dẫn để xác minh là người thật, không phải ảnh chụp.')}</p>
      <div className="face-actions">
        {phase === 'failed' && <button className="btn primary block lg" onClick={scan}><Icon name="refresh" />{t('Thử lại')}</button>}
        <button className="btn block lg" onClick={onClose}><Icon name="key" />{t('Dùng mật khẩu truyền thống')}</button>
      </div>
    </Modal>
  )
}

function ForgotDialog({ onClose }) {
  const toast = useToast()
  const [step, setStep] = useState(1)
  const [f, setF] = useState({ username: '', code: '', new_password: '' })
  const [err, setErr] = useState('')
  const send = async () => {
    setErr('')
    try { toast((await api.post('/auth/forgot-password', { username: f.username })).message, 'success'); setStep(2) } catch (e) { setErr(e.message) }
  }
  const reset = async () => {
    setErr('')
    try { toast((await api.post('/auth/reset-password', f)).message, 'success'); onClose() } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title={t('Quên mật khẩu')} onClose={onClose} size="narrow" footer={step === 1
      ? <button className="btn primary" onClick={send} disabled={!f.username}>{t('Gửi mã xác nhận')}</button>
      : <button className="btn primary" onClick={reset} disabled={!f.code || !f.new_password}>{t('Đặt lại mật khẩu')}</button>}>
      <p className="muted mt-0">{t('Mã 6 số được gửi tới email của tài khoản. Tài khoản chưa có email hãy nhờ quản trị viên đặt lại.')}</p>
      <div className="stack">
        <label>{t('Tên đăng nhập')}<input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></label>
        {step === 2 && <>
          <label>{t('Mã xác nhận')}<input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></label>
          <label>{t('Mật khẩu mới')}<input type="password" value={f.new_password} placeholder={t('Tối thiểu 8 ký tự, có chữ và số')}
            onChange={(e) => setF({ ...f, new_password: e.target.value })} /></label>
        </>}
        <p className="error">{err}</p>
      </div>
    </Modal>
  )
}

export default function Login() {
  const { login } = useAuth()
  const [form, setForm] = useState({ username: '', password: '', remember: true })
  const [show, setShow] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [forgot, setForgot] = useState(false)
  const [faceOpen, setFaceOpen] = useState(false)
  const [faceEnabled, setFaceEnabled] = useState(false)

  useEffect(() => {
    api.get('/auth/face-login/status').then((r) => setFaceEnabled(r.enabled)).catch(() => {})
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    const { username, password } = form
    setBusy(true); setError('')
    try { await login(username.trim(), password, form.remember) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return (
    <section className="auth">
      <aside className="auth-hero">
        <img className="auth-hero-img" src="/static/img/login-bg.webp" alt="" aria-hidden="true" />
        <div className="auth-hero-inner">
          <div className="auth-logo"><BrandLogo onDark />TechStoreAI</div>
          <div>
            <h1 className="auth-title">{t('Quản lý bán hàng')}<br /><span className="accent-text">{t('thiết bị điện tử')}</span></h1>
            <p className="auth-lead">{t('Bán hàng tại quầy, serial và bảo hành, đổi trả 24 giờ, khuyến mãi, tích điểm, nhập kho và báo cáo. Trợ lý AI tư vấn sản phẩm và phân tích doanh thu từ dữ liệu thật.')}</p>
            <span className="auth-pill">{t('Đề tài 01 · Nhóm 1')}</span>
          </div>
          <div className="auth-copy">© 2026 TechStoreAI</div>
        </div>
      </aside>
      <main className="auth-main">
        <div className="auth-top">
          <div className="auth-top-actions"><LangToggle /><ThemeToggle /></div>
        </div>
        <form className="auth-card" onSubmit={submit}>
          <div className="auth-card-brand"><BrandLogo />TechStoreAI</div>
          <div>
            <h2 className="auth-card-title">{t('Chào mừng trở lại')}</h2>
            <p className="muted auth-card-sub">{t('Đăng nhập để tiếp tục vào hệ thống.')}</p>
          </div>
          <label>{t('Tên đăng nhập')}
            <div className="input-icon"><Icon name="user" />
              <input value={form.username} autoComplete="username" required placeholder={t('Nhập tên đăng nhập')}
                onChange={(e) => setForm({ ...form, username: e.target.value })} /></div>
          </label>
          <label>{t('Mật khẩu')}
            <div className="input-icon has-action"><Icon name="lock" />
              <input type={show ? 'text' : 'password'} value={form.password} autoComplete="current-password" required
                placeholder={t('Nhập mật khẩu')} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <button type="button" className="input-action" onClick={() => setShow(!show)} aria-label={t('Hiện mật khẩu')}><Icon name="eye" /></button>
            </div>
          </label>
          <div className="auth-row">
            <label className="checkbox"><input type="checkbox" checked={form.remember}
              onChange={(e) => setForm({ ...form, remember: e.target.checked })} />{t('Ghi nhớ đăng nhập')}</label>
            <button type="button" className="link-btn" onClick={() => setForgot(true)}>{t('Quên mật khẩu?')}</button>
          </div>
          <button className="btn primary block lg" type="submit" disabled={busy}>{busy ? t('Đang đăng nhập...') : t('Đăng nhập')}</button>
          <p className="error" role="alert">{error}</p>
          {faceEnabled && <>
            <div className="auth-divider">{t('hoặc')}</div>
            <button type="button" className="btn block lg" onClick={() => setFaceOpen(true)}>
              <Icon name="scan" />{t('Đăng nhập bằng Face ID')}
            </button>
          </>}
          <p className="auth-secure"><Icon name="shield" /> {t('Sai mật khẩu 5 lần liên tiếp tài khoản bị khóa 15 phút')}</p>
        </form>
        <div className="auth-foot"><span>{t('Phiên bản 2.0')}</span><a href="/docs" target="_blank" rel="noopener">{t('Tài liệu API')}</a></div>
      </main>
      {forgot && <ForgotDialog onClose={() => setForgot(false)} />}
      {faceOpen && <FaceLoginDialog remember={form.remember} onClose={() => setFaceOpen(false)} />}
    </section>
  )
}
