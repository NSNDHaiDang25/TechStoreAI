import { t } from './i18n.js'
// Menu theo vai trò, khớp ma trận phân quyền SRS bảng 4.2 (backend vẫn kiểm tra quyền ở từng API)
export const NAV = [
  { group: t('Bán hàng'), items: [
    { to: '/', label: t('Tổng quan'), icon: 'dashboard', roles: ['owner'] },
    { to: '/pos', label: t('Bán hàng'), icon: 'cart', roles: ['owner', 'staff'] },
    { to: '/invoices', label: t('Hóa đơn@@menu'), icon: 'receipt', roles: ['owner', 'staff'] },
    { to: '/returns', label: t('Đổi trả'), icon: 'undo', roles: ['owner', 'staff'] },
    { to: '/warranty', label: t('Bảo hành'), icon: 'wrench', roles: ['owner', 'staff'] },
  ] },
  { group: t('Danh mục'), items: [
    { to: '/customers', label: t('Khách hàng@@menu'), icon: 'users', roles: ['owner', 'staff'] },
    { to: '/products', label: t('Sản phẩm@@menu'), icon: 'package', roles: ['owner', 'staff'] },
    { to: '/promotions', label: t('Khuyến mãi'), icon: 'percent', roles: ['owner', 'staff'] },
  ] },
  { group: t('Kho'), items: [
    { to: '/purchase-orders', label: t('Phiếu nhập'), icon: 'truck', roles: ['owner', 'staff'] },
    { to: '/suppliers', label: t('Nhà cung cấp@@menu'), icon: 'building', roles: ['owner', 'staff'] },
    { to: '/inventory', label: t('Tồn kho'), icon: 'arrows', roles: ['owner', 'staff'] },
  ] },
  { group: t('Báo cáo'), items: [
    { to: '/reports', label: t('Doanh thu'), icon: 'chart', roles: ['owner'] },
  ] },
  { group: t('Trợ lý AI'), items: [
    { to: '/ai/assistant', label: t('Trợ lý đa năng'), icon: 'sparkles', roles: ['owner', 'staff'] },
    { to: '/ai/advisor', label: t('Tư vấn sản phẩm'), icon: 'message', roles: ['owner', 'staff'] },
    { to: '/ai/report', label: t('AI báo cáo'), icon: 'file', roles: ['owner'] },
    { to: '/ai/ask', label: t('Hỏi đáp dữ liệu'), icon: 'help', roles: ['owner'] },
    { to: '/ai/logs', label: t('Nhật ký AI'), icon: 'history', roles: ['owner', 'admin', 'staff'] },
    { to: '/ai/conversations', label: t('Lịch sử hội thoại'), icon: 'message', roles: ['admin'] },
  ] },
  { group: t('Hệ thống'), items: [
    { to: '/users', label: t('Người dùng'), icon: 'shield', roles: ['admin'] },
    { to: '/settings', label: t('Cấu hình'), icon: 'settings', roles: ['owner', 'admin'] },
    { to: '/audit', label: t('Nhật ký thao tác'), icon: 'clipboard', roles: ['owner', 'admin'] },
    { to: '/system', label: t('Sao lưu dữ liệu'), icon: 'database', roles: ['admin'] },
    { to: '/account', label: t('Tài khoản của tôi'), icon: 'key', roles: ['owner', 'staff', 'admin'] },
  ] },
]

export const homeFor = (role) => (role === 'owner' ? '/' : role === 'admin' ? '/users' : '/pos')
