// Nút trợ lý AI nổi cho chủ cửa hàng và nhân viên: bấm để hỏi nhanh trong khung chat nhỏ mà không rời trang đang làm.
// Kéo thả tự do, thả ra thì dạt về mép trái / phải gần nhất (không che giữa trang); vị trí nhớ trên trình duyệt này.
// Dùng chung cuộc trò chuyện với trang "Trợ lý đa năng", nên bấm "Mở rộng" sẽ xem tiếp đúng cuộc trò chuyện đó.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { initialsOf } from '../format.js'
import { AiTurn, CFG, readStored, replyMeta, storeKey, writeStored } from '../pages/AIChat.jsx'
import Icon from './Icon.jsx'
import { useToast } from './kit.jsx'
import { t } from '../i18n.js'

const HIDE_ON = ['/ai/assistant', '/ai/advisor', '/ai/ask']  // các trang này đã có khung chat riêng
const POS_KEY = 'aiFabPos'
const TOPBAR_GAP = 72  // không kéo lên che topbar
const cfg = CFG.assistant

const vw = () => document.documentElement.clientWidth  // bỏ phần thanh cuộn
const vh = () => document.documentElement.clientHeight
const isMobile = () => matchMedia('(max-width: 860px)').matches
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi))

// side = mép, t = độ cao theo tỉ lệ (0 sát topbar, 1 sát đáy) để giữ đúng chỗ khi đổi cỡ cửa sổ
function loadPos() {
  try {
    const v = JSON.parse(localStorage.getItem(POS_KEY))
    if (v && ['left', 'right'].includes(v.side) && v.t >= 0 && v.t <= 1) return v
  } catch { /* chưa lưu hoặc trình duyệt chặn: dùng vị trí mặc định */ }
  return { side: 'right', t: 1 }
}
const savePos = (p) => { try { localStorage.setItem(POS_KEY, JSON.stringify(p)) } catch { /* chế độ riêng tư */ } }

