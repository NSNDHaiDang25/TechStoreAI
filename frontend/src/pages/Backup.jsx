// Sao lưu và khôi phục CSDL (FR-SYS-04), chỉ quản trị viên
import { useState } from 'react'
import { api, downloadPost } from '../api.js'
import { useAuth } from '../auth.jsx'
import Icon from '../ui/Icon.jsx'
import { ConfirmDialog, FileDrop, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

const stamp = () => {
  const d = new Date(); const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`
}

const ACCEPT = '.db,.sqlite,.sqlite3,application/vnd.sqlite3'

export default function Backup() {
  const toast = useToast()
  const { logout } = useAuth()
  const [busy, setBusy] = useState(false)
  const [file, setFile] = useState(null)
  const [confirm, setConfirm] = useState(false)

  const backup = async () => {
    setBusy(true)
    try { await downloadPost('/admin/backup', `techstoreai-backup-${stamp()}.db`); toast(t('Đã tải bản sao lưu'), 'success') } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  const restore = async () => {
    const form = new FormData()
    form.append('file', file)
    try {
      const r = await api.upload('/admin/restore', form)
      toast(r.message, 'success')
      setTimeout(logout, 1500)  // dữ liệu tài khoản có thể đã đổi: đăng nhập lại
    } catch (e) { toast(e.message, 'error'); throw e }
  }
  return (
    <div className="grid two w-lg">
      <div className="card">
        <div className="card-head"><h2><Icon name="download" />{t('Sao lưu')}</h2></div>
        <p className="mt-0">{t('Tải về bản sao toàn bộ CSDL SQLite (sản phẩm, hóa đơn, khách hàng, nhật ký...). Bản sao nhất quán ngay cả khi đang có người bán hàng.')}</p>
        <p className="muted small">{t('Nên sao lưu hằng ngày và cất ở nơi khác máy chủ. Tệp chứa dữ liệu khách hàng, cần bảo quản cẩn thận.')}</p>
        <button className="btn primary" disabled={busy} onClick={backup}><Icon name="database" />{busy ? t('Đang tạo bản sao...') : t('Tải bản sao lưu')}</button>
      </div>
      <div className="card">
        <div className="card-head"><h2><Icon name="upload" />{t('Khôi phục')}</h2></div>
        <p className="mt-0">{t('Ghi đè toàn bộ dữ liệu hiện tại bằng tệp sao lưu. Hệ thống kiểm tra tệp đúng định dạng và không hỏng trước khi ghi.')}</p>
        <FileDrop file={file} onFile={setFile} accept={ACCEPT} fileIcon="database"
          title={t('Chọn tệp sao lưu hoặc kéo thả vào đây')} hint={t('Tệp .db, .sqlite tải từ mục Sao lưu')} />
        <button className="btn danger mt-3" disabled={!file} onClick={() => setConfirm(true)}><Icon name="refresh" />{t('Khôi phục từ tệp')}</button>
      </div>
      {confirm && <ConfirmDialog danger title={t('Khôi phục dữ liệu')} confirmText={t('Ghi đè dữ liệu')}
        message={t('Toàn bộ dữ liệu hiện tại sẽ bị thay bằng nội dung tệp "{0}". Không thể hoàn tác. Nên tải bản sao lưu hiện tại trước.', [file?.name])}
        onClose={() => setConfirm(false)} onConfirm={restore} />}
    </div>
  )
}
