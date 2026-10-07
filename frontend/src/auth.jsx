import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, getToken, setAuthHandlers, setToken } from './api.js'

const AuthCtx = createContext(null)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)

  const logoutLocal = useCallback(() => { setToken(null); setUser(null) }, [])

  const refresh = useCallback(async () => {
    if (!getToken()) { setUser(null); setReady(true); return }
    try { setUser(await api.get('/auth/me')) } catch { logoutLocal() }
    setReady(true)
  }, [logoutLocal])

  useEffect(() => {
    // FR-AUT-09: token hết hạn thì về màn hình đăng nhập (giỏ hàng nháp vẫn được lưu ở server)
    setAuthHandlers(logoutLocal, () => setUser((u) => (u ? { ...u, must_change_password: true } : u)))
    refresh()
  }, [refresh, logoutLocal])

  const login = async (username, password, remember) => {
    const r = await api.post('/auth/login', { username, password })
    setToken(r.access_token, remember)
    setUser(r.user)
    return r.user
  }
  // Nhận kết quả đăng nhập đã xác thực ở nơi khác (Face ID): lưu token và vào hệ thống
  const acceptLogin = (r, remember) => {
    setToken(r.access_token, remember)
    setUser(r.user)
  }
  const logout = async () => {
    try { await api.post('/auth/logout') } catch { /* token có thể đã hết hạn */ }
    logoutLocal()
  }
  const can = (...roles) => !!user && roles.includes(user.role)

  return <AuthCtx.Provider value={{ user, ready, login, acceptLogin, logout, refresh, can, setUser }}>{children}</AuthCtx.Provider>
}
