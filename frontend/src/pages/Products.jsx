// Sản phẩm, nhóm hàng, serial (UC-10 đến UC-13)
import { useState } from 'react'
import { ApiError, api, openFile } from '../api.js'
import { useAuth } from '../auth.jsx'
import { SERIAL_STATUS, fmtDateTime, money, num } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Badge, Empty, ErrorBox, Field, Loading, Modal, MoneyInput, Pager, Thumb, useLoad, useToast } from '../ui/kit.jsx'
import { t } from '../i18n.js'

const STATUS = { active: [t('Đang bán'), 'green'], inactive: [t('Tạm ngừng'), 'yellow'], discontinued: [t('Ngừng kinh doanh'), 'red'] }
const STOCK = { in: [t('Còn hàng'), 'green'], low: [t('Sắp hết'), 'yellow'], out: [t('Hết hàng'), 'red'] }

function ProductForm({ initial, cats, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState(initial ? { ...initial } : {
    code: '', barcode: '', name: '', name_en: '', category_id: cats[0]?.id || '', brand: '', sale_price: '', cost_price: '',
    vat_rate: '', warranty_months: '', track_serial: false, stock: 0, min_stock: 5, description: '', status: 'active',
  })
  const [file, setFile] = useState(null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const save = async () => {
    const body = {
      ...f, category_id: f.category_id ? Number(f.category_id) : null, barcode: f.barcode || null, name_en: f.name_en || null,
      sale_price: Number(f.sale_price) || 0, cost_price: Number(f.cost_price) || 0, min_stock: Number(f.min_stock) || 0,
      vat_rate: f.vat_rate === '' ? null : Number(f.vat_rate), warranty_months: f.warranty_months === '' ? null : Number(f.warranty_months),
    }
    delete body.stock_state; delete body.category_name; delete body.image_url; delete body.id
    if (initial) delete body.stock
    else body.stock = Number(f.stock) || 0
    try {
      let p = initial ? await api.put(`/products/${initial.id}`, body) : await api.post('/products', body)
      if (file) { const fd = new FormData(); fd.append('file', file); p = await api.upload(`/products/${p.id}/image`, fd) }
      toast(t('Đã lưu sản phẩm'), 'success'); onSaved(p)
    } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={initial ? t('Sửa {0}', [initial.code]) : t('Thêm sản phẩm')} onClose={onClose} size="wide" footer={<button className="btn primary" onClick={save}>{t('Lưu')}</button>}>
      <div className="form-grid">
        <Field label="SKU"><input value={f.code} onChange={set('code')} placeholder="VD: LT-ASU-01" /></Field>
        <Field label={t('Mã vạch (8-14 số)')}><input value={f.barcode || ''} onChange={set('barcode')} /></Field>
        <Field label={t('Tên sản phẩm')} full><input value={f.name} onChange={set('name')} /></Field>
        <Field label={t('Tên tiếng Anh (không bắt buộc)')} full hint={t('Hiển thị khi chọn giao diện tiếng Anh')}><input value={f.name_en || ''} onChange={set('name_en')} placeholder="Asus Vivobook 15 Laptop" /></Field>
        <Field label={t('Nhóm hàng')}><select value={f.category_id || ''} onChange={set('category_id')}>
          <option value="">{t('Chưa phân nhóm')}</option>{cats.map((c) => <option key={c.id} value={c.id}>{t(c.name)}</option>)}</select></Field>
        <Field label={t('Hãng')}><input value={f.brand || ''} onChange={set('brand')} /></Field>
        <Field label={t('Giá bán (đã gồm VAT)')}><MoneyInput value={f.sale_price} onChange={(v) => setF({ ...f, sale_price: v })} /></Field>
        <Field label={t('Giá vốn')} hint={initial ? t('Tự cập nhật bình quân khi xác nhận phiếu nhập') : ''}><MoneyInput value={f.cost_price} onChange={(v) => setF({ ...f, cost_price: v })} /></Field>
        <Field label="VAT (%)" hint={t('Bỏ trống: theo nhóm hàng')}><input value={f.vat_rate ?? ''} onChange={set('vat_rate')} inputMode="numeric" /></Field>
        <Field label={t('Bảo hành (tháng)')} hint={t('Bỏ trống: theo nhóm hàng')}><input value={f.warranty_months ?? ''} onChange={set('warranty_months')} inputMode="numeric" /></Field>
        <Field label={t('Ngưỡng cảnh báo tồn')}><input value={f.min_stock} onChange={set('min_stock')} inputMode="numeric" /></Field>
        {!initial && !f.track_serial && <Field label={t('Tồn đầu kỳ')}><input value={f.stock} onChange={set('stock')} inputMode="numeric" /></Field>}
        <Field label={t('Trạng thái')}><select value={f.status} onChange={set('status')}>{Object.entries(STATUS).map(([k, [v]]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <label className="checkbox"><input type="checkbox" checked={!!f.track_serial} onChange={set('track_serial')} />{t('Quản lý theo serial / IMEI (tồn kho nhập qua phiếu nhập kèm serial)')}</label>
        <Field label={t('Ảnh sản phẩm')}><input type="file" accept="image/*" onChange={(e) => setFile(e.target.files[0])} /></Field>
        <Field label={t('Mô tả, thông số')} full><textarea rows={3} value={f.description || ''} onChange={set('description')} /></Field>
      </div>
    </Modal>
  )
}

function SerialsDialog({ product, onClose, onChanged }) {
  const { user } = useAuth()
  const toast = useToast()
  const { data, reload } = useLoad(() => api.get(`/products/${product.id}/serials`), [product.id])
  const mark = async (s, status) => {
    try { await api.put(`/serials/${s.id}`, { status }); toast(t('Đã cập nhật serial'), 'success'); reload(); onChanged() } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={`Serial / IMEI: ${t(product.name)}`} onClose={onClose} size="wide">
      {!data ? <Loading /> : !data.length ? <Empty title={t('Chưa có serial')} >{t('Nhập hàng kèm serial ở trang Phiếu nhập')}</Empty> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Serial / IMEI</th><th>{t('Trạng thái')}</th><th>{t('Ngày nhập')}</th>{user.role === 'owner' && <th />}</tr></thead>
          <tbody>{data.map((s) => (
            <tr key={s.id}><td className="strong">{s.serial_no}</td><td><Badge map={SERIAL_STATUS} value={s.status} /></td><td>{fmtDateTime(s.created_at)}</td>
              {user.role === 'owner' && <td className="right">
                {s.status === 'in_stock' && <button className="btn sm danger" onClick={() => mark(s, 'defective')}>{t('Đánh dấu lỗi')}</button>}
                {['defective', 'returned'].includes(s.status) && <button className="btn sm" onClick={() => mark(s, 'in_stock')}>{t('Đưa về kho')}</button>}
              </td>}
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </Modal>
  )
}

function AdjustDialog({ product, onClose, onDone }) {
  const toast = useToast()
  const [stock, setStock] = useState(product.stock)
  const [note, setNote] = useState('')
  const save = async () => {
    try { await api.post(`/products/${product.id}/adjust-stock`, { new_stock: Number(stock), note }); toast(t('Đã điều chỉnh tồn kho'), 'success'); onDone() } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={t('Kiểm kê: {0}', [t(product.name)])} onClose={onClose} size="narrow" footer={<button className="btn primary" onClick={save} disabled={!note.trim()}>{t('Lưu')}</button>}>
      <div className="stack">
        <p className="m-0 muted">{t('Tồn trên hệ thống:')} <span className="strong">{product.stock}</span></p>
        <label>{t('Tồn thực tế')}<input value={stock} onChange={(e) => setStock(e.target.value.replace(/\D/g, ''))} inputMode="numeric" /></label>
        <label>{t('Lý do (bắt buộc)')}<input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('VD: Kiểm kê cuối tháng thiếu 1')} /></label>
      </div>
    </Modal>
  )
}

function Categories({ onClose }) {
  const toast = useToast()
  const { data, reload } = useLoad(() => api.get('/categories'), [])
  const [f, setF] = useState(null)
  const save = async () => {
    const body = { ...f, default_vat_rate: f.default_vat_rate === '' ? null : Number(f.default_vat_rate),
      default_warranty_months: f.default_warranty_months === '' ? null : Number(f.default_warranty_months) }
    try { f.id ? await api.put(`/categories/${f.id}`, body) : await api.post('/categories', body); toast(t('Đã lưu nhóm hàng'), 'success'); setF(null); reload() } catch (e) { toast(e.message, 'error') }
  }
  const del = async (c) => { try { await api.del(`/categories/${c.id}`); reload() } catch (e) { toast(e.message, 'error') } }
  return (
    <Modal title={t('Nhóm hàng')} onClose={onClose} size="wide" footer={<button className="btn primary" onClick={() => setF({ name: '', name_en: '', description: '', default_vat_rate: '', default_warranty_months: '', is_active: true })}><Icon name="plus" />{t('Thêm nhóm')}</button>}>
      {!data ? <Loading /> : <div className="table-wrap"><table>
        <thead><tr><th>{t('Tên')}</th><th className="right">{t('VAT mặc định')}</th><th className="right">{t('Bảo hành')}</th><th>{t('Trạng thái')}</th><th /></tr></thead>
        <tbody>{data.map((c) => (
          <tr key={c.id}><td className="strong">{t(c.name)}<div className="muted small">{c.description}</div></td><td className="right">{c.default_vat_rate}%</td>
            <td className="right">{c.default_warranty_months} {t('tháng')}</td><td>{c.is_active ? <span className="badge green">{t('Hiện')}</span> : <span className="badge">{t('Đã ẩn')}</span>}</td>
            <td className="right nowrap"><button className="btn sm" onClick={() => setF(c)}><Icon name="edit" /></button> <button className="btn sm danger" onClick={() => del(c)}><Icon name="trash" /></button></td></tr>
        ))}</tbody>
      </table></div>}
      {f && <Modal title={f.id ? t('Sửa nhóm hàng') : t('Thêm nhóm hàng')} onClose={() => setF(null)} size="narrow" footer={<button className="btn primary" onClick={save}>{t('Lưu')}</button>}>
        <div className="stack">
          <label>{t('Tên nhóm')}<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label>{t('Tên tiếng Anh (không bắt buộc)')}<input value={f.name_en || ''} placeholder="Laptops" onChange={(e) => setF({ ...f, name_en: e.target.value })} /></label>
          <label>{t('Mô tả')}<input value={f.description || ''} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
          <label>{t('VAT mặc định (%)')}<input value={f.default_vat_rate ?? ''} placeholder={t('Bỏ trống: theo cấu hình')} onChange={(e) => setF({ ...f, default_vat_rate: e.target.value })} /></label>
          <label>{t('Bảo hành mặc định (tháng)')}<input value={f.default_warranty_months ?? ''} placeholder={t('Bỏ trống: theo cấu hình')} onChange={(e) => setF({ ...f, default_warranty_months: e.target.value })} /></label>
          <label className="checkbox"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />{t('Hiện nhóm hàng (nhóm đã có sản phẩm chỉ ẩn được, không xóa)')}</label>
        </div>
      </Modal>}
    </Modal>
  )
}

// Nhập danh mục từ CSV (SRS 7.7): xem trước rồi mới nhập; một dòng lỗi thì không nhập dòng nào
function ImportDialog({ onClose, onDone }) {
  const toast = useToast()
  const [file, setFile] = useState(null)
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const send = async (dryRun) => {
    const form = new FormData()
    form.append('file', file)
    setBusy(true)
    try {
      const r = await api.upload(`/products/import?dry_run=${dryRun}`, form)
      if (dryRun) setRes(r)
      else { toast(t('Đã nhập {0} sản phẩm', [r.created]), 'success'); onDone() }
    } catch (e) {
      if (e instanceof ApiError && e.data?.detail?.errors) setRes(e.data.detail)
      toast(e.data?.detail?.message || e.message, 'error')
    } finally { setBusy(false) }
  }
  const ok = res && !res.errors.length && res.to_create > 0
  return (
    <Modal title={t('Nhập sản phẩm từ CSV')} size="wide" onClose={onClose} footer={<>
      <button className="btn" disabled={!file || busy} onClick={() => send(true)}><Icon name="eye" />{t('Kiểm tra tệp')}</button>
      <button className="btn primary" disabled={!ok || busy} onClick={() => send(false)}><Icon name="upload" />{t('Nhập')} {ok ? t('{0} sản phẩm', [res.to_create]) : ''}</button>
    </>}>
      <p className="mt-0">{t('Điền tệp theo mẫu (cột bắt buộc:')} <code>sku</code>, <code>ten</code>, <code>gia_ban</code>{t('). Bỏ trống VAT, bảo hành thì lấy theo nhóm hàng; nhóm hàng chưa có sẽ được tạo mới. SKU đã có trong hệ thống sẽ được bỏ qua. Tồn đầu kỳ nhập bằng phiếu nhập.')}</p>
      <div className="row mb-4" style={{ flexWrap: 'wrap' }}>
        <button className="btn sm" onClick={() => openFile('/products/import-template', null, 'mau_nhap_san_pham.csv')}><Icon name="download" />{t('Tải tệp mẫu')}</button>
        <input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] || null); setRes(null) }} />
      </div>
      {res && <>
        <div className="row mb-4" style={{ flexWrap: 'wrap' }}>
          <span className="badge green">{t('Sẽ tạo')} {res.to_create}</span>
          {res.skipped.length > 0 && <span className="badge yellow">{t('Bỏ qua')} {res.skipped.length} {t('(SKU đã có)')}</span>}
          {res.errors.length > 0 && <span className="badge red">{res.errors.length} {t('dòng lỗi: sửa tệp rồi kiểm tra lại')}</span>}
        </div>
        {res.errors.length > 0 && (
          <div className="table-wrap mb-4"><table>
            <thead><tr><th>{t('Dòng')}</th><th>SKU</th><th>{t('Lỗi')}</th></tr></thead>
            <tbody>{res.errors.map((e) => <tr key={`${e.line}-${e.error}`}><td>{e.line}</td><td>{e.sku}</td><td className="small">{e.error}</td></tr>)}</tbody>
          </table></div>
        )}
        {res.preview.length > 0 && (
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Dòng')}</th><th>SKU</th><th>{t('Tên')}</th><th>{t('Nhóm')}</th><th className="right">{t('Giá bán')}</th><th>Serial</th></tr></thead>
            <tbody>{res.preview.map((p) => <tr key={p.line}><td>{p.line}</td><td>{p.sku}</td><td>{p.name}</td><td>{p.category || '-'}</td>
              <td className="right num">{money(p.sale_price)}</td><td>{p.track_serial ? t('Có') : ''}</td></tr>)}</tbody>
          </table></div>
        )}
      </>}
    </Modal>
  )
}

export default function Products() {
  const { user } = useAuth()
  const owner = user.role === 'owner'
  const toast = useToast()
  const [f, setF] = useState({ q: '', category_id: '', status: '', stock: '', min_price: '', max_price: '' })
  const [page, setPage] = useState(1)
  const [dialog, setDialog] = useState(null)
  const cats = useLoad(() => api.get('/categories'), [])
  const { data, loading, error, reload } = useLoad(() => api.get('/products', { ...f, page, size: 20 }), [JSON.stringify(f), page])
  const set = (k) => (e) => { setPage(1); setF({ ...f, [k]: e.target.value }) }
  const remove = async (p) => {
    try { toast((await api.del(`/products/${p.id}`)).message, 'success'); reload() } catch (e) { toast(e.message, 'error') }
  }
  return (
    <div className="card">
      <div className="toolbar">
        <label className="grow">{t('Tìm sản phẩm')}<input placeholder={t('SKU, mã vạch, tên (không cần dấu)')} value={f.q} onChange={set('q')} /></label>
        <label>{t('Nhóm')}<select value={f.category_id} onChange={set('category_id')}><option value="">{t('Tất cả')}</option>
          {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{t(c.name)}</option>)}</select></label>
        <label>{t('Trạng thái')}<select value={f.status} onChange={set('status')}><option value="">{t('Tất cả')}</option>
          {Object.entries(STATUS).map(([k, [v]]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>{t('Tồn kho')}<select value={f.stock} onChange={set('stock')}><option value="">{t('Tất cả')}</option>
          {Object.entries(STOCK).map(([k, [v]]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>{t('Giá từ')}<input value={f.min_price} onChange={set('min_price')} inputMode="numeric" style={{ width: 110 }} /></label>
        <label>{t('đến')}<input value={f.max_price} onChange={set('max_price')} inputMode="numeric" style={{ width: 110 }} /></label>
        {owner && <div className="actions">
          <button className="btn" onClick={() => setDialog({ type: 'cats' })}><Icon name="tag" />{t('Nhóm hàng')}</button>
          <button className="btn" onClick={() => setDialog({ type: 'import' })}><Icon name="upload" />{t('Nhập CSV')}</button>
          <button className="btn primary" onClick={() => setDialog({ type: 'form' })}><Icon name="plus" />{t('Thêm sản phẩm')}</button>
        </div>}
      </div>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : data && (!data.items.length ? <Empty title={t('Không có sản phẩm phù hợp')} /> : <>
        <div className="table-wrap"><table>
          <thead><tr><th>{t('Sản phẩm')}</th><th>{t('Nhóm')}</th><th className="right">{t('Giá bán')}</th>{owner && <th className="right">{t('Giá vốn')}</th>}
            <th className="right">VAT</th><th className="right">{t('Tồn')}</th><th>{t('Trạng thái')}</th><th /></tr></thead>
          <tbody>{data.items.map((p) => (
            <tr key={p.id}>
              <td><div className="cell-product"><Thumb url={p.image_url} name={t(p.name)} size="sm" /><div>
                <div className="strong">{t(p.name)}</div><div className="muted small">{p.code}{p.barcode ? ` · ${p.barcode}` : ''}{p.brand ? ` · ${p.brand}` : ''}</div></div></div></td>
              <td>{t(p.category_name) || '-'}</td><td className="right num">{money(p.sale_price)}</td>
              {owner && <td className="right num muted">{money(p.cost_price)}</td>}
              <td className="right">{p.vat_rate}%</td>
              <td className="right"><span className="strong">{num(p.stock)}</span> <Badge map={STOCK} value={p.stock_state} /></td>
              <td><Badge map={STATUS} value={p.status} />{p.track_serial && <span className="badge blue">Serial</span>}</td>
              <td className="right nowrap">
                {p.track_serial && <button className="btn sm" onClick={() => setDialog({ type: 'serials', p })} title="Serial"><Icon name="barcode" /></button>}
                {owner && !p.track_serial && <button className="btn sm" onClick={() => setDialog({ type: 'adjust', p })} title={t('Kiểm kê')}><Icon name="clipboard" /></button>}
                {owner && <button className="btn sm" onClick={() => setDialog({ type: 'form', p })} title={t('Sửa')}><Icon name="edit" /></button>}
                {owner && <button className="btn sm danger" onClick={() => remove(p)} title={t('Xóa')}><Icon name="trash" /></button>}
              </td>
            </tr>
          ))}</tbody>
        </table></div>
        <Pager page={page} size={20} total={data.total} onPage={setPage} />
      </>)}
      {dialog?.type === 'form' && <ProductForm initial={dialog.p} cats={cats.data || []} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); reload() }} />}
      {dialog?.type === 'serials' && <SerialsDialog product={dialog.p} onClose={() => setDialog(null)} onChanged={reload} />}
      {dialog?.type === 'adjust' && <AdjustDialog product={dialog.p} onClose={() => setDialog(null)} onDone={() => { setDialog(null); reload() }} />}
      {dialog?.type === 'cats' && <Categories onClose={() => { setDialog(null); cats.reload() }} />}
      {dialog?.type === 'import' && <ImportDialog onClose={() => setDialog(null)} onDone={() => { setDialog(null); reload(); cats.reload() }} />}
    </div>
  )
}
