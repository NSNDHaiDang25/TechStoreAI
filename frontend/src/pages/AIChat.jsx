// Khung chat AI dùng chung: trợ lý đa năng, chatbot tư vấn sản phẩm (UC-34), hỏi đáp dữ liệu bán hàng (UC-36).
// Lịch sử trò chuyện lưu ở server (bảng chat_sessions); trình duyệt chỉ nhớ id cuộc đang mở.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { initialsOf, money } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { ConfirmDialog, Empty, Modal, Thumb, useToast } from '../ui/kit.jsx'
import Markdown from '../ui/Markdown.jsx'
import { locale, numLocale, t } from '../i18n.js'

export const CFG = {
  assistant: {
    endpoint: '/ai/assistant', name: t('Trợ lý TechStoreAI'), cart: true,
    greeting: t('Hôm nay mình giúp gì được cho bạn?'),
    intro: t('Hỏi về sản phẩm, giá, tồn kho, hóa đơn, khách hàng, doanh thu hay cách dùng phần mềm. Trợ lý tự tra dữ liệu thật của cửa hàng trong phạm vi quyền của bạn.'),
    placeholder: t('VD: tuần này bán được bao nhiêu? sạc nào dưới 200k còn hàng?'),
    suggestions: (manager) => (manager ? [
      ['chart', t('So sánh doanh thu'), t('Tháng này và tháng trước'), t('So sánh doanh thu, lãi gộp tháng này với tháng trước')],
      ['truck', t('Cần nhập hàng gì?'), t('Sắp hết và đang bán chạy'), t('Sản phẩm nào sắp hết mà lại đang bán chạy, cần nhập thêm bao nhiêu?')],
      ['users', t('Khách hàng thân thiết'), t('Top chi tiêu 3 tháng'), t('Top 5 khách hàng chi tiêu nhiều nhất 3 tháng qua là ai?')],
      ['calendar', t('Giờ cao điểm'), t('Khung giờ, thứ bán đông'), t('Khung giờ nào và thứ mấy trong tuần bán được nhiều nhất?')],
    ] : [
      ['package', t('Tìm sản phẩm'), t('Theo nhu cầu, ngân sách'), t('Có tai nghe bluetooth nào dưới 500k còn hàng không?')],
      ['receipt', t('Hóa đơn của tôi'), t('Hôm nay bán được gì'), t('Hôm nay tôi đã lập bao nhiêu hóa đơn, tổng tiền bao nhiêu?')],
      ['help', t('Cách dùng phần mềm'), t('Đổi trả hàng'), t('Hướng dẫn tôi cách đổi trả hàng cho khách')],
      ['message', t('Viết tin nhắn'), t('Chăm sóc khách hàng'), t('Viết giúp tin nhắn Zalo ngắn cảm ơn khách vừa mua tai nghe')],
    ]),
    hint: t('AI có thể nhầm, hãy kiểm tra lại số liệu quan trọng trên các trang quản lý.'),
    body: (text) => ({ message: text }), maxLength: 1000,
  },
  advisor: {
    endpoint: '/ai/advisor', name: t('Trợ lý tư vấn'), cart: true, versions: true,
    greeting: t('Khách hàng đang cần gì?'),
    intro: t('Mô tả nhu cầu và ngân sách của khách. Trợ lý chỉ gợi ý sản phẩm còn hàng trong kho, kèm giá và số lượng tồn.'),
    placeholder: t('VD: laptop văn phòng dưới 20 triệu, pin lâu'),
    suggestions: () => [
      ['package', t('Laptop văn phòng'), t('Dưới 20 triệu'), t('Khách cần laptop làm văn phòng, ngân sách dưới 20 triệu')],
      ['message', t('Tai nghe dưới 500k'), t('Pin lâu, còn hàng'), t('Khách cần tai nghe dưới 500000 đồng, pin lâu')],
      ['sparkles', t('Điện thoại chụp ảnh đẹp'), t('Tầm trung'), t('Tư vấn điện thoại chụp ảnh đẹp tầm 8 đến 12 triệu')],
      ['tag', t('Quà tặng sinh viên'), t('Khoảng 300k'), t('Gợi ý quà tặng cho sinh viên tầm 300k')],
    ],
    hint: t('AI có thể nhầm, hãy kiểm tra lại giá và tồn kho trước khi báo khách.'),
    body: (text) => ({ message: text }), maxLength: 1000,
  },
  ask: {
    endpoint: '/ai/ask', name: t('Trợ lý dữ liệu'),
    greeting: t('Bạn muốn biết gì về tình hình kinh doanh?'),
    intro: t('Hỏi bằng tiếng Việt tự nhiên. AI chỉ đọc các view thống kê được phép, không thấy thông tin cá nhân của khách.'),
    placeholder: t('Hỏi về doanh thu, sản phẩm bán chạy, tồn kho...'),
    suggestions: () => [
      ['down', t('Mặt hàng bán chậm'), t('Tháng này'), t('Tháng này mặt hàng nào bán chậm?')],
      ['wallet', t('Doanh thu hôm nay'), t('So với mọi ngày'), t('Doanh thu hôm nay thế nào?')],
      ['up', t('Top bán chạy'), t('Tháng trước'), t('Top 5 sản phẩm bán chạy tháng trước?')],
      ['truck', t('Cần nhập thêm hàng'), t('Sản phẩm sắp hết'), t('Sản phẩm nào cần nhập thêm?')],
    ],
    hint: t('AI có thể nhầm, hãy đối chiếu với trang Báo cáo doanh thu khi cần số liệu chính xác.'),
    body: (text) => ({ question: text }), maxLength: 500,
  },
}

