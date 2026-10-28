// Biểu tượng logo (ảnh chữ PDL), đặt cạnh tên TechStoreAI.
// Bản gốc cho nền sáng, bản chữ trắng cho nền tối.
const LIGHT = '/static/img/logo-mark.png'
const DARK = '/static/img/logo-mark-dark.png'

export default function BrandLogo({ onDark = false }) {
  // Nền luôn tối (ảnh nền trang đăng nhập): chỉ dùng bản chữ trắng
  if (onDark) return <img className="brand-logo" src={DARK} alt="" aria-hidden="true" />
  // Còn lại tự đổi theo giao diện sáng / tối (xem .theme-light / .theme-dark trong base.css)
  return (
    <>
      <img className="brand-logo theme-light" src={LIGHT} alt="" aria-hidden="true" />
      <img className="brand-logo theme-dark" src={DARK} alt="" aria-hidden="true" />
    </>
  )
}
