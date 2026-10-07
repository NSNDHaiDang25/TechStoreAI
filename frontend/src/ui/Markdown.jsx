// Hiển thị Markdown do AI sinh ra. Luôn lọc qua DOMPurify trước khi chèn HTML (NFR-SEC-06).
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { useMemo } from 'react'

marked.setOptions({ gfm: true, breaks: true })

export function renderMarkdown(md) {
  return DOMPurify.sanitize(marked.parse(String(md || '')))
}

export default function Markdown({ text, className = '' }) {
  const html = useMemo(() => renderMarkdown(text), [text])
  return <div className={`markdown ${className}`} dangerouslySetInnerHTML={{ __html: html }} />
}
