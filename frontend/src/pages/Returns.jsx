// Đổi trả trong 24 giờ (UC-31)
import { useState } from 'react'
import { api, openFile } from '../api.js'
import { PAY_VI, daysAgo, fmtDateTime, money, num, today } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Empty, ErrorBox, Loading, Modal, Pager, useLoad, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

function hoursLeft(sec) { const h = Math.floor(sec / 3600); const m = Math.floor((sec % 3600) / 60); return t('{0} giờ {1} phút', [h, m]) }

function ReturnForm({ info, onClose, onDone }) {
  const toast = useToast()
  const [sel, setSel] = useState({})  // invoice_item_id -> {quantity, item_condition, serial_no}
  const [reason, setReason] = useState('')
  const [exchange, setExchange] = useState([])
  const [q, setQ] = useState('')
  const found = useLoad(() => (q.trim() ? api.get('/products', { q, size: 6, status: 'active', stock: 'in' }) : Promise.resolve(null)), [q])
  const lines = info.lines.filter((l) => l.returnable_qty > 0)
  const refund = Object.entries(sel).reduce((s, [id, v]) => {
    const l = info.lines.find((x) => x.invoice_item_id === Number(id))
    return s + Math.floor((l.net_total * v.quantity) / l.quantity)
  }, 0)
  const newTotal = exchange.reduce((s, x) => s + x.product.sale_price * x.quantity, 0)
  const submit = async () => {
    try {
      const r = await api.post('/returns', {
        invoice_id: info.invoice_id, reason,
        items: Object.entries(sel).map(([id, v]) => ({ invoice_item_id: Number(id), ...v })),
        exchange_items: exchange.map((x) => ({ product_id: x.product.id, quantity: x.quantity, serial_id: x.serial_id || null })),
      })
      toast(t('Đã tạo phiếu {0}, hoàn {1}', [r.code, money(r.refund_amount)]), 'success'); onDone(r)
    } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={t('Đổi trả hóa đơn {0}', [info.code])} onClose={onClose} size="wide" footer={
      <button className="btn primary" disabled={!Object.keys(sel).length || reason.trim().length < 5} onClick={submit}><Icon name="check" />{t('Xác nhận đổi trả')}</button>}>
      <p className="m-0">{t('Khách:')} <span className="strong">{t(info.customer_name)}</span> {t('· thanh toán')} {PAY_VI[info.payment_method]} {t('lúc')} {fmtDateTime(info.paid_at)} ·
        <span className="badge yellow">{t('Còn {0}', [hoursLeft(info.seconds_left)])}</span></p>
      <div className="table-wrap mt-3"><table>
        <thead><tr><th /><th>{t('Sản phẩm')}</th><th className="right">{t('Đã mua')}</th><th className="right">{t('Còn trả được')}</th><th>{t('Số lượng trả')}</th><th>{t('Tình trạng')}</th><th>Serial</th></tr></thead>
        <tbody>{lines.map((l) => {
          const v = sel[l.invoice_item_id]
          const toggle = (on) => setSel((s) => { const n = { ...s }; if (on) n[l.invoice_item_id] = { quantity: 1, item_condition: 'sellable', serial_no: l.serial_no || '' }; else delete n[l.invoice_item_id]; return n })
          const upd = (k, val) => setSel((s) => ({ ...s, [l.invoice_item_id]: { ...s[l.invoice_item_id], [k]: val } }))
          return (
            <tr key={l.invoice_item_id}>
              <td><input type="checkbox" checked={!!v} onChange={(e) => toggle(e.target.checked)} /></td>
              <td>{t(l.product_name)}<div className="muted small">{money(l.unit_refund)}{t('/sp sau giảm giá')}</div></td>
              <td className="right">{l.quantity}</td><td className="right">{l.returnable_qty}</td>
              <td>{v && <input value={v.quantity} style={{ width: 70 }} disabled={!!l.serial_no}
                onChange={(e) => upd('quantity', Math.min(l.returnable_qty, Number(e.target.value.replace(/\D/g, '')) || 1))} />}</td>
              <td>{v && <select value={v.item_condition} onChange={(e) => upd('item_condition', e.target.value)}>
                <option value="sellable">{t('Bán lại được (nhập kho)')}</option><option value="defective">{t('Hàng lỗi')}</option></select>}</td>
              <td>{v && l.serial_no && <input placeholder={t('Quét serial máy trả')} value={v.serial_no} onChange={(e) => upd('serial_no', e.target.value)} />}</td>
            </tr>
          )
        })}</tbody>
      </table></div>
      <label className="mt-3">{t('Lý do (bắt buộc)')}<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t('VD: Khách đổi ý, máy lỗi màn hình')} /></label>
      <h3 className="mt-3">{t('Đổi sang sản phẩm khác (không bắt buộc)')}</h3>
      <div className="combo"><input placeholder={t('Tìm sản phẩm đổi')} value={q} onChange={(e) => setQ(e.target.value)} />
        {q && found.data?.items?.length > 0 && <div className="combo-list">{found.data.items.filter((p) => !p.track_serial).map((p) => (
          <button key={p.id} className="combo-item" onClick={() => { setExchange((x) => [...x, { product: p, quantity: 1 }]); setQ('') }}>{t(p.name)} · {money(p.sale_price)}</button>))}</div>}
      </div>
      {exchange.map((x, i) => <div key={i} className="row mt-2"><span className="flex-1">{t(x.product.name)}</span><span className="num">{money(x.product.sale_price)}</span>
        <button className="btn ghost sm icon-only" onClick={() => setExchange((e) => e.filter((_, j) => j !== i))}><Icon name="x" /></button></div>)}
      <div className="totals-box">
        <div className="row strong"><span className="flex-1">{t('Tiền hoàn')}</span><span className="num">{money(refund)}</span></div>
        {exchange.length > 0 && <>
          <div className="row"><span className="flex-1 muted">{t('Hóa đơn đổi mới')}</span><span className="num">{money(newTotal)}</span></div>
          <div className="row strong text-lg"><span className="flex-1">{newTotal >= refund ? t('Khách trả thêm') : t('Trả lại khách')}</span><span className="num">{money(Math.abs(newTotal - refund))}</span></div>
        </>}
      </div>
    </Modal>
  )
}

