// Bảo hành theo serial (UC-32, UC-33, FR-WAR-01..08)
import { useState } from 'react'
import { api, openFile } from '../api.js'
import { TICKET_STATUS, fmtDate, fmtDateTime } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Badge, Empty, ErrorBox, Loading, Modal, Pager, useLoad, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

const WARRANTY_STATUS = {
  active: [t('Còn bảo hành'), 'green'], expired: [t('Hết hạn'), 'red'], void: [t('Không còn hiệu lực'), ''],
}

function ReceiveDialog({ w, onClose, onDone }) {
  const toast = useToast()
  const [issue, setIssue] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true)
    try {
      const tt = await api.post('/warranty-tickets', { warranty_id: w.id, issue_description: issue.trim() })
      toast(t('Đã tạo phiếu {0}', [tt.code]), 'success'); onDone(tt)
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  return (
    <Modal title={t('Tiếp nhận bảo hành')} onClose={onClose} footer={
      <button className="btn primary" disabled={busy || issue.trim().length < 5} onClick={submit}><Icon name="check" />{t('Tạo phiếu và in biên nhận')}</button>}>
      <div className="info-list">
        <div><span className="muted">{t('Sản phẩm')}</span><span className="strong">{t(w.product_name)}</span></div>
        <div><span className="muted">Serial / IMEI</span><span>{w.serial_no || t('Không theo serial')}</span></div>
        <div><span className="muted">{t('Khách hàng')}</span><span>{t(w.customer_name)}{w.customer_phone ? ` · ${w.customer_phone}` : ''}</span></div>
        <div><span className="muted">{t('Hạn bảo hành')}</span><span>{fmtDate(w.end_date)} {t('(còn {0} ngày)', [w.days_left])}</span></div>
      </div>
      <label>{t('Mô tả lỗi khách báo (bắt buộc)')}
        <textarea rows={4} value={issue} onChange={(e) => setIssue(e.target.value)} placeholder={t('VD: Máy không lên nguồn, màn hình sọc ngang')} /></label>
    </Modal>
  )
}

