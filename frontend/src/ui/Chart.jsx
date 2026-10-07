// Biểu đồ Chart.js: màu lấy từ biến CSS, tự vẽ lại khi đổi giao diện sáng / tối
import {
  ArcElement, BarController, BarElement, CategoryScale, Chart as ChartJS, DoughnutController, Filler, Legend,
  LinearScale, LineController, LineElement, PointElement, Tooltip,
} from 'chart.js'
import { useEffect, useRef, useState } from 'react'
import { money, num } from '../format.js'
import { t } from '../i18n.js'

ChartJS.register(ArcElement, BarController, BarElement, CategoryScale, DoughnutController, Filler, Legend,
  LinearScale, LineController, LineElement, PointElement, Tooltip)

function chartTheme() {
  const cs = getComputedStyle(document.documentElement)
  const v = (n) => cs.getPropertyValue(n).trim()
  return {
    text: v('--text'), text2: v('--text-2'), muted: v('--muted'), surface: v('--surface'), border: v('--border-strong'),
    line: v('--chart-line') || '#2563eb', grid: v('--chart-grid'), axis: v('--chart-axis'), other: v('--chart-other') || '#94a3b8',
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--chart-${i}`)).filter(Boolean),
  }
}

const alpha = (color, a) => {
  if (!color.startsWith('#')) return color
  const n = parseInt(color.slice(1, 7), 16)
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}
const tooltip = (tt, label) => ({
  backgroundColor: tt.surface, titleColor: tt.text, bodyColor: tt.text2, borderColor: tt.border, borderWidth: 1,
  padding: 10, cornerRadius: 8, boxPadding: 4, callbacks: { label },
})

// Một chuỗi doanh thu (đường hoặc cột)
export function seriesChart(type, labels, values, label = t('Doanh thu')) {
  return (tt) => {
    const c = tt.line
    const fill = ({ chart: { ctx, chartArea: a } }) => {
      if (!a) return alpha(c, 0.1)
      const g = ctx.createLinearGradient(0, a.top, 0, a.bottom)
      g.addColorStop(0, alpha(c, 0.24)); g.addColorStop(1, alpha(c, 0))
      return g
    }
    const ds = type === 'line'
      ? { borderColor: c, backgroundColor: fill, fill: true, tension: 0.3, cubicInterpolationMode: 'monotone', borderWidth: 2, pointRadius: 0, pointHoverRadius: 5 }
      : { backgroundColor: c, hoverBackgroundColor: alpha(c, 0.8), borderRadius: 4, borderSkipped: 'start', maxBarThickness: 32 }
    return {
      type, data: { labels, datasets: [{ label, data: values, ...ds }] },
      options: {
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false }, tooltip: tooltip(tt, (x) => money(x.raw)) },
        scales: {
          x: { grid: { display: false }, border: { color: tt.axis }, ticks: { color: tt.muted, maxRotation: 0, autoSkipPadding: 12 } },
          y: { grid: { color: tt.grid }, border: { display: false }, ticks: { color: tt.muted, callback: (v) => num(v) } },
        },
      },
    }
  }
}

// Tỉ trọng doanh thu theo nhóm hàng, chú thích kèm phần trăm (không chỉ dựa vào màu)
export function shareChart(rows, labelKey = 'category', valueKey = 'revenue') {
  return (tt) => {
    const total = rows.reduce((s, r) => s + r[valueKey], 0) || 1
    const pct = (i) => `${((rows[i][valueKey] / total) * 100).toFixed(1)}%`
    return {
      type: 'doughnut',
      data: {
        labels: rows.map((r) => t(r[labelKey])),
        datasets: [{ data: rows.map((r) => r[valueKey]), backgroundColor: rows.map((_, i) => tt.series[i] || tt.other),
          borderColor: tt.surface, borderWidth: 2, hoverOffset: 4 }],
      },
      options: {
        cutout: '62%',
        plugins: {
          legend: { position: 'right', labels: { color: tt.text2, usePointStyle: true, pointStyle: 'circle', boxWidth: 8, padding: 14,
            generateLabels: (c) => ChartJS.overrides.doughnut.plugins.legend.labels.generateLabels(c).map((l) => ({ ...l, text: `${l.text} · ${pct(l.index)}` })) } },
          tooltip: tooltip(tt, (x) => `${x.label}: ${money(x.raw)} (${pct(x.dataIndex)})`),
        },
      },
    }
  }
}

function useThemeKey() {
  const [key, setKey] = useState(document.documentElement.getAttribute('data-theme'))
  useEffect(() => {
    const ob = new MutationObserver(() => setKey(document.documentElement.getAttribute('data-theme')))
    ob.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => ob.disconnect()
  }, [])
  return key
}

// build: (theme) => cấu hình Chart.js
export default function Chart({ build, label }) {
  const ref = useRef(null)
  const theme = useThemeKey()
  const first = useRef(true)
  useEffect(() => {
    ChartJS.defaults.font.family = getComputedStyle(document.body).fontFamily
    const cfg = build(chartTheme())
    cfg.options = { responsive: true, maintainAspectRatio: false, ...cfg.options, ...(first.current ? {} : { animation: false }) }
    first.current = false
    const c = new ChartJS(ref.current, cfg)
    return () => c.destroy()
  }, [build, theme])
  return <div className="chart-box"><canvas ref={ref} role="img" aria-label={label} /></div>
}
