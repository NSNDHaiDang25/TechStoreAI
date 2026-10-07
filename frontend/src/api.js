import { lang, t } from './i18n.js'
// Gọi API backend. Token lưu trong localStorage (hoặc sessionStorage khi không chọn "Ghi nhớ đăng nhập").
const KEY = 'token'

// Địa chỉ backend. Trống = cùng tên miền với giao diện (FastAPI phục vụ bản build).
// Bản GitHub Pages build với VITE_API_URL=https://<app>.onrender.com để gọi API ở Render.
export const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '')

// Đường dẫn do backend trả về (/static/img/..., /uploads/...) đổi thành địa chỉ đầy đủ của backend
export const apiUrl = (path) => (path && path.startsWith('/') ? API_BASE + path : path)

export function getToken() {
  try { return localStorage.getItem(KEY) || sessionStorage.getItem(KEY) } catch { return null }
}

export function setToken(token, remember = true) {
  try {
    localStorage.removeItem(KEY); sessionStorage.removeItem(KEY)
    if (token) (remember ? localStorage : sessionStorage).setItem(KEY, token)
  } catch { /* trình duyệt chặn lưu trữ: chỉ giữ trong phiên */ }
}

export class ApiError extends Error {
  constructor(status, message, data) { super(message); this.status = status; this.data = data }
}

let onUnauthorized = () => {}
let onMustChangePassword = () => {}
export function setAuthHandlers(unauth, mustChange) { onUnauthorized = unauth; onMustChangePassword = mustChange }

function errorMessage(data, status) {
  if (!data) return t('Lỗi {0}', [status])
  if (typeof data.detail === 'string') return data.detail
  if (Array.isArray(data.detail)) {
    // Lỗi kiểm tra dữ liệu của FastAPI: lấy câu tiếng Việt do backend đặt, bỏ tiền tố "Value error, "
    return data.detail.map((d) => String(d.msg || '').replace(/^Value error, /, '')).join('; ')
  }
  return t('Lỗi {0}', [status])
}

async function request(method, path, { params, body, form, raw } = {}) {
  let url = API_BASE + '/api' + path
  if (params) {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') q.append(k, v) })
    const s = q.toString()
    if (s) url += '?' + s
  }
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  headers['Accept-Language'] = lang  // AI trả lời theo ngôn ngữ giao diện
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const res = await fetch(url, { method, headers, body: payload })
  if (raw && res.ok) return res
  let data = null
  const text = await res.text()
  try { data = text ? JSON.parse(text) : null } catch { data = { detail: text } }
  if (!res.ok) {
    const message = errorMessage(data, res.status)
    if (res.status === 401 && path !== '/auth/login' && !path.startsWith('/auth/face-login')) onUnauthorized()
    if (res.status === 403 && message.includes('đổi mật khẩu')) onMustChangePassword()
    throw new ApiError(res.status, t(message), data)  // dịch thông báo lỗi quen thuộc của backend
  }
  return data
}

export const api = {
  get: (path, params) => request('GET', path, { params }),
  post: (path, body, params) => request('POST', path, { body, params }),
  put: (path, body) => request('PUT', path, { body }),
  patch: (path, body) => request('PATCH', path, { body }),
  del: (path, params) => request('DELETE', path, { params }),
  upload: (path, form) => request('POST', path, { form }),
  raw: (method, path, params) => request(method, path, { params, raw: true }),
}

// Mở PDF / tải file có kèm token: tải về dạng blob rồi mở tab mới hoặc lưu file
export async function openFile(path, params, filename) {
  const res = await api.raw('GET', path, params)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  if (filename) {
    const a = document.createElement('a')
    a.href = url; a.download = filename; a.click()
  } else {
    window.open(url, '_blank', 'noopener')
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export async function downloadPost(path, filename) {
  const res = await api.raw('POST', path)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
