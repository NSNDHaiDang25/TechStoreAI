// Nhập hàng nhanh khi sắp hết: chọn sản phẩm sắp hết, sửa số lượng / nhà cung cấp / giá rồi lập phiếu nhập trong một bước.
// Mỗi nhà cung cấp một phiếu. Nhân viên lập phiếu nháp; chủ cửa hàng có thể nhập kho ngay (trừ hàng quản lý serial).
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { money, num } from '../format.js'
import { t } from '../i18n.js'
import Icon from '../ui/Icon.jsx'
import { Empty, ErrorBox, Loading, Modal, MoneyInput, Thumb, useLoad, useToast } from '../ui/kit.jsx'

export default function QuickRestock({ onClose, onDone }) {
  const { user } = useAuth()
  const owner = user.role === 'owner'
  const toast = useToast()
  const { data, error } = useLoad(() => api.get('/purchase-orders/restock-suggestions'), [])
  const [rows, setRows] = useState(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  useEffect(() => {
    if (!data) return
    const fallback = data.suppliers[0]?.id || ''
    setRows(data.items.map((it) => ({ ...it, picked: it.suggested_qty > 0, quantity: it.suggested_qty || '',
      supplier_id: it.supplier_id || fallback, unit_cost: it.unit_cost ?? '' })))
  }, [data])

  const picked = (rows || []).filter((r) => r.picked)
  const orders = new Set(picked.map((r) => r.supplier_id)).size
  const total = picked.reduce((s, r) => s + (Number(r.quantity) || 0) * (Number(r.unit_cost) || 0), 0)
  const allPicked = rows?.length > 0 && picked.length === rows.length
  const upd = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
  const problem = useMemo(() => {
    if (!picked.length) return t('Chọn ít nhất một sản phẩm')
    if (picked.some((r) => !(Number(r.quantity) > 0))) return t('Nhập số lượng lớn hơn 0')
    if (picked.some((r) => !r.supplier_id)) return t('Chọn nhà cung cấp cho từng sản phẩm')
    return ''
  }, [picked])

  const submit = async (confirm) => {
    if (problem) { toast(problem, 'error'); return }
    if (confirm && picked.some((r) => !(Number(r.unit_cost) > 0))) { toast(t('Nhập giá nhập cho từng sản phẩm để nhập kho ngay'), 'error'); return }
    setBusy(true)
    try {
      const res = await api.post('/purchase-orders/quick-restock', { confirm, items: picked.map((r) => ({
        product_id: r.product_id, quantity: Number(r.quantity), supplier_id: Number(r.supplier_id),
        unit_cost: owner && Number(r.unit_cost) > 0 ? Number(r.unit_cost) : null })) })
      setResult(res.orders)
      toast(t('Đã tạo {0} phiếu nhập', [res.orders.length]), 'success')
      onDone?.()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }

  if (result) {
    return (
      <Modal title={t('Nhập hàng nhanh')} onClose={onClose} footer={<button className="btn primary" onClick={onClose}>{t('Xong')}</button>}>
        <div className="stack">
          {result.map((o) => (
            <div key={o.id} className="row">
              <span className="strong">{o.code}</span><span className="muted flex-1">{o.supplier} · {t('{0} sản phẩm', [o.item_count])}</span>
              {o.status === 'confirmed' ? <span className="badge green">{t('Đã nhập kho')}</span>
                : <span className="badge yellow">{t('Nháp')}</span>}
            </div>
          ))}
          {result.some((o) => o.status === 'draft') && (
            <p className="muted small m-0">{owner
              ? t('Phiếu nháp có hàng quản lý serial: mở phiếu ở trang Phiếu nhập để nhập serial rồi xác nhận nhập kho.')
              : t('Phiếu nháp chờ chủ cửa hàng điền giá nhập và xác nhận nhập kho.')}</p>
          )}
        </div>
      </Modal>
    )
  }

  return (
    <Modal title={t('Nhập hàng nhanh')} onClose={onClose} size="xwide" footer={<>
      {rows?.length > 0 && <span className="muted small flex-1">
        {t('Đã chọn {0} sản phẩm · {1} phiếu nhập', [picked.length, orders])}{owner && total > 0 ? ` · ${money(total)}` : ''}</span>}
      <button className="btn" onClick={onClose}>{t('Đóng')}</button>
      {rows?.length > 0 && <button className={`btn ${owner ? '' : 'primary'}`} disabled={busy || !!problem} onClick={() => submit(false)}><Icon name="file" />{t('Tạo phiếu nháp')}</button>}
      {owner && rows?.length > 0 && <button className="btn primary" disabled={busy || !!problem} onClick={() => submit(true)}><Icon name="truck" />{t('Tạo và nhập kho ngay')}</button>}
    </>}>
      <ErrorBox error={error} />
      {!rows ? (!error && <Loading />) : !rows.length ? <Empty icon="check" title={t('Không có sản phẩm sắp hết hàng')} /> : <>
        <p className="muted small mt-0">{t('Số lượng gợi ý đủ bán khoảng {0} ngày theo tốc độ bán gần đây (ít nhất gấp đôi mức tồn tối thiểu), đã trừ hàng đang chờ trong phiếu nháp. Mỗi nhà cung cấp được lập một phiếu.', [data.days])}</p>
        {!data.suppliers.length && <div className="note"><Icon name="alert" /><span>{t('Chưa có nhà cung cấp.')} <Link to="/suppliers" onClick={onClose}>{t('Thêm nhà cung cấp')}</Link></span></div>}
        <div className="table-wrap"><table>
          <thead><tr>
            <th><input type="checkbox" checked={allPicked} aria-label={t('Chọn tất cả')} onChange={(e) => setRows(rows.map((r) => ({ ...r, picked: e.target.checked })))} /></th>
            <th>{t('Sản phẩm')}</th><th className="right">{t('Tồn / tối thiểu')}</th><th className="right">{t('Bán 30 ngày')}</th>
            <th className="right">{t('Đang chờ nhập')}</th><th>{t('Số lượng nhập')}</th><th>{t('Nhà cung cấp')}</th>{owner && <th>{t('Giá nhập')}</th>}
          </tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={r.product_id} className={r.picked ? '' : 'muted'}>
              <td><input type="checkbox" checked={r.picked} aria-label={t('Chọn {0}', [t(r.name)])} onChange={(e) => upd(i, 'picked', e.target.checked)} /></td>
              <td><div className="cell-product"><Thumb url={r.image_url} name={t(r.name)} size="sm" /><div>
                <div className="strong">{t(r.name)}</div><div className="muted small">{r.code}{r.track_serial ? ' · serial' : ''}</div></div></div></td>
              <td className="right"><span className={`badge ${r.stock <= 0 ? 'red' : 'yellow'}`}>{r.stock}</span> <span className="muted">/ {r.min_stock}</span></td>
              <td className="right num">{num(r.sold_30d)}</td>
              <td className="right num">{r.pending_qty ? num(r.pending_qty) : '-'}</td>
              <td><input type="number" min="1" max="9999" value={r.quantity} style={{ width: 84 }} aria-label={t('Số lượng nhập')}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, quantity: e.target.value, picked: x.picked || !!e.target.value } : x)))} /></td>
              <td><select value={r.supplier_id} onChange={(e) => upd(i, 'supplier_id', e.target.value)} aria-label={t('Nhà cung cấp')} style={{ minWidth: 140, maxWidth: 190 }}>
                <option value="">{t('Chọn nhà cung cấp')}</option>{data.suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></td>
              {owner && <td><MoneyInput value={r.unit_cost} onChange={(v) => upd(i, 'unit_cost', v)} style={{ width: 110 }} aria-label={t("Giá nhập")} /></td>}
            </tr>
          ))}</tbody>
        </table></div>
      </>}
    </Modal>
  )
}
