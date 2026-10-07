// Đa ngôn ngữ Việt / Anh. Chuỗi tiếng Việt trong mã là khóa tra từ điển (locales/en.js); thiếu bản dịch thì giữ tiếng Việt.
// Đổi ngôn ngữ thì tải lại trang, nhờ vậy cả các hằng số khai báo ngoài component (menu, nhãn trạng thái...) cũng đổi theo.
import { useEffect, useState } from 'react'
import en from './locales/en.js'

const KEY = 'lang'
const read = () => { try { return localStorage.getItem(KEY) === 'en' ? 'en' : 'vi' } catch { return 'vi' } }

export const lang = read()
export const locale = lang === 'en' ? 'en-GB' : 'vi-VN'     // ngày giờ: dd/mm/yyyy ở cả hai ngôn ngữ
export const numLocale = lang === 'en' ? 'en-US' : 'vi-VN'  // số: 1,590,000 / 1.590.000
document.documentElement.lang = lang

// Tên tiếng Anh của sản phẩm, nhóm hàng (dữ liệu, không nằm trong từ điển): tải từ /api/catalog/names,
// lưu trên trình duyệt để lần mở trang sau hiển thị ngay
const NAMES_KEY = 'names-en'
let names = {}
if (lang === 'en') { try { names = JSON.parse(localStorage.getItem(NAMES_KEY)) || {} } catch { names = {} } }

// t('Còn {0}', [5]) hoặc t('Xin chào, {name}', { name }): chèn giá trị vào chỗ {…} sau khi dịch.
// t(p.name): tên sản phẩm / nhóm hàng có tên tiếng Anh thì đổi, không có thì giữ nguyên.
// t('Sản phẩm@@menu'): cùng chữ tiếng Việt nhưng dịch khác theo ngữ cảnh (menu "Products", cột bảng "Product")
const CONTEXT = '@@'
const plain = (s) => (typeof s === 'string' && s.includes(CONTEXT) ? s.slice(0, s.indexOf(CONTEXT)) : s)

export function t(text, vars) {
  let out = plain(text)
  if (lang === 'en') out = Object.hasOwn(en, text) ? en[text] : Object.hasOwn(names, text) ? names[text] : out
  if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (vars[k] ?? m))
  return out
}

export function setLang(next) {
  if (next === lang) return
  try { localStorage.setItem(KEY, next) } catch { /* trình duyệt chặn lưu trữ: không đổi được */ }
  location.reload()
}

// Gọi ở gốc ứng dụng sau khi đăng nhập: cập nhật bảng tên tiếng Anh rồi vẽ lại giao diện nếu có thay đổi
export function useEnglishNames(userId, fetchNames) {
  const [, redraw] = useState(0)
  useEffect(() => {
    if (lang !== 'en' || !userId) return undefined
    let alive = true
    fetchNames().then((map) => {
      if (!alive || JSON.stringify(map) === JSON.stringify(names)) return
      names = map
      try { localStorage.setItem(NAMES_KEY, JSON.stringify(map)) } catch { /* trình duyệt chặn lưu trữ */ }
      redraw((n) => n + 1)
    }).catch(() => {})
    return () => { alive = false }
  }, [userId, fetchNames])
}
