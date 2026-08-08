import axios from 'axios'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '../utils/tokenStorage'

const api = axios.create({ baseURL: '/api' })

// Attach access token to every request
api.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Auto-refresh on 401
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status === 401 && !error.config._retry) {
      const requestUrl = String(error.config?.url || '')
      // Authentication forms own their errors; redirecting here erases the
      // useful message before the login screen can render it.
      if (requestUrl.includes('/auth/login') || requestUrl.includes('/auth/refresh')) {
        return Promise.reject(error)
      }
      error.config._retry = true
      const refresh = getRefreshToken()
      if (!refresh) {
        clearTokens()
        window.location.href = '/login'
        return Promise.reject(error)
      }
      try {
        const { data } = await axios.post('/api/auth/refresh', { refresh_token: refresh })
        setTokens(data.access_token, data.refresh_token)
        error.config.headers.Authorization = `Bearer ${data.access_token}`
        return api(error.config)
      } catch {
        clearTokens()
        window.location.href = '/login'
        return Promise.reject(error)
      }
    }
    return Promise.reject(error)
  }
)

export default api
