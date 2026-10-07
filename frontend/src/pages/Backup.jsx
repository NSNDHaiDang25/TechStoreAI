// Sao lưu và khôi phục CSDL (FR-SYS-04), chỉ quản trị viên
import { useRef, useState } from 'react'
import { api, downloadPost } from '../api.js'
import { useAuth } from '../auth.jsx'
import Icon from '../ui/Icon.jsx'
import { ConfirmDialog, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

const stamp = () => {
  const d = new Date(); const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`
}

const ACCEPT = '.db,.sqlite,.sqlite3,application/vnd.sqlite3'
const sizeOf = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

// Ô chọn tệp: bấm để chọn hoặc kéo thả tệp vào, chọn xong hiện tên và dung lượng
function FileDrop({ file, onFile }) {
  const [over, setOver] = useState(false)
  const input = useRef(null)
  const pick = (f) => { onFile(f || null); if (!f && input.current) input.current.value = '' }
  return (
    <label className={`file-drop ${over ? 'over' : ''} ${file ? 'has-file' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]) }}>
      <input ref={input} type="file" accept={ACCEPT} onChange={(e) => pick(e.target.files?.[0])} />
      <span className="fd-icon"><Icon name={file ? 'database' : 'upload'} /></span>
      <span className="fd-text">
        {file ? <><span className="fd-name">{file.name}</span><span className="fd-hint">{sizeOf(file.size)} {t('· bấm để chọn tệp khác')}</span></>
          : <><span className="fd-name">{t('Chọn tệp sao lưu hoặc kéo thả vào đây')}</span><span className="fd-hint">{t('Tệp .db, .sqlite tải từ mục Sao lưu')}</span></>}
      </span>
      {file && <button type="button" className="icon-tool" title={t('Bỏ chọn tệp')} aria-label={t('Bỏ chọn tệp')}
        onClick={(e) => { e.preventDefault(); pick(null) }}><Icon name="x" /></button>}
    </label>
  )
}

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
        <FileDrop file={file} onFile={setFile} />
        <button className="btn danger mt-3" disabled={!file} onClick={() => setConfirm(true)}><Icon name="refresh" />{t('Khôi phục từ tệp')}</button>
      </div>
      {confirm && <ConfirmDialog danger title={t('Khôi phục dữ liệu')} confirmText={t('Ghi đè dữ liệu')}
        message={t('Toàn bộ dữ liệu hiện tại sẽ bị thay bằng nội dung tệp "{0}". Không thể hoàn tác. Nên tải bản sao lưu hiện tại trước.', [file?.name])}
        onClose={() => setConfirm(false)} onConfirm={restore} />}
    </div>
  )
}
