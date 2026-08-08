import { Navigate, Outlet } from 'react-router-dom'
import { getAccessToken } from '../utils/tokenStorage'

export default function ProtectedRoute({ requiredRole }) {
  const token = getAccessToken()
  if (!token) return <Navigate to="/login" replace />

  if (requiredRole) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      const ROLE_LEVELS = {
        viewer: 0, system_owner: 1, reviewer: 2,
        assessor: 3, security_officer: 4, system_admin: 5,
      }
      if ((ROLE_LEVELS[payload.role] ?? -1) < (ROLE_LEVELS[requiredRole] ?? 99)) {
        return <Navigate to="/projects" replace />
      }
    } catch {
      return <Navigate to="/login" replace />
    }
  }

  return <Outlet />
}
