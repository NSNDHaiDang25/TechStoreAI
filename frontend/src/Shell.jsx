import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { api } from './api.js'
import { useAuth } from './auth.jsx'
import { initialsOf, ROLE_VI } from './format.js'
import { NAV } from './nav.js'
import AIFab from './ui/AIFab.jsx'
import Icon from './ui/Icon.jsx'
import LangToggle from './ui/LangToggle.jsx'
import NotificationBell from './ui/NotificationBell.jsx'
import { t } from './i18n.js'

function ThemeToggle() {
  const [theme, setTheme] = useState(document.documentElement.getAttribute('data-theme') || 'light')
  const toggle = () => {
    const tt = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.setAttribute('data-theme', tt)
    try { localStorage.setItem('theme', tt) } catch { /* bỏ qua */ }
    setTheme(tt)
  }
  return (
    <button className="btn ghost icon-only theme-toggle" onClick={toggle} type="button"
      title={theme === 'dark' ? t('Giao diện sáng') : t('Giao diện tối')} aria-label={t('Đổi giao diện sáng tối')}>
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
    </button>
  )
}
export { ThemeToggle }

export default function Shell({ title, children }) {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const [ai, setAi] = useState(null)
  const [lowCount, setLowCount] = useState(0)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  useEffect(() => {
    if (user.role === 'admin') return
    api.get('/ai/status').then(setAi).catch(() => {})
    // FR-STK-02: cảnh báo sắp hết hàng trên thanh điều hướng
    api.get('/products', { stock: 'low', size: 1, status: 'active' }).then((r) => setLowCount(r.total)).catch(() => {})
  }, [user.role, loc.pathname])

  const aiBadge = ai && (!ai.switched_on ? [t('AI đang tắt'), 'red'] : ai.enabled ? [`AI: ${ai.model || t('tạm hết lượt')}`, 'cyan'] : [t('AI dự phòng'), 'yellow'])
  return (
    <div className="layout">
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand"><span className="brand-mark"><Icon name="store" /></span>TechStoreAI</div>
        <nav>
          {NAV.map((g) => {
            const items = g.items.filter((i) => i.roles.includes(user.role))
            if (!items.length) return null
            return (
              <div key={g.group}>
                <div className="group">{g.group}</div>
                {items.map((i) => (
                  <NavLink key={i.to} to={i.to} end={i.to === '/'}>
                    <Icon name={i.icon} />{i.label}
                    {i.to === '/inventory' && lowCount > 0 && <span className="nav-count" title={t('Sản phẩm sắp hết hàng')}>{lowCount}</span>}
                  </NavLink>
                ))}
              </div>
            )
          })}
        </nav>
      </aside>
      {open && <div className="sidebar-backdrop" style={{ display: 'block' }} onClick={() => setOpen(false)} />}
      <div className="main">
        <header className="topbar">
          <button className="icon-btn" id="menu-toggle" aria-label={t('Mở menu')} onClick={() => setOpen(!open)}><Icon name="menu" /></button>
          <h1>{title}</h1>
          <div className="spacer" />
          {aiBadge && <span id="ai-badge" className={`badge ${aiBadge[1]}`}>{aiBadge[0]}</span>}
          <LangToggle />
          <NotificationBell />
          <ThemeToggle />
          <div className="user-chip">
            <span className="avatar">{initialsOf(user.full_name)}</span>
            <span className="who"><span className="strong">{user.full_name}</span><br /><span className="muted small">{ROLE_VI[user.role]}</span></span>
          </div>
          <button className="btn ghost icon-only" title={t('Đăng xuất')} aria-label={t('Đăng xuất')} onClick={logout}><Icon name="logout" /></button>
        </header>
        <main id="page">{children}</main>
        {user.role !== 'admin' && <AIFab pageTitle={title} />}
      </div>
    </div>
  )
}
