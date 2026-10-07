import { t } from '../i18n.js'
import { Thumb } from './kit.jsx'

export default function ProductCell({ p }) {
  return (
    <div className="cell-product">
      <Thumb url={p.image_url} name={t(p.name || p.product_name)} size="sm" />
      <div className="min-w-0"><div className="title strong">{t(p.name || p.product_name)}</div><div className="muted small">{p.code || p.product_code}</div></div>
    </div>
  )
}
