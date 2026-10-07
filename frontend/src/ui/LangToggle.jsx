// Chọn ngôn ngữ giao diện (VI / EN) trên thanh trên cùng và màn hình đăng nhập
import { lang, setLang, t } from '../i18n.js'

const LANGS = [['vi', 'VI', 'Tiếng Việt'], ['en', 'EN', 'English']]

export default function LangToggle() {
  return (
    <div className="lang-toggle" role="group" aria-label={t('Ngôn ngữ')}>
      {LANGS.map(([code, short, name]) => (
        <button key={code} type="button" className={lang === code ? 'active' : ''} aria-pressed={lang === code}
          title={name} onClick={() => setLang(code)}>{short}</button>
      ))}
    </div>
  )
}
