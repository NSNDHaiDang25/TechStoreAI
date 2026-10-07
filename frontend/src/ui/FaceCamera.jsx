// Webcam cho Face ID: hiện hình camera trước kèm khung oval, chụp một khung hình thành ảnh JPEG để gửi lên máy chủ.
// Trình duyệt chỉ cho mở camera trên HTTPS hoặc localhost.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { t } from '../i18n.js'

function cameraError(e) {
  if (!navigator.mediaDevices?.getUserMedia) return t('Trình duyệt không hỗ trợ camera hoặc trang không chạy trên HTTPS')
  if (e?.name === 'NotAllowedError') return t('Bạn chưa cho phép trang dùng camera')
  if (e?.name === 'NotFoundError' || e?.name === 'OverconstrainedError') return t('Không tìm thấy camera trên thiết bị')
  if (e?.name === 'NotReadableError') return t('Camera đang được ứng dụng khác sử dụng')
  return t('Không mở được camera')
}

const FaceCamera = forwardRef(function FaceCamera({ status, state = '', onReady }, ref) {
  const video = useRef(null)
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)
  const readyCb = useRef(onReady)
  readyCb.current = onReady

  useEffect(() => {  // mở camera một lần khi hiện, tắt khi đóng
    let stream
    let alive = true
    const start = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('unsupported')
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
        if (!alive) { stream.getTracks().forEach((tr) => tr.stop()); return }
        video.current.srcObject = stream
        await video.current.play()
        setReady(true)
        readyCb.current?.()
      } catch (e) { if (alive) setError(cameraError(e)) }
    }
    start()
    return () => { alive = false; stream?.getTracks().forEach((tr) => tr.stop()) }
  }, [])

  useImperativeHandle(ref, () => ({
    // Chụp khung hình hiện tại (không lật gương) thành JPEG
    capture: () => new Promise((resolve) => {
      const v = video.current
      if (!v || !v.videoWidth) { resolve(null); return }
      const canvas = document.createElement('canvas')
      canvas.width = v.videoWidth; canvas.height = v.videoHeight
      canvas.getContext('2d').drawImage(v, 0, 0)
      canvas.toBlob(resolve, 'image/jpeg', 0.9)
    }),
  }), [])

  return (
    <div className={`face-cam ${state}`}>
      <video ref={video} playsInline muted aria-label={t('Hình ảnh camera')} />
      {!ready && !error && <div className="face-cam-msg"><Icon name="camera" />{t('Đang mở camera...')}</div>}
      {error && <div className="face-cam-msg error"><Icon name="camera" />{error}</div>}
      {ready && <div className="face-cam-guide" aria-hidden="true" />}
      {ready && status && <div className="face-cam-status" role="status">{status}</div>}
    </div>
  )
})

export default FaceCamera
