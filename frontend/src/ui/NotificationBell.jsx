// Chuông thông báo: việc cần chú ý theo vai trò (GET /api/notifications), làm mới mỗi phút và mỗi lần chuyển trang.
// "Đã đọc" lưu trên trình duyệt theo chữ ký số lượng + thời điểm + tên mẫu: có việc mới thì chuông sáng lại.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { PAY_VI, fmtDateTime, money } from '../format.js'
import { locale, t } from '../i18n.js'
import Icon from './Icon.jsx'

const TYPES = {
  payments: { icon: 'wallet', tone: 'green', to: '/invoices', title: t('Đơn hàng đã thanh toán'), detail: (n, i) => t('{0} đơn trong 24 giờ qua · tổng {1}', [n, money(i.amount)]) },
  low_stock: { icon: 'alert', tone: 'yellow', to: '/purchase-orders', state: { quickRestock: true }, title: t('Sản phẩm sắp hết hàng'), detail: (n) => t('{0} sản phẩm dưới mức tồn tối thiểu', [n]) },
  pending_payment: { icon: 'receipt', tone: 'yellow', to: '/invoices', title: t('Hóa đơn chờ thanh toán'), detail: (n) => t('{0} hóa đơn đang chờ khách chuyển khoản', [n]) },
  cancel_requests: { icon: 'alert', tone: 'red', to: '/invoices', title: t('Yêu cầu hủy hóa đơn'), detail: (n) => t('{0} yêu cầu đang chờ bạn duyệt', [n]) },
  warranty_open: { icon: 'wrench', tone: 'blue', to: '/warranty', title: t('Phiếu bảo hành đang xử lý'), detail: (n) => t('{0} phiếu chưa trả máy cho khách', [n]) },
  draft_receipts: { icon: 'truck', tone: 'blue', to: '/purchase-orders', title: t('Phiếu nhập nháp'), detail: (n) => t('{0} phiếu chưa xác nhận nhập kho', [n]) },
  pending_users: { icon: 'users', tone: 'yellow', to: '/users', title: t('Tài khoản chờ duyệt'), detail: (n) => t('{0} người tự đăng ký đang chờ duyệt', [n]) },
  locked_users: { icon: 'lock', tone: 'red', to: '/users', title: t('Tài khoản đang bị khóa'), detail: (n) => t('{0} tài khoản bị khóa do đăng nhập sai nhiều lần', [n]) },
  ai_errors: { icon: 'sparkles', tone: 'red', to: '/ai/logs', title: t('Lỗi gọi AI'), detail: (n) => t('{0} lượt gọi AI lỗi hoặc quá thời gian trong 24 giờ qua', [n]) },
}

const sig = (i) => `${i.count}|${i.latest_at || ''}|${i.names.join(',')}`
const readSeen = (k) => { try { return JSON.parse(localStorage.getItem(k)) || {} } catch { return {} } }
const writeSeen = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* trình duyệt chặn lưu trữ */ } }

export default function NotificationBell() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const loc = useLocation()
  const key = `notif-seen:${user.id}`
  const [items, setItems] = useState(null)
  const [seen, setSeen] = useState(() => readSeen(key))
  const [open, setOpen] = useState(false)
  const box = useRef(null)

  // Mới nhất lên đầu (thông báo không có thời điểm, như hàng sắp hết, xếp sau)
  const load = useCallback(() => api.get('/notifications').then((r) => setItems(r.items.filter((i) => TYPES[i.type])
    .sort((a, b) => String(b.latest_at || '').localeCompare(String(a.latest_at || ''))))).catch(() => {}), [])
  useEffect(() => { load() }, [load, loc.pathname])
  useEffect(() => { const id = setInterval(load, 60_000); return () => clearInterval(id) }, [load])

  // Bấm ra ngoài hoặc nhấn Esc thì đóng
  useEffect(() => {
    if (!open) return undefined
    const outside = (e) => { if (!box.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', esc) }
  }, [open])

  const isNew = (i) => seen[i.type] !== sig(i)
  const unread = (items || []).filter(isNew).length
  const mark = (list) => {
    const next = { ...seen }
    list.forEach((i) => { next[i.type] = sig(i) })
    setSeen(next); writeSeen(key, next)
  }
  const go = (i) => { mark([i]); setOpen(false); navigate(TYPES[i.type].to, { state: TYPES[i.type].state }) }

  return (
    <div className="notif" ref={box}>
      <button type="button" className="btn ghost icon-only notif-btn" aria-expanded={open} title={t('Thông báo')}
        aria-label={unread ? t('Thông báo ({0} mới)', [unread]) : t('Thông báo')} onClick={() => { setOpen(!open); if (!open) load() }}>
        <Icon name="bell" />{unread > 0 && <span className="notif-dot">{unread}</span>}
      </button>
      {open && (
        <div className="notif-panel" role="dialog" aria-label={t('Thông báo')}>
          <div className="notif-head">
            <strong>{t('Thông báo')}</strong>
            {unread > 0 && <button type="button" className="link-btn small" onClick={() => mark(items)}><Icon name="check" />{t('Đánh dấu đã đọc')}</button>}
          </div>
          <div className="notif-list">
            {!items ? <div className="notif-empty muted small">{t('Đang tải...')}</div> : !items.length ? (
              <div className="notif-empty"><span className="notif-icon green"><Icon name="check" /></span><div className="muted">{t('Không có việc cần chú ý')}</div></div>
            ) : items.map((i) => {
              const cfg = TYPES[i.type]
              return (
                <button key={i.type} type="button" className={`notif-item ${isNew(i) ? 'unread' : ''}`} onClick={() => go(i)}>
                  <span className={`notif-icon ${cfg.tone}`}><Icon name={cfg.icon} /></span>
                  <span className="notif-body">
                    <span className="notif-title">{cfg.title}</span>
                    <span className="notif-detail">{cfg.detail(i.count, i)}</span>
                    {i.details ? (
                      <span className="notif-lines">{i.details.map((d) => (
                        <span key={d.code}><b>{d.code}</b> · {money(d.total)} · {PAY_VI[d.method] || d.method} · {new Date(d.paid_at).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}</span>
                      ))}</span>
                    ) : i.names.length > 0 && <span className="notif-names">{i.names.join(' · ')}{i.count > i.names.length ? ' …' : ''}</span>}
                    {i.latest_at && !i.details && <span className="notif-time">{fmtDateTime(i.latest_at)}</span>}
                  </span>
                  {isNew(i) && <span className="notif-new" aria-label={t('Mới')} />}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
