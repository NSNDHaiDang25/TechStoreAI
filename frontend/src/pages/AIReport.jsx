// AI sinh báo cáo doanh thu (UC-35, SRS 6.4): hệ thống tính số liệu, AI viết nhận xét và khuyến nghị nhập hàng
import { useState } from 'react'
import { api, getToken } from '../api.js'
import { daysAgo, money, num, today } from '../format.js'
import Icon from '../ui/Icon.jsx'
import { Empty, useToast } from '../ui/kit.jsx'
import Markdown from '../ui/Markdown.jsx'
import RangePicker from '../ui/RangePicker.jsx'
import { t } from '../i18n.js'

function pctChange(cur, prev) {
  if (!prev) return null
  const p = ((cur - prev) / prev) * 100
  return `${p >= 0 ? '+' : ''}${p.toFixed(1)}%`
}

export default function AIReport() {
  const toast = useToast()
  const [range] = useState({ date_from: daysAgo(29), date_to: today() })
  const [state, setState] = useState({ res: null, busy: false, error: null })
  const run = async (r) => {
    setState({ res: null, busy: true, error: null })
    try { setState({ res: await api.post('/ai/report', r), busy: false, error: null }) } catch (e) { setState({ res: null, busy: false, error: e.message, r }) }
  }
  const { res, busy, error } = state
  const download = () => {
    const url = URL.createObjectURL(new Blob([res.markdown], { type: 'text/markdown;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url; a.download = `bao-cao-ai-${res.period.from}-${res.period.to}.md`; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
  // FR-AIR-06: xuất báo cáo đang xem ra PDF
  const downloadPdf = async () => {
    try {
      const resp = await fetch('/api/ai/report/pdf', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ markdown: res.markdown, date_from: res.period.from, date_to: res.period.to }),
      })
      if (!resp.ok) throw new Error(t('Lỗi {0}', [resp.status]))
      const url = URL.createObjectURL(await resp.blob())
      const a = document.createElement('a')
      a.href = url; a.download = `bao-cao-ai-${res.period.from}-${res.period.to}.pdf`; a.click()
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) { toast(t('Không xuất được PDF: {0}', [e.message]), 'error') }
  }
  const s = res?.data?.summary
  const prev = res?.data?.previous_period_summary
  return (
    <div className="stack">
      <div className="card">
        <RangePicker value={range} onChange={run} busy={busy} submitLabel={t('Tạo báo cáo')} />
        <p className="muted small mt-3 mb-0">{t('Hệ thống tự tính doanh thu, tồn kho, sản phẩm bán chạy và bán chậm, sau đó AI viết nhận xét và khuyến nghị nhập hàng. Dữ liệu gửi cho AI chỉ là số liệu tổng hợp, không có tên, số điện thoại hay thông tin thanh toán của khách (NFR-DAT-01).')}</p>
      </div>
      <div className="card">
        {busy ? <div className="loading"><span className="spinner" /> {t('AI đang phân tích dữ liệu, thường mất 5 đến 20 giây...')}</div>
          : error ? (
            <div className="error-state" role="alert"><Icon name="alert" /><div className="grow"><div className="strong">{t('Không tạo được báo cáo')}</div><div>{error}</div></div>
              <button className="btn sm" onClick={() => run(state.r)}><Icon name="refresh" />{t('Thử lại')}</button></div>
          ) : !res ? <Empty icon="sparkles" title={t('Chưa có báo cáo')}>{t('Chọn kỳ rồi bấm Tạo báo cáo hoặc một nút chọn nhanh.')}</Empty>
            : <>
              <div className="card-head"><h2><Icon name="sparkles" />{t('Báo cáo')} {res.period.from} → {res.period.to} ({t('{0} ngày', [res.period.days])})</h2>
                <button className="btn sm" onClick={() => navigator.clipboard?.writeText(res.markdown).then(() => toast(t('Đã sao chép'), 'success'))}><Icon name="copy" />{t('Sao chép')}</button>
                <button className="btn sm" onClick={downloadPdf}><Icon name="download" />{t('Tải PDF')}</button>
                <button className="btn sm" onClick={download}><Icon name="download" />{t('Tải .md')}</button></div>
              <div className="row mb-4" style={{ flexWrap: 'wrap' }}>
                {res.source === 'ai' ? <span className="badge dot cyan">Gemini{res.model ? ` · ${res.model}` : ''}</span> : <span className="badge dot yellow">{t('Báo cáo dự phòng')}</span>}
                {res.latency_ms ? <span className="muted small">{res.latency_ms} ms</span> : null}
                {s && <span className="muted small">{t('Số liệu đối chiếu: doanh thu')} {money(s.revenue)} · {num(s.invoice_count)} {t('hóa đơn')}
                  {prev && pctChange(s.revenue, prev.revenue) ? t(' · so với kỳ trước {0}', [pctChange(s.revenue, prev.revenue)]) : ''}
                  {res.data.stock_value != null ? t(' · giá trị tồn {0}', [money(res.data.stock_value)]) : ''}</span>}
              </div>
              {res.warning && <div className="note mb-4"><Icon name="alert" /><span>{res.warning}</span></div>}
              <Markdown text={res.markdown} />
            </>}
      </div>
    </div>
  )
}