export default function AIFab({ pageTitle }) {
  const { user } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const loc = useLocation()
  const key = storeKey(user.id, 'assistant')
  const hidden = HIDE_ON.includes(loc.pathname)
  const [open, setOpen] = useState(false)
  const [session, setSession] = useState({ id: null, messages: [] })
  const [loading, setLoading] = useState(false)
  const [pending, setPending] = useState(false)
  const [text, setText] = useState('')
  const btn = useRef(null)
  const pop = useRef(null)
  const scroller = useRef(null)
  const input = useRef(null)
  const pos = useRef(loadPos())
  const drag = useRef(null)
  const justDragged = useRef(false)

  const bounds = () => {
    const size = btn.current.offsetWidth
    const m = isMobile() ? 16 : 24
    return { size, m, minY: TOPBAR_GAP, maxY: vh() - size - m }
  }

  // Khung chat mở về phía còn nhiều chỗ hơn (trên / dưới nút), bám cùng mép với nút
  const placePanel = useCallback(() => {
    if (!btn.current || !pop.current) return
    const r = btn.current.getBoundingClientRect()
    const gap = 12, edge = 12
    const above = r.top - gap - edge, below = vh() - r.bottom - gap - edge
    const up = above >= below
    const onLeft = r.left + r.width / 2 < vw() / 2
    Object.assign(pop.current.style, {
      height: `${Math.min(600, Math.max(up ? above : below, 240))}px`,
      top: up ? 'auto' : `${r.bottom + gap}px`,
      bottom: up ? `${vh() - r.top + gap}px` : 'auto',
      left: isMobile() ? '8px' : onLeft ? `${r.left}px` : 'auto',
      right: isMobile() ? '8px' : onLeft ? 'auto' : `${vw() - r.right}px`,
      transformOrigin: `${up ? 'bottom' : 'top'} ${onLeft ? 'left' : 'right'}`,
    })
  }, [])

  const applyPos = useCallback(() => {
    if (!btn.current) return
    const { size, m, minY, maxY } = bounds()
    const p = pos.current
    Object.assign(btn.current.style, {
      left: `${p.side === 'left' ? m : vw() - size - m}px`,
      top: `${minY + p.t * Math.max(0, maxY - minY)}px`,
      right: 'auto', bottom: 'auto',
    })
    document.body.classList.toggle('fab-left', p.side === 'left')
    placePanel()
  }, [placePanel])

  useLayoutEffect(() => {
    if (hidden) return undefined
    applyPos()
    window.addEventListener('resize', applyPos)
    return () => window.removeEventListener('resize', applyPos)
  }, [hidden, applyPos])

  // Chừa chỗ cuối trang cho nút, đẩy thông báo lên trên nút
  useEffect(() => {
    const b = document.body.classList
    b.toggle('fab-visible', !hidden)
    b.toggle('fab-open', open && !hidden)
    return () => b.remove('fab-visible', 'fab-open', 'fab-left')
  }, [hidden, open])

  useEffect(() => { if (hidden) setOpen(false) }, [hidden])

  // Mỗi lần mở: lấy lại cuộc trò chuyện đang dở (có thể vừa hỏi tiếp ở trang "Trợ lý đa năng")
  useEffect(() => {
    if (!open || pending) return
    const id = readStored(key)
    if (!id) { setSession({ id: null, messages: [] }); return }
    setLoading(true)
    api.get(`/ai/sessions/${id}`)
      .then((s) => setSession({ id: s.id, messages: s.messages }))
      .catch(() => { writeStored(key, null); setSession({ id: null, messages: [] }) })
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, key])

  useLayoutEffect(() => { if (open) { placePanel(); input.current?.focus() } }, [open, placePanel])
  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = session.messages.length ? el.scrollHeight : 0  // màn hình chào đọc từ trên xuống
  }, [session.messages.length, pending, loading])

  const onPointerDown = (e) => {
    if (e.button !== 0) return
    // Chặn kéo liên kết bên dưới (Chrome hủy thao tác kéo nút khi nút đè lên menu); "click" vẫn phát bình thường
    e.preventDefault()
    const r = btn.current.getBoundingClientRect()
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, dx: e.clientX - r.left, dy: e.clientY - r.top, moved: false }
    btn.current.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e) => {
    const d = drag.current
    if (!d || e.pointerId !== d.id) return
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5) return  // rung tay khi bấm: vẫn tính là bấm
    d.moved = true
    btn.current.classList.add('dragging')
    const { size, minY, maxY } = bounds()
    btn.current.style.left = `${clamp(e.clientX - d.dx, 0, vw() - size)}px`
    btn.current.style.top = `${clamp(e.clientY - d.dy, minY, maxY)}px`
    placePanel()
  }
  const onPointerUp = (e) => {
    const d = drag.current
    if (!d || e.pointerId !== d.id) return
    drag.current = null
    if (!d.moved) return
    btn.current.classList.remove('dragging')
    // Trình duyệt vẫn phát "click" ngay sau khi thả: bỏ qua lần đó để không mở / đóng khung ngoài ý muốn
    justDragged.current = true
    setTimeout(() => { justDragged.current = false }, 0)
    const r = btn.current.getBoundingClientRect()
    const { minY, maxY } = bounds()
    pos.current = { side: r.left + r.width / 2 < vw() / 2 ? 'left' : 'right', t: maxY > minY ? clamp((r.top - minY) / (maxY - minY), 0, 1) : 1 }
    savePos(pos.current)
    applyPos()
  }

  const grow = () => {
    const el = input.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight + 2, 120)}px`
  }
  useEffect(grow, [text])

  const send = async (raw) => {
    const q = raw.trim()
    if (!q || pending) return
    setText('')
    setPending(true)
    setSession((s) => ({ ...s, messages: [...s.messages, { role: 'user', content: q, created_at: new Date().toISOString() }] }))
    try {
      const res = await api.post(cfg.endpoint, { ...cfg.body(q), session_id: session.id })
      setSession((s) => ({ id: res.session_id,
        messages: [...s.messages, { id: res.message_id, role: 'assistant', content: res.answer, meta: replyMeta(res), created_at: new Date().toISOString() }] }))
      writeStored(key, res.session_id)
    } catch (e) {
      setSession((s) => ({ ...s, messages: [...s.messages, { role: 'assistant', content: e.message, error: true }] }))
    } finally {
      setPending(false)
      input.current?.focus()
    }
  }
  const newChat = () => {
    if (pending) return
    setSession({ id: null, messages: [] }); writeStored(key, null); input.current?.focus()
  }
  const close = () => { setOpen(false); btn.current?.focus() }
  const copy = (tt) => navigator.clipboard?.writeText(tt).then(() => toast(t('Đã sao chép câu trả lời'), 'success'), () => toast(t('Trình duyệt không cho sao chép'), 'error'))
  const addToCart = (s) => navigate('/pos', { state: { addCode: s.code } })

  if (hidden) return null
  // Gợi ý đầu tiên là hướng dẫn dùng chính trang đang mở
  const chips = [
    ...(pageTitle ? [[t('Cách dùng trang "{0}"', [pageTitle]), t('Hướng dẫn tôi cách dùng trang "{0}" trong phần mềm', [pageTitle])]] : []),
    ...cfg.suggestions(user.role !== 'staff').slice(0, 3).map(([, tt, , q]) => [tt, q]),
  ]
  return (
    <div className={`ai-fab-wrap ${open ? 'open' : ''}`}>
      {open && (
        <section className="ai-pop" ref={pop} role="dialog" aria-label={t('Trợ lý AI')}
          onKeyDown={(e) => { if (e.key === 'Escape') close() }}>
          <header className="ai-pop-head">
            <div className="ai-avatar"><Icon name="sparkles" /></div>
            <div className="grow"><div className="t">{cfg.name}</div><div className="s">{pending ? t('Đang trả lời...') : t('Sẵn sàng hỗ trợ bạn')}</div></div>
            <button type="button" className="icon-tool" onClick={newChat} title={t('Cuộc trò chuyện mới')} aria-label={t('Cuộc trò chuyện mới')}><Icon name="plus" /></button>
            <button type="button" className="icon-tool" onClick={() => { setOpen(false); navigate('/ai/assistant') }} title={t('Mở rộng toàn trang')} aria-label={t('Mở rộng toàn trang')}><Icon name="expand" /></button>
            <button type="button" className="icon-tool" onClick={close} title={t('Đóng (Esc)')} aria-label={t('Đóng')}><Icon name="x" /></button>
          </header>
          <div className="ai-pop-scroll" ref={scroller}>
            <div className="ai-pop-thread">
              {loading ? <div className="muted small">{t('Đang tải cuộc trò chuyện...')}</div> : !session.messages.length ? (
                <div className="ai-pop-welcome">
                  <div className="ai-orb sm"><Icon name="sparkles" /></div>
                  <div className="strong">{t('Xin chào,')} {user.full_name}!</div>
                  <p className="muted small">{user.role !== 'staff' ? t('Mình tra được sản phẩm, tồn kho, hóa đơn, doanh thu và hướng dẫn cách dùng phần mềm. Bạn cần giúp gì?') : t('Mình tra được sản phẩm, tồn kho, hóa đơn và hướng dẫn cách dùng phần mềm. Bạn cần giúp gì?')}</p>
                  <div className="ai-pop-chips">{chips.map(([tt, q]) => <button key={tt} type="button" className="chip" onClick={() => send(q)}>{tt}</button>)}</div>
                </div>
              ) : session.messages.map((m, i) => (m.role === 'user' ? (
                <div key={m.id || `u${i}`} className="turn-user"><div className="bubble">{m.content}</div><div className="avatar">{initialsOf(user.full_name)}</div></div>
              ) : <AiTurn key={m.id || `a${i}`} m={m} cfg={cfg} onCart={addToCart} onCopy={copy} />))}
              {pending && (
                <div className="turn-ai is-typing"><div className="ai-avatar"><Icon name="sparkles" /></div>
                  <div className="body"><div className="typing"><span /><span /><span /></div></div></div>
              )}
            </div>
          </div>
          <form className="ai-pop-composer" onSubmit={(e) => { e.preventDefault(); send(text) }}>
            <textarea ref={input} rows={1} maxLength={cfg.maxLength} value={text} placeholder={t('Hỏi bất cứ điều gì...')} aria-label={t('Câu hỏi cho trợ lý AI')}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(text) } }} />
            <button className="send-btn" type="submit" title={t('Gửi (Enter)')} aria-label={t('Gửi')} disabled={pending || !text.trim()}><Icon name="arrow-up" /></button>
          </form>
        </section>
      )}
      <button type="button" ref={btn} className="ai-fab" aria-expanded={open} aria-label={open ? t('Đóng trợ lý AI') : t('Mở trợ lý AI')}
        title={open ? t('Đóng trợ lý AI (kéo để di chuyển)') : t('Cần trợ giúp? Hỏi trợ lý AI (kéo để di chuyển)')}
        onClick={() => { if (!justDragged.current) setOpen(!open) }}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
        <Icon name={open ? 'x' : 'sparkles'} />
      </button>
    </div>
  )
}
