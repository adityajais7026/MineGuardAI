import DashboardPage from './pages/DashboardPage'
import AdminDashboardPage from './pages/admin/AdminDashboardPage'
import { useAuth } from './context/AuthContext'

/**
 * Landing route ("/").
 *
 * Platform administrators get the platform-administration overview; every
 * operational role keeps the mine-safety dashboard. Both read real data.
 */
export default function App() {
  const { user } = useAuth()
  return user?.role === 'admin' ? <AdminDashboardPage /> : <DashboardPage />
}