export default function Returns() {
  const toast = useToast()
  const [q, setQ] = useState('')
  const [results, setResults] = useState(null)
  const [form, setForm] = useState(null)
  const [page, setPage] = useState(1)
  const [range, setRange] = useState({ date_from: daysAgo(29), date_to: today() })
  const list = useLoad(() => api.get('/returns', { ...range, page, size: 20 }), [JSON.stringify(range), page])
  const search = async (e) => {
    e.preventDefault()
    try { setResults(await api.get('/returns/lookup', { q })) } catch (err) { toast(err.message, 'error') }
  }
  return (
    <div className="stack">
      <div className="card">
        <div className="card-head"><h2><Icon name="search" />{t('Tra hóa đơn cần đổi trả')}</h2></div>
        <form className="toolbar" onSubmit={search}>
          <label className="grow">{t('Mã hóa đơn hoặc số điện thoại khách')}<input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('HD-20261001-0001 hoặc 0912345678')} /></label>
          <div className="actions"><button className="btn primary" type="submit"><Icon name="search" />{t('Tìm')}</button></div>
        </form>
        {results && (!results.length ? <Empty title={t('Không tìm thấy hóa đơn đã thanh toán')} /> : (
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Hóa đơn')}</th><th>{t('Khách')}</th><th>{t('Thanh toán lúc')}</th><th>{t('Hạn đổi trả')}</th><th /></tr></thead>
            <tbody>{results.map((r) => (
              <tr key={r.invoice_id}><td className="strong">{r.code}</td><td>{t(r.customer_name)}</td><td>{fmtDateTime(r.paid_at)}</td>
                <td>{r.eligible ? <span className="badge green">{t('Còn {0}', [hoursLeft(r.seconds_left)])}</span> : <span className="badge red" title={r.reason}>{r.reason}</span>}</td>
                <td className="right">{r.eligible && <button className="btn sm primary" onClick={() => setForm(r)}>{t('Đổi trả')}</button>}</td></tr>
            ))}</tbody>
          </table></div>
        ))}
      </div>
      <div className="card">
        <div className="card-head"><h2><Icon name="undo" />{t('Phiếu đổi trả')}</h2>
          <label>{t('Từ')}<input type="date" value={range.date_from} onChange={(e) => setRange({ ...range, date_from: e.target.value })} /></label>
          <label>{t('Đến')}<input type="date" value={range.date_to} onChange={(e) => setRange({ ...range, date_to: e.target.value })} /></label>
        </div>
        <ErrorBox error={list.error} />
        {!list.data ? <Loading /> : !list.data.items.length ? <Empty title={t('Chưa có phiếu đổi trả')} /> : <>
          <p className="muted small mt-0">{t('Tổng tiền hoàn:')} {money(list.data.refund_total)}</p>
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Mã phiếu')}</th><th>{t('Thời gian')}</th><th>{t('Hóa đơn gốc')}</th><th>{t('Khách')}</th><th>{t('Hàng trả')}</th><th className="right">{t('Tiền hoàn')}</th><th className="right">{t('Điểm trừ')}</th><th /></tr></thead>
            <tbody>{list.data.items.map((r) => (
              <tr key={r.id}><td className="strong">{r.code}{r.return_type === 'exchange' && <span className="badge blue">{t('Đổi hàng')}</span>}</td><td>{fmtDateTime(r.created_at)}</td>
                <td>{r.invoice_code}{r.new_invoice_code && <div className="muted small">{t('Đổi sang')} {r.new_invoice_code}</div>}</td><td>{t(r.customer_name)}</td>
                <td className="small">{r.items.map((i) => `${t(i.product_name)} x${i.quantity}${i.restock ? '' : t(' (lỗi)')}`).join(', ')}</td>
                <td className="right num strong">{money(r.refund_amount)}</td><td className="right">{num(r.points_reversed)}</td>
                <td><button className="btn sm" onClick={() => openFile(`/returns/${r.id}/pdf`)} title={t('In phiếu')}><Icon name="printer" /></button></td></tr>
            ))}</tbody>
          </table></div>
          <Pager page={page} size={20} total={list.data.total} onPage={setPage} />
        </>}
      </div>
      {form && <ReturnForm info={form} onClose={() => setForm(null)} onDone={(r) => { setForm(null); setResults(null); list.reload(); openFile(`/returns/${r.id}/pdf`) }} />}
    </div>
  )
}
