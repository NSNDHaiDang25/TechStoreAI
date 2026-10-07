// Nhật ký gọi AI (BR-44, bảng ai_logs). Nhân viên chỉ xem lượt của mình.
import { Fragment, useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { fmtDateTime, num } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Badge, Empty, ErrorBox, Loading, Pager, useLoad } from '../ui/kit.jsx'
import { Kpi } from './Dashboard.jsx'
import { t } from '../i18n.js'

const FEATURE = { assistant: t('Trợ lý đa năng'), advisor: t('Tư vấn sản phẩm'), cross_sell: t('Gợi ý phụ kiện'), report: t('Báo cáo doanh thu'), qa: t('Hỏi đáp dữ liệu') }
const STATUS = {
  success: [t('Thành công'), 'green'], fallback: [t('Dự phòng'), 'yellow'], timeout: [t('Quá thời gian'), 'red'],
  rate_limited: [t('Hết lượt'), 'red'], invalid_format: [t('Sai định dạng'), 'red'], rejected_sql: [t('SQL bị chặn'), 'red'], error: [t('Lỗi'), 'red'],
}

export default function AILogs() {
  const { user } = useAuth()
  const [f, setF] = useState({ feature: '', status: '' })
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(null)
  const { data, error } = useLoad(() => api.get('/ai/logs', { ...f, page, size: 30 }), [f.feature, f.status, page])
  const ai = useLoad(() => api.get('/ai/status'), [])
  const set = (k) => (e) => { setPage(1); setF({ ...f, [k]: e.target.value }) }
  const sum = data?.summary || {}
  const total = Object.values(sum).reduce((a, b) => a + b, 0)
  return (
    <div className="stack">
      {user.role !== 'staff' && data && (
        <div className="grid kpi">
          <Kpi featured icon="sparkles" label={t('Tổng lượt gọi')} value={num(total)} sub={ai.data ? t('Giới hạn {0} lượt / người / giờ', [ai.data.rate_limit_per_hour || t('không giới hạn')]) : ''} />
          <Kpi icon="check" color="green" label={t('Thành công')} value={num(sum.success || 0)} sub={total ? `${(((sum.success || 0) / total) * 100).toFixed(0)}%` : ''} />
          <Kpi icon="clock" label={t('Thời gian phản hồi TB')} value={data.avg_latency_ms ? `${num(data.avg_latency_ms)} ms` : '-'} sub={t('Lượt thành công (NFR-PER-06)')} />
          <Kpi icon="alert" color={total - (sum.success || 0) ? 'yellow' : ''} label={t('Dự phòng / lỗi')} value={num(total - (sum.success || 0))}
            sub={Object.entries(sum).filter(([k]) => k !== 'success').map(([k, v]) => `${STATUS[k]?.[0] || k} ${v}`).join(' · ')} />
        </div>
      )}
      <div className="card">
        <div className="toolbar">
          <label>{t('Tính năng')}<select value={f.feature} onChange={set('feature')}><option value="">{t('Tất cả')}</option>
            {Object.entries(FEATURE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>{t('Trạng thái')}<select value={f.status} onChange={set('status')}><option value="">{t('Tất cả')}</option>
            {Object.entries(STATUS).map(([k, [v]]) => <option key={k} value={k}>{v}</option>)}</select></label>
          {ai.data && <div className="actions"><span className="muted small">Model: {ai.data.model || t('chưa sẵn sàng')} {t('· Prompt tư vấn')} {ai.data.advisor_prompt_version}</span></div>}
        </div>
        <ErrorBox error={error} />
        {!data ? <Loading /> : !data.items.length ? <Empty icon="history" title={t('Chưa có lượt gọi AI')} /> : <>
          <div className="table-wrap"><table>
            <thead><tr><th>{t('Thời gian')}</th>{user.role !== 'staff' && <th>{t('Người dùng')}</th>}<th>{t('Tính năng')}</th><th>{t('Câu hỏi')}</th><th>{t('Trạng thái')}</th><th className="right">{t('Độ trễ')}</th><th>Model</th></tr></thead>
            <tbody>{data.items.map((r) => (
              <Fragment key={r.id}>
                <tr className="clickable" onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}>
                  <td className="small nowrap">{fmtDateTime(r.created_at)}</td>
                  {user.role !== 'staff' && <td>{r.user_name}</td>}
                  <td>{FEATURE[r.feature] || r.feature}{r.prompt_version && r.prompt_version !== '-' && <span className="badge">{r.prompt_version}</span>}</td>
                  <td className="small">{r.question?.length > 90 ? `${r.question.slice(0, 90)}…` : r.question}</td>
                  <td><Badge map={STATUS} value={r.status} />{r.retry_count > 0 && <span className="muted small"> {t('· thử lại')} {r.retry_count}</span>}</td>
                  <td className="right num">{r.latency_ms ? `${num(r.latency_ms)} ms` : '-'}</td>
                  <td className="small muted">{r.model_name}</td>
                </tr>
                {open === r.id && (
                  <tr><td colSpan={7}>
                    <div className="stack">
                      <div><div className="muted small">{t('Câu hỏi (đã che số điện thoại, email)')}</div><div>{r.question}</div></div>
                      {r.generated_sql && <div><div className="muted small">{t('SQL do AI sinh')}</div><pre className="sql-code"><code>{r.generated_sql}</code></pre></div>}
                      <div><div className="muted small">{t('Phản hồi')}</div><pre className="sql-code">{r.response || t('(trống)')}</pre></div>
                    </div>
                  </td></tr>
                )}
              </Fragment>
            ))}</tbody>
          </table></div>
          <Pager page={page} size={30} total={data.total} onPage={setPage} />
        </>}
      </div>
    </div>
  )
}
