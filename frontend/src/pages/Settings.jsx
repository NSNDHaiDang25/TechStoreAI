// Cấu hình (UC-07 tham số kinh doanh của chủ cửa hàng, UC-08 tham số kỹ thuật và AI của quản trị viên)
// và hạng khách hàng (UC-16). Mọi thay đổi được ghi audit log ở backend.
import { useMemo, useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { money, num } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { ErrorBox, Loading, MoneyInput, useLoad, useToast } from '../ui/kit.jsx'
import { locale, t } from '../i18n.js'

const GROUPS = [
  [t('Bán hàng và kho'), 'cart', ['low_stock_threshold', 'return_window_hours', 'warranty_months_default', 'vat_rate_default', 'pending_payment_minutes']],
  [t('Tích điểm'), 'award', ['points_per_vnd', 'point_value_vnd', 'points_max_percent']],
  [t('Thông tin cửa hàng in trên hóa đơn'), 'store', ['store_name', 'store_address', 'store_phone', 'store_tax_code']],
  [t('Tài khoản nhận chuyển khoản (VietQR)'), 'bank', ['bank_bin', 'bank_name', 'bank_account', 'bank_account_name']],
  [t('Bảo mật đăng nhập'), 'lock', ['jwt_expire_hours', 'login_max_fail', 'login_lock_minutes', 'face_login_enabled', 'face_liveness_enabled', 'face_login_threshold']],
  [t('Trí tuệ nhân tạo'), 'sparkles', ['ai_enabled', 'ai_model_name', 'ai_prompt_version', 'ai_timeout_seconds', 'ai_max_retries', 'ai_rate_limit_per_hour']],
]
const MONEY_KEYS = new Set(['points_per_vnd', 'point_value_vnd'])
const HIDDEN = new Set(['tier_silver_min', 'tier_gold_min'])  // sửa ở bảng hạng khách hàng bên dưới

function SettingInput({ s, value, onChange }) {
  if (!s.editable) return <span className="strong">{String(s.value)}</span>
  if (s.type === 'bool') {
    return <select value={value ? '1' : '0'} onChange={(e) => onChange(e.target.value === '1')}><option value="1">{t('Bật')}</option><option value="0">{t('Tắt')}</option></select>
  }
  if (s.key === 'ai_prompt_version') {
    return <select value={value} onChange={(e) => onChange(e.target.value)}>{['v1', 'v2', 'v3'].map((v) => <option key={v} value={v}>Prompt {v}</option>)}</select>
  }
  if (s.type === 'int') {
    if (MONEY_KEYS.has(s.key)) return <MoneyInput value={value} onChange={onChange} />
    return <input type="number" min={s.min ?? undefined} max={s.max ?? undefined} value={value}
      onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
  }
  if (s.type === 'float') {
    return <input type="number" step="0.01" min={s.min ?? undefined} max={s.max ?? undefined} value={value}
      onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
  }
  return <input value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
}

function Tiers() {
  const { user } = useAuth()
  const toast = useToast()
  const { data, error, reload } = useLoad(() => api.get('/customer-tiers'), [])
  const [edit, setEdit] = useState(null)
  const rows = edit || data || []
  const save = async () => {
    try {
      await api.put('/customer-tiers', { tiers: edit.map((tt) => ({ id: tt.id, min_total_spent: Number(tt.min_total_spent) || 0, points_multiplier: Number(tt.points_multiplier) || 0 })) })
      toast(t('Đã lưu hạng khách hàng và tính lại hạng cho mọi khách'), 'success'); setEdit(null); reload()
    } catch (e) { toast(e.message, 'error') }
  }
  const upd = (i, k, v) => setEdit(rows.map((tt, j) => (j === i ? { ...tt, [k]: v } : tt)))
  return (
    <div className="card">
      <div className="card-head"><h2><Icon name="award" />{t('Hạng khách hàng')}</h2>
        {edit && <><button className="btn sm" onClick={() => setEdit(null)}>{t('Hủy')}</button><button className="btn sm primary" onClick={save}><Icon name="save" />{t('Lưu')}</button></>}</div>
      <ErrorBox error={error} />
      {!data ? <Loading /> : (
        <div className="table-wrap"><table>
          <thead><tr><th>{t('Hạng')}</th><th>{t('Tổng chi tiêu từ')}</th><th>{t('Hệ số điểm')}</th><th className="right">{t('Số khách')}</th></tr></thead>
          <tbody>{rows.map((tt, i) => (
            <tr key={tt.id}><td className="strong">{t(tt.name)}</td>
              <td>{user.role === 'staff' ? money(tt.min_total_spent) : <MoneyInput value={tt.min_total_spent} disabled={i === 0} onChange={(v) => upd(i, 'min_total_spent', v)} />}</td>
              <td><input type="number" step="0.1" min="0" max="10" value={tt.points_multiplier} style={{ width: 90 }} onChange={(e) => upd(i, 'points_multiplier', e.target.value)} /></td>
              <td className="right">{num(tt.customer_count)}</td></tr>
          ))}</tbody>
        </table></div>
      )}
      <p className="muted small mb-0">{t('Hạng thấp nhất luôn bắt đầu từ 0 đồng. Khi lưu, hệ thống tính lại hạng của mọi khách theo tổng chi tiêu (FR-LOY-01, 02).')}</p>
    </div>
  )
}

function AIStatus() {
  const { data, error, reload, loading } = useLoad(() => api.get('/ai/status'), [])
  return (
    <div className="card">
      <div className="card-head"><h2><Icon name="sparkles" />{t('Kết nối Gemini')}</h2>
        <button className="btn sm" onClick={reload} disabled={loading}><Icon name="refresh" />{t('Kiểm tra lại')}</button></div>
      <ErrorBox error={error} />
      {data && <>
        <div className="row mb-4" style={{ flexWrap: 'wrap' }}>
          {!data.switched_on ? <span className="badge red">{t('AI đang tắt')}</span> : !data.enabled ? <span className="badge yellow">{t('Chưa có GEMINI_API_KEY: chạy chế độ dự phòng')}</span>
            : data.model ? <span className="badge green">{t('Đang dùng')} {data.model}</span> : <span className="badge red">{t('Mọi model đều tạm hết lượt')}</span>}
        </div>
        {data.models?.length > 0 && (
          <div className="table-wrap"><table>
            <thead><tr><th>Model</th><th>{t('Tình trạng')}</th></tr></thead>
            <tbody>{data.models.map((m) => <tr key={m.model}><td>{m.model}</td><td>{m.available ? <span className="badge green">{t('Sẵn sàng')}</span>
              : <span className="badge red" title={m.reason || ''}>{t('Tạm ngưng')}{m.until ? t(' đến {0}', [new Date(m.until).toLocaleTimeString(locale)]) : ''}</span>}</td></tr>)}</tbody>
          </table></div>
        )}
        <p className="muted small mb-0">{t('Khóa API đặt trong tệp .env trên máy chủ và không hiển thị lại ở đây (UC-08).')}</p>
      </>}
    </div>
  )
}

export default function Settings() {
  const { user } = useAuth()
  const toast = useToast()
  const { data, error, setData } = useLoad(() => api.get('/settings'), [])
  const [draft, setDraft] = useState({})
  const [busy, setBusy] = useState(false)
  const byKey = useMemo(() => Object.fromEntries((data?.items || []).map((s) => [s.key, s])), [data])
  const changed = Object.keys(draft).filter((k) => draft[k] !== byKey[k]?.value)
  const save = async () => {
    setBusy(true)
    try {
      const r = await api.put('/settings', { values: Object.fromEntries(changed.map((k) => [k, draft[k]])) })
      setData({ items: r.items }); setDraft({})
      toast(r.updated.length ? t('Đã lưu {0} tham số', [r.updated.length]) : t('Không có gì thay đổi'), 'success')
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  const known = new Set(GROUPS.flatMap((g) => g[2]))
  const others = (data?.items || []).filter((s) => !known.has(s.key) && !HIDDEN.has(s.key))
  const editableFirst = (g) => (g[2].some((k) => byKey[k]?.editable) ? 0 : 1)  // nhóm mình sửa được lên trước
  const groups = [...GROUPS, ...(others.length ? [[t('Khác'), 'settings', others.map((s) => s.key)]] : [])]
    .sort((a, b) => editableFirst(a) - editableFirst(b))
  return (
    <div className="stack w-lg">
      <ErrorBox error={error} />
      {!data ? <Loading /> : <>
        <div className="card">
          <div className="toolbar mb-0">
            <p className="muted small m-0 grow">{user.role === 'admin' ? t('Quản trị viên sửa tham số kỹ thuật, bảo mật và AI; tham số kinh doanh do chủ cửa hàng sửa (ở đây chỉ xem).') : t('Chủ cửa hàng sửa tham số kinh doanh; tham số kỹ thuật và AI do quản trị viên quản lý.')}
              {' '}{t('Tham số mới có hiệu lực ngay, không cần khởi động lại.')}</p>
            <div className="actions">
              {changed.length > 0 && <button className="btn" onClick={() => setDraft({})}>{t('Hoàn tác')}</button>}
              <button className="btn primary" disabled={!changed.length || busy} onClick={save}><Icon name="save" />{t('Lưu')} {changed.length ? `(${changed.length})` : ''}</button>
            </div>
          </div>
        </div>
        {groups.map(([title, icon, keys]) => {
          const items = keys.map((k) => byKey[k]).filter(Boolean)
          if (!items.length) return null
          return (
            <div className="card" key={title}>
              <div className="card-head"><h2><Icon name={icon} />{title}</h2></div>
              <div className="settings-list">{items.map((s) => {
                const value = s.key in draft ? draft[s.key] : s.value
                return (
                  <div key={s.key} className={`settings-row ${changed.includes(s.key) ? 'changed' : ''}`}>
                    <div><div>{t(s.description)}</div><div className="k">{s.key}{s.default !== undefined && s.value !== s.default ? t(' · mặc định {0}', [String(s.default)]) : ''}</div></div>
                    <SettingInput s={s} value={value} onChange={(v) => setDraft({ ...draft, [s.key]: v })} />
                  </div>
                )
              })}</div>
            </div>
          )
        })}
      </>}
      {user.role === 'owner' && <Tiers />}
      {user.role === 'admin' && <AIStatus />}
    </div>
  )
}
