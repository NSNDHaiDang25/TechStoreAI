import { locale, numLocale, t } from './i18n.js'
export const money = (v) => (Number(v) || 0).toLocaleString(numLocale) + ' ₫'
export const num = (v) => (Number(v) || 0).toLocaleString(numLocale)
export const fmtDateTime = (s) => (s ? new Date(s).toLocaleString(locale, {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
}) : '')
export const fmtDate = (s) => (s ? new Date(s).toLocaleDateString(locale, { day: '2-digit', month: '2-digit', year: 'numeric' }) : '')
export const isoDate = (d) => { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 10) }
export const today = () => isoDate(new Date())
export const daysAgo = (n) => isoDate(Date.now() - n * 86400000)
export const initialsOf = (name) => String(name || '?').trim().split(/\s+/).slice(-2).map((w) => w[0]).join('').toUpperCase()
export const toLocalInput = (s) => (s ? String(s).slice(0, 16) : '')

export const ROLE_VI = { admin: t('Quản trị viên'), owner: t('Chủ cửa hàng'), staff: t('Nhân viên bán hàng') }
export const PAY_VI = { cash: t('Tiền mặt'), bank_transfer: t('Chuyển khoản'), card: t('Thẻ (POS)') }
export const INVOICE_STATUS = {
  draft: [t('Nháp'), ''], pending_payment: [t('Chờ thanh toán'), 'yellow'], paid: [t('Đã thanh toán'), 'green'],
  partially_returned: [t('Trả một phần'), 'cyan'], fully_returned: [t('Đã trả hết'), 'blue'], cancelled: [t('Đã hủy'), 'red'],
}
export const PO_STATUS = { draft: [t('Nháp'), 'yellow'], confirmed: [t('Đã nhập kho'), 'green'], cancelled: [t('Đã hủy'), 'red'] }
export const TICKET_STATUS = {
  received: [t('Đã tiếp nhận'), 'blue'], in_repair: [t('Đang sửa'), 'yellow'], waiting_parts: [t('Chờ linh kiện'), 'yellow'],
  done: [t('Đã sửa xong'), 'green'], rejected: [t('Từ chối'), 'red'], returned: [t('Đã trả khách'), ''],
}
export const SERIAL_STATUS = {
  in_stock: [t('Trong kho'), 'green'], sold: [t('Đã bán'), 'blue'], returned: [t('Khách trả'), 'cyan'],
  defective: [t('Lỗi'), 'red'], in_warranty: [t('Đang bảo hành'), 'yellow'],
}
export const MOVE_VI = {
  import: t('Nhập hàng'), import_cancel: t('Hủy phiếu nhập'), sale: t('Bán hàng'), cancel: t('Hủy hóa đơn'),
  edit: t('Sửa hóa đơn'), return: t('Khách trả hàng'), adjust: t('Điều chỉnh / kiểm kê'),
}
