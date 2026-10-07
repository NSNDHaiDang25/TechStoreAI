// Điều hướng theo vai trò (SRS bảng 4.2). Menu ẩn trang không có quyền, backend vẫn kiểm tra quyền ở từng API.
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api.js'
import { AuthProvider, useAuth } from './auth.jsx'
import { useEnglishNames } from './i18n.js'
import { NAV, homeFor } from './nav.js'
import Shell from './Shell.jsx'
import { Loading, ToastProvider } from './ui/kit.jsx'
import Account, { ForcedChange } from './pages/Account.jsx'
import AIChat from './pages/AIChat.jsx'
import AIConversations from './pages/AIConversations.jsx'
import AILogs from './pages/AILogs.jsx'
import AIReport from './pages/AIReport.jsx'
import Audit from './pages/Audit.jsx'
import Backup from './pages/Backup.jsx'
import Customers from './pages/Customers.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Inventory from './pages/Inventory.jsx'
import Invoices from './pages/Invoices.jsx'
import Login from './pages/Login.jsx'
import Pos from './pages/Pos.jsx'
import Products from './pages/Products.jsx'
import Promotions from './pages/Promotions.jsx'
import PurchaseOrders from './pages/PurchaseOrders.jsx'
import Reports from './pages/Reports.jsx'
import Returns from './pages/Returns.jsx'
import Settings from './pages/Settings.jsx'
import Suppliers from './pages/Suppliers.jsx'
import Users from './pages/Users.jsx'
import Warranty from './pages/Warranty.jsx'

const PAGES = {
  '/': Dashboard,
  '/pos': Pos,
  '/invoices': Invoices,
  '/returns': Returns,
  '/warranty': Warranty,
  '/customers': Customers,
  '/products': Products,
  '/promotions': Promotions,
  '/purchase-orders': PurchaseOrders,
  '/suppliers': Suppliers,
  '/inventory': Inventory,
  '/reports': Reports,
  '/ai/assistant': () => <AIChat kind="assistant" />,
  '/ai/advisor': () => <AIChat kind="advisor" />,
  '/ai/report': AIReport,
  '/ai/ask': () => <AIChat kind="ask" />,
  '/ai/logs': AILogs,
  '/ai/conversations': AIConversations,
  '/users': Users,
  '/settings': Settings,
  '/audit': Audit,
  '/system': Backup,
  '/account': Account,
}

const ROUTES = NAV.flatMap((g) => g.items)

function NotFound() {
  const { user } = useAuth()
  const loc = useLocation()
  // Trang không tồn tại hoặc không có quyền: về trang chủ của vai trò
  return <Navigate to={homeFor(user.role)} replace state={{ from: loc.pathname }} />
}

const fetchEnglishNames = () => api.get('/catalog/names')

function Routed() {
  const { user, ready } = useAuth()
  useEnglishNames(user?.id, fetchEnglishNames)
  if (!ready) return <div className="center-screen"><Loading /></div>
  if (!user) return <Login />
  if (user.must_change_password) return <ForcedChange />
  return (
    <Routes>
      {ROUTES.filter((r) => r.roles.includes(user.role)).map((r) => {
        const Page = PAGES[r.to]
        return <Route key={r.to} path={r.to} element={<Shell title={r.label}><Page key={r.to} /></Shell>} />
      })}
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <Routed />
      </AuthProvider>
    </ToastProvider>
  )
}