function TicketDialog({ id, onClose, onChanged }) {
  const toast = useToast()
  const { data: tt, error, reload } = useLoad(() => api.get(`/warranty-tickets/${id}`), [id])
  const [resolution, setResolution] = useState(null)
  const [busy, setBusy] = useState(false)
  if (error) return <Modal title={t('Phiếu bảo hành')} onClose={onClose}><ErrorBox error={error} /></Modal>
  if (!tt) return <Modal title={t('Phiếu bảo hành')} onClose={onClose}><Loading /></Modal>
  const res = resolution ?? (tt.resolution || '')
  const update = async (status) => {
    setBusy(true)
    try {
      await api.put(`/warranty-tickets/${tt.id}`, { status, resolution: res })
      toast(status ? t('Đã chuyển sang "{0}"', [TICKET_STATUS[status][0]]) : t('Đã lưu kết quả xử lý'), 'success')
      setResolution(null); reload(); onChanged()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  const needResult = (s) => ['done', 'rejected'].includes(s) && !res.trim()
  return (
    <Modal title={t('Phiếu {0}', [tt.code])} onClose={onClose} size="wide" footer={<>
      <button className="btn" onClick={() => openFile(`/warranty-tickets/${tt.id}/pdf`)}><Icon name="printer" />{t('In biên nhận')}</button>
      {tt.status !== 'returned' && <button className="btn" disabled={busy || res === (tt.resolution || '')} onClick={() => update(null)}><Icon name="save" />{t('Lưu kết quả')}</button>}
      {tt.next_statuses.map((s) => (
        <button key={s} className={`btn ${s === 'rejected' ? 'danger' : 'primary'}`} disabled={busy || needResult(s)}
          title={needResult(s) ? t('Nhập kết quả xử lý trước') : ''} onClick={() => update(s)}>{TICKET_STATUS[s][0]}</button>
      ))}
    </>}>
      <div className="row mb-4"><Badge map={TICKET_STATUS} value={tt.status} />
        <span className="muted small">{t('Tiếp nhận {0} bởi {1}', [fmtDateTime(tt.received_at), tt.received_by])}</span></div>
      <div className="info-list">
        <div><span className="muted">{t('Sản phẩm')}</span><span className="strong">{t(tt.product_name)}</span></div>
        <div><span className="muted">Serial / IMEI</span><span>{tt.serial_no || '-'}</span></div>
        <div><span className="muted">{t('Hóa đơn')}</span><span>{tt.invoice_code}</span></div>
        <div><span className="muted">{t('Khách hàng')}</span><span>{t(tt.customer_name)}{tt.customer_phone ? ` · ${tt.customer_phone}` : ''}</span></div>
        <div><span className="muted">{t('Hết hạn bảo hành')}</span><span>{fmtDate(tt.warranty_end)}</span></div>
        <div><span className="muted">{t('Email thông báo')}</span><span>{tt.customer_email || t('Khách chưa có email')}</span></div>
        {tt.completed_at && <div><span className="muted">{t('Xử lý xong')}</span><span>{fmtDateTime(tt.completed_at)}</span></div>}
        {tt.returned_at && <div><span className="muted">{t('Trả khách')}</span><span>{fmtDateTime(tt.returned_at)}</span></div>}
      </div>
      <label>{t('Lỗi khách báo')}<textarea rows={2} value={tt.issue_description} readOnly /></label>
      <label className="mt-3">{t('Kết quả xử lý')} {['received', 'in_repair', 'waiting_parts'].includes(tt.status) && <span className="muted small">{t('(bắt buộc trước khi hoàn tất hoặc từ chối)')}</span>}
        <textarea rows={3} value={res} disabled={tt.status === 'returned'} onChange={(e) => setResolution(e.target.value)}
          placeholder={t('VD: Thay màn hình mới, kiểm tra hoạt động bình thường')} /></label>
    </Modal>
  )
}

export default function Warranty() {
  const toast = useToast()
  const [q, setQ] = useState('')
  const [found, setFound] = useState(null)
  const [receive, setReceive] = useState(null)
  const [ticket, setTicket] = useState(null)
  const [filter, setFilter] = useState({ status: '', q: '', open_only: true })
  const [page, setPage] = useState(1)
  const list = useLoad(() => api.get('/warranty-tickets', { ...filter, open_only: filter.open_only || '', page, size: 20 }), [JSON.stringify(filter), page])

  const search = async (e) => {
    e.preventDefault()
    if (q.trim().length < 3) { toast(t('Nhập ít nhất 3 ký tự'), 'error'); return }
    try { setFound(await api.get('/warranties/lookup', { q: q.trim() })) } catch (err) { toast(err.message, 'error') }
  }
  const counts = list.data?.counts || {}
  return (
    <div className="stack">
      <div className="card">
        <div className="card-head"><h2><Icon name="search" />{t('Tra cứu bảo hành')}</h2></div>
        <form className="toolbar" onSubmit={search}>
          <label className="grow">{t('Serial / IMEI, số điện thoại khách hoặc mã hóa đơn')}
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('Quét serial hoặc nhập 0912345678 / HD-20261001-0001')} autoFocus /></label>
          <div className="actions"><button className="btn primary" type="submit"><Icon name="search" />{t('Tra cứu')}</button></div>
        </form>
        {found && (!found.length ? <Empty title={t('Không tìm thấy hồ sơ bảo hành')} /> : (
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Sản phẩm')}</th><th>Serial</th><th>{t('Khách')}</th><th>{t('Hóa đơn')}</th><th>{t('Thời hạn')}</th><th>{t('Trạng thái')}</th><th /></tr></thead>
            <tbody>{found.map((w) => (
              <tr key={w.id}>
                <td className="strong">{t(w.product_name)}<div className="muted small">{w.product_code}</div></td>
                <td>{w.serial_no || '-'}</td><td>{t(w.customer_name)}<div className="muted small">{w.customer_phone}</div></td><td>{w.invoice_code}</td>
                <td className="small">{fmtDate(w.start_date)} → {fmtDate(w.end_date)}{w.status === 'active' && <div className="muted">{t('Còn {0} ngày', [w.days_left])}</div>}</td>
                <td><Badge map={WARRANTY_STATUS} value={w.status} />{w.open_ticket && <div className="mt-2"><button className="link-btn small" onClick={() => setTicket(w.open_ticket.id)}>{t('Đang có phiếu')} {w.open_ticket.code}</button></div>}</td>
                <td className="right">{w.can_receive && <button className="btn sm primary" onClick={() => setReceive(w)}>{t('Tiếp nhận')}</button>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ))}
      </div>

      <div className="card">
        <div className="card-head"><h2><Icon name="wrench" />{t('Phiếu bảo hành')}</h2></div>
        <div className="chips">
          <button className={`chip ${filter.open_only && !filter.status ? 'active' : ''}`} onClick={() => { setPage(1); setFilter({ ...filter, status: '', open_only: true }) }}>{t('Chưa trả khách')}</button>
          {Object.entries(TICKET_STATUS).map(([k, [label]]) => (
            <button key={k} className={`chip ${filter.status === k ? 'active' : ''}`} onClick={() => { setPage(1); setFilter({ ...filter, status: k, open_only: false }) }}>
              {label}{counts[k] ? ` (${counts[k]})` : ''}</button>
          ))}
          <button className={`chip ${!filter.open_only && !filter.status ? 'active' : ''}`} onClick={() => { setPage(1); setFilter({ ...filter, status: '', open_only: false }) }}>{t('Tất cả')}</button>
        </div>
        <div className="toolbar"><label className="grow">{t('Tìm theo mã phiếu hoặc serial')}
          <input value={filter.q} onChange={(e) => { setPage(1); setFilter({ ...filter, q: e.target.value }) }} placeholder={t('BH-... hoặc serial')} /></label></div>
        <ErrorBox error={list.error} />
        {!list.data ? <Loading /> : !list.data.items.length ? <Empty icon="wrench" title={t('Không có phiếu bảo hành')} /> : <>
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Mã phiếu')}</th><th>{t('Sản phẩm')}</th><th>{t('Khách')}</th><th>{t('Lỗi')}</th><th>{t('Tiếp nhận')}</th><th>{t('Trạng thái')}</th><th /></tr></thead>
            <tbody>{list.data.items.map((tt) => (
              <tr key={tt.id} className="clickable" onClick={() => setTicket(tt.id)}>
                <td className="strong">{tt.code}</td><td>{t(tt.product_name)}<div className="muted small">{tt.serial_no}</div></td>
                <td>{t(tt.customer_name)}</td><td className="small">{tt.issue_description}</td><td className="small">{fmtDateTime(tt.received_at)}</td>
                <td><Badge map={TICKET_STATUS} value={tt.status} /></td>
                <td className="right"><button className="btn sm" title={t('In biên nhận')} onClick={(e) => { e.stopPropagation(); openFile(`/warranty-tickets/${tt.id}/pdf`) }}><Icon name="printer" /></button></td>
              </tr>
            ))}</tbody>
          </table></div>
          <Pager page={page} size={20} total={list.data.total} onPage={setPage} />
        </>}
      </div>

      {receive && <ReceiveDialog w={receive} onClose={() => setReceive(null)} onDone={(tt) => {
        setReceive(null); setFound(null); list.reload(); openFile(`/warranty-tickets/${tt.id}/pdf`)
      }} />}
      {ticket && <TicketDialog id={ticket} onClose={() => setTicket(null)} onChanged={list.reload} />}
    </div>
  )
}
