import { useAuth } from '../context/AuthContext'
import { PageHeader, Badge } from '../components/ui'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrator',
  mine_manager: 'Mine Manager',
  safety_officer: 'Safety Officer',
  environmental_officer: 'Environmental Officer',
}

export default function ProfilePage() {
  const { user, logout } = useAuth()
  if (!user) return null

  return (
    <div className="page">
      <PageHeader title="Profile" subtitle="Your MineGuardAI account" />
      <div className="card profile-card">
        <div className="avatar avatar-lg">{user.full_name.charAt(0)}</div>
        <h2>{user.full_name}</h2>
        <p><code>{user.email}</code></p>
        <p><Badge text={ROLE_LABEL[user.role] ?? user.role} tone="info" /></p>
        <p className="muted">Member since {new Date(user.created_at).toLocaleDateString()}</p>
        <button className="btn" onClick={logout}>Log out</button>
      </div>
      <p className="simulated-note">
        Authentication currently uses backend-issued JWTs. Supabase Auth adapter can be enabled
        once Supabase credentials are configured (see README).
      </p>
    </div>
  )
}
