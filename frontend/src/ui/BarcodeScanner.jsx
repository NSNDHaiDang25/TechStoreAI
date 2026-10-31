// Quét mã vạch / QR bằng camera (cho cửa hàng không có máy quét). Ưu tiên bộ đọc mã có sẵn của trình duyệt
// (BarcodeDetector: Chrome Android, Safari / Chrome trên Mac); trình duyệt chưa có (Chrome trên Windows...) thì tải
// thư viện ZXing khi mở camera. Quét liên tục: mỗi mã đọc được gọi onCode(mã); cùng một mã chỉ nhận lại sau 2 giây.
// Trình duyệt chỉ cho mở camera trên HTTPS hoặc localhost.
import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { Modal } from './kit.jsx'
import { t } from '../i18n.js'

const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'code_93', 'itf', 'codabar', 'qr_code']
const SAME_CODE_MS = 2000

function cameraError(e) {
  if (!navigator.mediaDevices?.getUserMedia) return t('Trình duyệt không hỗ trợ camera hoặc trang không chạy trên HTTPS')
  if (e?.name === 'NotAllowedError') return t('Bạn chưa cho phép trang dùng camera')
  if (e?.name === 'NotFoundError' || e?.name === 'OverconstrainedError') return t('Không tìm thấy camera trên thiết bị')
  if (e?.name === 'NotReadableError') return t('Camera đang được ứng dụng khác sử dụng')
  return t('Không mở được camera')
}

// Tiếng "bíp" ngắn và rung nhẹ khi đọc được mã
function beep(ok) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = ok ? 1200 : 300
    gain.gain.value = 0.08
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + (ok ? 0.09 : 0.25))
    osc.onended = () => ctx.close()
  } catch { /* trình duyệt chặn âm thanh: bỏ qua */ }
  try { navigator.vibrate?.(ok ? 60 : [80, 60, 80]) } catch { /* không hỗ trợ rung */ }
}

// Bộ đọc: BarcodeDetector có sẵn nếu hỗ trợ các định dạng cần dùng, không thì ZXing
async function startReader(video, stream, onText) {
  if ('BarcodeDetector' in window) {
    try {
      const supported = await window.BarcodeDetector.getSupportedFormats()
      const formats = FORMATS.filter((f) => supported.includes(f))
      if (formats.includes('ean_13') && formats.includes('code_128')) {
        const detector = new window.BarcodeDetector({ formats })
        let alive = true
        const loop = async () => {
          if (!alive) return
          try {
            if (video.readyState >= 2) {
              const found = await detector.detect(video)
              if (found[0]?.rawValue) onText(found[0].rawValue)
            }
          } catch { /* khung hình lỗi: bỏ qua, đọc khung sau */ }
          if (alive) setTimeout(loop, 120)
        }
        loop()
        return () => { alive = false }
      }
    } catch { /* dùng ZXing bên dưới */ }
  }
  const { BrowserMultiFormatReader } = await import('@zxing/browser')
  const reader = new BrowserMultiFormatReader(undefined, { delayBetweenScanAttempts: 120, delayBetweenScanSuccess: 300 })
  const controls = await reader.decodeFromStream(stream, video, (result) => { if (result) onText(result.getText()) })
  return () => controls.stop()
}

export default function BarcodeScanner({ onCode, onClose }) {
  const video = useRef(null)
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [log, setLog] = useState([])  // [{ code, ok, text }] mới nhất trước
  const last = useRef({ code: '', at: 0 })
  const working = useRef(false)
  const handler = useRef(onCode)
  handler.current = onCode

  const handle = async (raw) => {
    const code = String(raw).trim()
    const now = Date.now()
    if (!code || working.current || (code === last.current.code && now - last.current.at < SAME_CODE_MS)) return
    last.current = { code, at: now }
    working.current = true
    setBusy(true)
    try {
      const text = await handler.current(code)
      beep(true)
      setLog((l) => [{ code, ok: true, text }, ...l].slice(0, 6))
    } catch (e) {
      beep(false)
      setLog((l) => [{ code, ok: false, text: e.message }, ...l].slice(0, 6))
    } finally {
      last.current = { code, at: Date.now() }
      working.current = false
      setBusy(false)
    }
  }

  useEffect(() => {  // mở camera sau (nếu có) một lần khi hiện, tắt khi đóng
    let stream
    let stop
    let alive = true
    const start = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('unsupported')
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false })
        if (!alive) { stream.getTracks().forEach((tr) => tr.stop()); return }
        video.current.srcObject = stream
        await video.current.play()
        setReady(true)
        stop = await startReader(video.current, stream, (text) => handle(text))
        if (!alive) stop?.()
      } catch (e) { if (alive) setError(cameraError(e)) }
    }
    start()
    return () => { alive = false; stop?.(); stream?.getTracks().forEach((tr) => tr.stop()) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Modal title={t('Quét mã bằng camera')} icon="scan" size="narrow" onClose={onClose}
      footer={<button className="btn primary" onClick={onClose}><Icon name="check" />{t('Xong')}</button>}>
      <div className={`scan-cam ${busy ? 'busy' : ''}`}>
        <video ref={video} playsInline muted aria-label={t('Hình ảnh camera')} />
        {!ready && !error && <div className="face-cam-msg"><Icon name="camera" />{t('Đang mở camera...')}</div>}
        {error && <div className="face-cam-msg error"><Icon name="camera" />{error}</div>}
        {ready && <div className="scan-cam-frame" aria-hidden="true"><span className="scan-cam-line" /></div>}
      </div>
      <p className="muted small scan-cam-hint">{t('Đưa mã vạch hoặc mã QR vào giữa khung, giữ yên khoảng 1 giây. Sản phẩm tự vào giỏ, có thể quét tiếp nhiều món rồi bấm Xong.')}</p>
      {log.length > 0 && (
        <ul className="scan-log-list" aria-live="polite">
          {log.map((x, i) => (
            <li key={`${x.code}-${i}`} className={x.ok ? 'ok' : 'bad'}>
              <Icon name={x.ok ? 'check' : 'alert'} /><span className="code">{x.code}</span><span className="text">{x.text}</span>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}