function historyGroup(dateStr) {
  const start = new Date(); start.setHours(0, 0, 0, 0)
  const d = new Date(dateStr); d.setHours(0, 0, 0, 0)
  const days = Math.round((start - d) / 86400000)
  if (days <= 0) return t('Hôm nay')
  if (days === 1) return t('Hôm qua')
  if (days < 7) return t('7 ngày qua')
  if (days < 30) return t('30 ngày qua')
  return t('Cũ hơn')
}

export const storeKey = (userId, kind) => `chat:${userId}:${kind}`
export const readStored = (k) => { try { return Number(localStorage.getItem(k)) || null } catch { return null } }
export const writeStored = (k, v) => { try { v ? localStorage.setItem(k, String(v)) : localStorage.removeItem(k) } catch { /* trình duyệt chặn lưu trữ */ } }

// Phần phụ của câu trả lời AI (gợi ý sản phẩm, công cụ đã tra, SQL...) lưu kèm tin nhắn để hiển thị lại
export const replyMeta = (res) => ({ suggestions: res.suggestions, removed: res.removed, tools: res.tools, model: res.model, source: res.source, version: res.version,
  warning: res.warning, latency_ms: res.latency_ms, period: res.period, period_label: res.period_label,
  sql: res.sql, columns: res.columns, rows: res.rows, row_count: res.row_count, truncated: res.truncated })

function ProductCard({ s, onCart }) {
  return (
    <div className="product-card">
      <div className="img"><Thumb url={s.image_url} name={t(s.name)} /></div>
      <div className="b">
        <div className="strong">{t(s.name)}</div>
        <div className="muted small">{s.code}{s.category ? ` · ${t(s.category)}` : ''}</div>
        <div className="tile-foot"><span className="price">{money(s.price)}</span><span className="badge green">{t('Còn {0}', [s.stock])}</span></div>
        {s.reason && <div className="reason">{s.reason}</div>}
        {onCart && <button className="btn sm block" onClick={() => onCart(s)}><Icon name="cart" />{t('Thêm vào giỏ')}</button>}
      </div>
    </div>
  )
}

// FR-AIQ-07: hiển thị bảng kết quả và câu SQL đã chạy để chủ cửa hàng kiểm chứng
function SqlResult({ meta }) {
  const [open, setOpen] = useState(false)
  const cols = meta.columns || []
  const rows = meta.rows || []
  const cell = (v) => (typeof v === 'number' ? v.toLocaleString(numLocale) : v ?? '')
  return (
    <div className="sql-result">
      {cols.length > 0 && (rows.length ? (
        <div className="table-wrap"><table>
          <thead><tr>{cols.map((c) => <th key={c}>{c.replace(/_/g, ' ')}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className={typeof v === 'number' ? 'right num' : ''}>{cell(v)}</td>)}</tr>)}</tbody>
        </table></div>
      ) : <div className="muted small">{t('Truy vấn không trả về dòng nào.')}</div>)}
      {(meta.row_count > rows.length || meta.truncated) && (
        <div className="muted small">{t('Hiển thị')} {rows.length} {t('dòng')}{meta.truncated ? t(', kết quả bị cắt ở 200 dòng') : t(' / {0} dòng', [meta.row_count])}.</div>)}
      <button type="button" className="link-btn small" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name="database" /> {open ? t('Ẩn câu SQL') : t('Xem câu SQL đã chạy')}</button>
      {open && <pre className="sql-code"><code>{meta.sql}</code></pre>}
    </div>
  )
}

