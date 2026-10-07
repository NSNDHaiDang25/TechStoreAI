// Lịch sử hội thoại AI của mọi người dùng, dành cho quản trị viên: chỉ xem, không chat, không đổi tên, không xóa.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDateTime, initialsOf } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Empty, Loading, useToast } from '../ui/kit.jsx'
import { AiTurn, CFG } from './AIChat.jsx'
import { t } from '../i18n.js'

const KIND = { assistant: t('Trợ lý đa năng'), advisor: t('Tư vấn sản phẩm'), ask: t('Hỏi đáp dữ liệu') }
const ROLE = { owner: t('Chủ cửa hàng'), staff: t('Nhân viên'), admin: t('Quản trị viên') }
const SIZE = 30

export default function AIConversations() {
  const toast = useToast()
  const [f, setF] = useState({ kind: '', user_id: '', q: '' })
  const [list, setList] = useState(null)
  const [page, setPage] = useState(1)
  const [users, setUsers] = useState([])
  const [session, setSession] = useState(null)
  const [opening, setOpening] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => { api.get('/users').then(setUsers).catch(() => {}) }, [])

  const load = useCallback(async (p) => {
    try {
      const res = await api.get('/ai/conversations', { kind: f.kind, user_id: f.user_id, q: f.q.trim(), page: p, size: SIZE })
      setList((old) => (p === 1 ? res : { total: res.total, items: [...(old?.items || []), ...res.items] }))
      setPage(p)
    } catch (e) { toast(e.message, 'error'); setList({ total: 0, items: [] }) }
  }, [f.kind, f.user_id, f.q, toast])
  useEffect(() => { const tt = setTimeout(() => load(1), 250); return () => clearTimeout(tt) }, [load])

  const open = async (id) => {
    setOpening(true)
    try { setSession(await api.get(`/ai/conversations/${id}`)); setShowHistory(false) } catch (e) { toast(e.message, 'error') } finally { setOpening(false) }
  }
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const copy = (tt) => navigator.clipboard?.writeText(tt).then(() => toast(t('Đã sao chép câu trả lời'), 'success'), () => toast(t('Trình duyệt không cho sao chép'), 'error'))
  const cfg = session ? { ...CFG[session.kind], cart: false } : null
  const toggleHistory = () => (matchMedia('(max-width: 860px)').matches ? setShowHistory(!showHistory) : setCollapsed(!collapsed))

  return (
    <div className={`ai-shell ${collapsed ? 'collapsed' : ''} ${showHistory ? 'show-history' : ''}`}>
      <aside className="ai-history">
        <div className="ai-history-top">
          <div className="input-icon"><Icon name="search" /><input value={f.q} onChange={set('q')} placeholder={t('Tìm theo tiêu đề, nội dung')} aria-label={t('Tìm hội thoại')} /></div>
          <select value={f.kind} onChange={set('kind')} aria-label={t('Tính năng')}>
            <option value="">{t('Mọi tính năng')}</option>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={f.user_id} onChange={set('user_id')} aria-label={t('Người dùng')}>
            <option value="">{t('Mọi người dùng')}</option>
            {users.filter((u) => u.role !== 'admin').map((u) => <option key={u.id} value={u.id}>{u.full_name} ({ROLE[u.role] || u.role})</option>)}
          </select>
        </div>
        <div className="ai-history-list">
          {!list ? <Loading /> : !list.items.length && <Empty icon="message" title={t('Không có cuộc trò chuyện nào')} />}
          {list?.items.map((s) => (
            <div key={s.id} className={`ai-history-item two-line ${s.id === session?.id ? 'active' : ''}`} title={s.title}
              role="button" tabIndex={0} onClick={() => open(s.id)} onKeyDown={(e) => { if (e.key === 'Enter') open(s.id) }}>
              <span className="t">{s.title}
                <span className="sub">{s.user_name} · {KIND[s.kind] || s.kind} · {t('{0} tin', [s.message_count])} · {fmtDateTime(s.updated_at)}</span></span>
            </div>
          ))}
          {list && list.items.length < list.total && (
            <button className="btn ghost sm block" onClick={() => load(page + 1)}>{t('Xem thêm (')}{list.total - list.items.length})</button>
          )}
        </div>
        <div className="ai-history-foot muted small">{list ? t('{0} cuộc trò chuyện', [list.total]) : ''} {t('· chỉ xem')}</div>
      </aside>

      <section className="ai-main">
        <div className="ai-head">
          <button className="btn ghost sm icon-only" onClick={toggleHistory} title={t('Ẩn/hiện danh sách')} aria-label={t('Ẩn hoặc hiện danh sách')}><Icon name="panel" /></button>
          <div className="title">{session ? session.title : t('Lịch sử hội thoại AI')}</div>
          {session && <span className="muted small">{session.user_name} ({ROLE[session.user_role] || session.user_role}) · {KIND[session.kind]}</span>}
        </div>
        <div className="ai-scroll">
          <div className="ai-thread">
            {opening ? <Loading /> : !session ? (
              <div className="ai-welcome">
                <div className="ai-orb"><Icon name="history" /></div>
                <h2>{t('Chọn một cuộc trò chuyện')}</h2>
                <p>{t('Xem lại nội dung người dùng đã trao đổi với trợ lý AI. Quản trị viên chỉ xem, không gửi tin, sửa hay xóa hội thoại.')}</p>
              </div>
            ) : session.messages.map((m) => (m.role === 'user' ? (
              <div key={m.id} className="turn-user"><div className="bubble">{m.content}</div><div className="avatar" title={session.user_name}>{initialsOf(session.user_name || '?')}</div></div>
            ) : <AiTurn key={m.id} m={m} cfg={cfg} onCart={null} onCopy={copy} />))}
          </div>
        </div>
      </section>
    </div>
  )
}
