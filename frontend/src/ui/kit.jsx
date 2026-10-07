// Thành phần giao diện dùng chung: thông báo, hộp thoại, nhãn, phân trang, trạng thái rỗng
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { numLocale, t } from '../i18n.js'

// ---------------------------------------------------------------- Thông báo (toast)
const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((message, type = 'info') => {
    const id = Math.random()
    setItems((x) => [...x, { id, message, type }])
    setTimeout(() => setItems((x) => x.filter((tt) => tt.id !== id)), type === 'error' ? 6000 : 3500)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div id="toast-root" aria-live="polite">
        {items.map((tt) => (
          <div key={tt.id} className={`toast ${tt.type}`} role={tt.type === 'error' ? 'alert' : 'status'}>
            <Icon name={tt.type === 'error' ? 'alert' : tt.type === 'success' ? 'check' : 'sparkles'} />
            <span>{tt.message}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

// ---------------------------------------------------------------- Hộp thoại
export function Modal({ title, onClose, children, footer, size = '' }) {
  const ref = useRef(null)
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    document.addEventListener('keydown', onKey)
    ref.current?.querySelector('input, select, textarea, button.primary')?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div className={`modal ${size}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button className="btn ghost icon-only sm" onClick={onClose} aria-label={t('Đóng')}><Icon name="x" /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  )
}

export function ConfirmDialog({ title, message, confirmText = t('Xác nhận'), danger, reason, onConfirm, onClose }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const ok = !reason || text.trim().length >= 5
  const submit = async () => {
    setBusy(true)
    try { await onConfirm(text.trim()); onClose() } finally { setBusy(false) }
  }
  return (
    <Modal title={title} onClose={onClose} size="narrow" footer={<>
      <button className="btn" onClick={onClose}>{t('Đóng')}</button>
      <button className={`btn ${danger ? 'danger' : 'primary'}`} disabled={!ok || busy} onClick={submit}>{confirmText}</button>
    </>}>
      {message && <p className="m-0">{message}</p>}
      {reason && (
        <label className="mt-3">{reason}
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder={t('Tối thiểu 5 ký tự')} />
        </label>
      )}
    </Modal>
  )
}

// ---------------------------------------------------------------- Nhỏ
export function Badge({ map, value, children, color }) {
  const [label, c] = map ? (map[value] || [value, '']) : [children, color]
  return <span className={`badge ${c || ''}`}>{label}</span>
}

export function Empty({ icon = 'clipboard', title = t('Chưa có dữ liệu'), children }) {
  return (
    <div className="empty-state compact">
      <Icon name={icon} />
      <div className="strong">{title}</div>
      {children && <div className="muted small">{children}</div>}
    </div>
  )
}

export function Loading() {
  return <div className="loading"><span className="spinner" /> {t('Đang tải...')}</div>
}

export function Pager({ page, size, total, onPage }) {
  const pages = Math.max(1, Math.ceil((total || 0) / size))
  if (pages <= 1) return null
  return (
    <div className="pager">
      <span className="muted small">{t('Trang {0}/{1} · {2} dòng', [page, pages, total])}</span>
      <button className="btn sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>{t('Trước')}</button>
      <button className="btn sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>{t('Sau')}</button>
    </div>
  )
}

export function Thumb({ url, name, size = '' }) {
  if (url) return <img className={`thumb ${size}`} src={url} alt="" loading="lazy" />
  const code = [...String(name || '?')].reduce((a, c) => a + c.charCodeAt(0), 0) % 7
  return <span className={`thumb thumb-ph ph-${code} ${size}`}>{String(name || '?').trim().slice(0, 2).toUpperCase()}</span>
}

export function Field({ label, children, full, hint }) {
  return (
    <label className={full ? 'full' : ''}>
      {label}
      {children}
      {hint && <span className="muted small">{hint}</span>}
    </label>
  )
}

// Hook tải dữ liệu: data, loading, error, reload
export function useLoad(fn, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const fnRef = useRef(fn)
  fnRef.current = fn
  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await fnRef.current()
      setState({ data, loading: false, error: null })
    } catch (e) {
      setState({ data: null, loading: false, error: e.message })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { reload() }, [reload])
  return { ...state, reload, setData: (data) => setState((s) => ({ ...s, data })) }
}

export function ErrorBox({ error }) {
  if (!error) return null
  return <div className="error-state"><Icon name="alert" /> {error}</div>
}

// Ô nhập tiền: hiển thị dấu chấm phân cách hàng nghìn, giá trị trả về là số nguyên
export function MoneyInput({ value, onChange, ...rest }) {
  const shown = value === '' || value === null || value === undefined ? '' : Number(value).toLocaleString(numLocale)
  return (
    <input inputMode="numeric" value={shown} {...rest}
      onChange={(e) => { const d = e.target.value.replace(/\D/g, ''); onChange(d === '' ? '' : Number(d)) }} />
  )
}