export function AiTurn({ m, cfg, onCart, onCopy }) {
  const meta = m.meta || {}
  const time = m.created_at ? new Date(m.created_at).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' }) : ''
  return (
    <div className={`turn-ai ${m.error ? 'error' : ''}`}>
      <div className="ai-avatar"><Icon name="sparkles" /></div>
      <div className="body">
        <div className="who">{cfg.name}{' '}
          {meta.source === 'ai' ? <span className="badge dot cyan">Gemini</span> : meta.source ? <span className="badge dot yellow">{t('Dự phòng')}</span> : null}
          {meta.version && <span className="badge">Prompt {meta.version}</span>}</div>
        <Markdown className="content" text={m.content} />
        <div className="extra">
          {meta.tools?.length > 0 && <div className="turn-tools"><Icon name="search" />{t('Đã tra cứu:')} {meta.tools.map((tt) => <span key={tt.name}>{tt.label}</span>)}</div>}
          {meta.suggestions?.length > 0 && <div className="product-cards">{meta.suggestions.map((s) => <ProductCard key={s.code} s={s} onCart={cfg.cart ? onCart : null} />)}</div>}
          {meta.removed?.length > 0 && <div className="note"><Icon name="alert" /><span>{t('Đã bỏ')} {meta.removed.length} {t('gợi ý không hợp lệ (sai mã hoặc hết hàng).')}</span></div>}
          {meta.sql && <SqlResult meta={meta} />}
          {meta.period && <div className="turn-period"><Icon name="calendar" />{t('Kỳ dữ liệu:')} {meta.period_label} ({meta.period.from} → {meta.period.to})</div>}
          {meta.warning && <div className="note"><Icon name="alert" /><span>{meta.warning}</span></div>}
          {!m.error && (
            <div className="turn-actions">
              <button className="tool" onClick={() => onCopy(m.content)}><Icon name="copy" /> {t('Sao chép')}</button>
              {time && <><span className="sep">·</span>{time}</>}
              {meta.latency_ms ? <><span className="sep">·</span>{meta.latency_ms} ms</> : null}
              {meta.model && <><span className="sep">·</span>{meta.model}</>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function AIChat({ kind }) {
  const cfg = CFG[kind]
  const { user } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const key = storeKey(user.id, kind)
  const [session, setSession] = useState({ id: null, title: '', messages: [] })
  const [list, setList] = useState(null)
  const [search, setSearch] = useState('')
  const [text, setText] = useState('')
  const [pending, setPending] = useState(false)
  const [version, setVersion] = useState('')
  const [collapsed, setCollapsed] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [defaultVersion, setDefaultVersion] = useState('v3')
  const [rename, setRename] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const scroller = useRef(null)
  const input = useRef(null)

  const loadList = useCallback(async () => {
    try { setList(await api.get('/ai/sessions', { kind, q: search.trim() })) } catch { setList([]) }
  }, [kind, search])
  useEffect(() => { const tt = setTimeout(loadList, 250); return () => clearTimeout(tt) }, [loadList])

  // Mở lại cuộc trò chuyện đang dở khi tải lại trang
  useEffect(() => {
    const id = readStored(key)
    if (id) api.get(`/ai/sessions/${id}`).then((s) => setSession({ id: s.id, title: s.title, messages: s.messages })).catch(() => writeStored(key, null))
    if (cfg.versions) api.get('/ai/status').then((s) => setDefaultVersion(s.advisor_prompt_version)).catch(() => {})
    input.current?.focus()
  }, [key, cfg.versions])

  useEffect(() => { if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight }, [session.messages.length, pending])

  const open = async (id) => {
    if (pending) return
    try {
      const s = await api.get(`/ai/sessions/${id}`)
      setSession({ id: s.id, title: s.title, messages: s.messages }); writeStored(key, s.id); setShowHistory(false)
    } catch (e) { toast(e.message, 'error'); loadList() }
  }
  const newChat = () => {
    if (pending) return
    setSession({ id: null, title: '', messages: [] }); writeStored(key, null); setShowHistory(false); input.current?.focus()
  }

  const send = async (raw) => {
    const q = raw.trim()
    if (!q || pending) return
    setText('')
    setPending(true)
    setSession((s) => ({ ...s, messages: [...s.messages, { role: 'user', content: q, created_at: new Date().toISOString() }] }))
    try {
      const res = await api.post(cfg.endpoint, { ...cfg.body(q), session_id: session.id }, cfg.versions && version ? { version } : undefined)
      const meta = replyMeta(res)
      setSession((s) => ({ id: res.session_id, title: res.session_title,
        messages: [...s.messages, { id: res.message_id, role: 'assistant', content: res.answer, meta, created_at: new Date().toISOString() }] }))
      writeStored(key, res.session_id)
      loadList()
    } catch (e) {
      setSession((s) => ({ ...s, messages: [...s.messages, { role: 'assistant', content: e.message, error: true }] }))
    } finally {
      setPending(false)
      input.current?.focus()
    }
  }

  const copy = (tt) => navigator.clipboard?.writeText(tt).then(() => toast(t('Đã sao chép câu trả lời'), 'success'), () => toast(t('Trình duyệt không cho sao chép'), 'error'))
  const addToCart = (s) => navigate('/pos', { state: { addCode: s.code } })

  const doRename = async () => {
    const title = rename.title.trim()
    if (!title) return
    try {
      const r = await api.patch(`/ai/sessions/${rename.id}`, { title })
      if (rename.id === session.id) setSession((s) => ({ ...s, title: r.title }))
      setRename(null); loadList()
    } catch (e) { toast(e.message, 'error') }
  }

  const groups = []
  for (const s of list || []) {
    const g = historyGroup(s.updated_at)
    if (!groups.length || groups[groups.length - 1][0] !== g) groups.push([g, []])
    groups[groups.length - 1][1].push(s)
  }
  const toggleHistory = () => (matchMedia('(max-width: 860px)').matches ? setShowHistory(!showHistory) : setCollapsed(!collapsed))

  return (
    <div className={`ai-shell ${collapsed ? 'collapsed' : ''} ${showHistory ? 'show-history' : ''}`}>
      <aside className="ai-history">
        <div className="ai-history-top">
          <button className="btn primary block" onClick={newChat}><Icon name="plus" />{t('Cuộc trò chuyện mới')}</button>
          <div className="input-icon"><Icon name="search" /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('Tìm trong lịch sử')} aria-label={t('Tìm trong lịch sử')} /></div>
        </div>
        <div className="ai-history-list">
          {list && !list.length && <Empty icon={search ? 'search' : 'message'} title={search ? t('Không tìm thấy cuộc trò chuyện') : t('Chưa có lịch sử')} />}
          {groups.map(([g, items]) => (
            <div key={g}>
              <div className="ai-history-group">{g}</div>
              {items.map((s) => (
                <div key={s.id} className={`ai-history-item ${s.id === session.id ? 'active' : ''}`} title={s.title}
                  role="button" tabIndex={0} onClick={() => open(s.id)} onKeyDown={(e) => { if (e.key === 'Enter') open(s.id) }}>
                  <span className="t">{s.title}</span>
                  <span className="acts">
                    <button className="icon-tool" title={t('Đổi tên')} aria-label={t('Đổi tên')} onClick={(e) => { e.stopPropagation(); setRename({ id: s.id, title: s.title }) }}><Icon name="edit" /></button>
                    <button className="icon-tool del" title={t('Xóa')} aria-label={t('Xóa')} onClick={(e) => { e.stopPropagation(); setConfirm({ id: s.id }) }}><Icon name="trash" /></button>
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="ai-history-foot"><button className="btn ghost sm block" disabled={!list?.length} onClick={() => setConfirm({ all: true })}><Icon name="trash" />{t('Xóa toàn bộ lịch sử')}</button></div>
      </aside>

      <section className="ai-main">
        <div className="ai-head">
          <button className="btn ghost sm icon-only" onClick={toggleHistory} title={t('Ẩn/hiện lịch sử')} aria-label={t('Ẩn hoặc hiện lịch sử')}><Icon name="panel" /></button>
          <div className="title">{session.title || t('Cuộc trò chuyện mới')}</div>
          {cfg.cart && <button className="btn sm" onClick={() => navigate('/pos')}><Icon name="cart" />{t('Bán hàng')}</button>}
        </div>
        <div className="ai-scroll" ref={scroller}>
          <div className="ai-thread">
            {!session.messages.length ? (
              <div className="ai-welcome">
                <div className="ai-orb"><Icon name="sparkles" /></div>
                <div className="muted">{t('Xin chào,')} {user.full_name}</div>
                <h2>{cfg.greeting}</h2><p>{cfg.intro}</p>
                <div className="suggest-grid">{cfg.suggestions(user.role !== 'staff').map(([icon, tt, s, q]) => (
                  <button key={tt} className="suggest-item" onClick={() => send(q)}><Icon name={icon} /><span><div className="s1">{tt}</div><div className="s2">{s}</div></span></button>
                ))}</div>
              </div>
            ) : session.messages.map((m, i) => (m.role === 'user' ? (
              <div key={m.id || `u${i}`} className="turn-user"><div className="bubble">{m.content}</div><div className="avatar">{initialsOf(user.full_name)}</div></div>
            ) : <AiTurn key={m.id || `a${i}`} m={m} cfg={cfg} onCart={addToCart} onCopy={copy} />))}
            {pending && (
              <div className="turn-ai is-typing"><div className="ai-avatar"><Icon name="sparkles" /></div>
                <div className="body"><div className="who">{cfg.name}</div><div className="typing"><span /><span /><span /></div></div></div>
            )}
          </div>
        </div>
        <div className="ai-composer-wrap">
          <form className="ai-composer" onSubmit={(e) => { e.preventDefault(); send(text) }}>
            <textarea ref={input} rows={1} maxLength={cfg.maxLength} value={text} placeholder={cfg.placeholder} aria-label={t('Nội dung câu hỏi')}
              style={{ height: Math.min(200, 24 + 22 * (text.split('\n').length - 1)) }}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(text) } }} />
            <div className="row">
              {cfg.versions && (
                <select value={version} onChange={(e) => setVersion(e.target.value)} title={t('Phiên bản prompt')} aria-label={t('Phiên bản prompt')}>
                  <option value="">{t('Prompt mặc định (')}{defaultVersion})</option>
                  <option value="v1">Prompt v1</option><option value="v2">Prompt v2</option><option value="v3">Prompt v3</option>
                </select>
              )}
              <button className="send-btn" type="submit" title={t('Gửi (Enter)')} aria-label={t('Gửi')} disabled={pending || !text.trim()}><Icon name="arrow-up" /></button>
            </div>
          </form>
          <div className="ai-hint">{t('Enter để gửi · Shift + Enter để xuống dòng ·')} {cfg.hint}</div>
        </div>
      </section>

      {rename && (
        <Modal title={t('Đổi tên cuộc trò chuyện')} size="narrow" onClose={() => setRename(null)} footer={<>
          <button className="btn" onClick={() => setRename(null)}>{t('Hủy')}</button>
          <button className="btn primary" onClick={doRename} disabled={!rename.title.trim()}><Icon name="check" />{t('Lưu')}</button></>}>
          <input className="w-full" maxLength={120} value={rename.title} onChange={(e) => setRename({ ...rename, title: e.target.value })}
            onKeyDown={(e) => { if (e.key === 'Enter') doRename() }} />
        </Modal>
      )}
      {confirm && (
        <ConfirmDialog danger title={confirm.all ? t('Xóa toàn bộ lịch sử') : t('Xóa cuộc trò chuyện')} confirmText={t('Xóa')}
          message={confirm.all ? t('Xóa toàn bộ lịch sử của trang này? Không thể hoàn tác.') : t('Xóa cuộc trò chuyện này khỏi lịch sử?')}
          onClose={() => setConfirm(null)}
          onConfirm={async () => {
            try {
              if (confirm.all) {
                const r = await api.del('/ai/sessions', { kind }); newChat(); toast(t('Đã xóa {0} cuộc trò chuyện', [r.deleted]), 'success')
              } else {
                await api.del(`/ai/sessions/${confirm.id}`); if (confirm.id === session.id) newChat(); toast(t('Đã xóa cuộc trò chuyện'), 'success')
              }
              loadList()
            } catch (e) { toast(e.message, 'error') }
          }} />
      )}
    </div>
  )
}
