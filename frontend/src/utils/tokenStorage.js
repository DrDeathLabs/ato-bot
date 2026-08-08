const ACCESS_KEY = 'access_token'
const REFRESH_KEY = 'refresh_token'

function migrateLegacyToken(key) {
  const legacy = localStorage.getItem(key)
  if (legacy && !sessionStorage.getItem(key)) {
    sessionStorage.setItem(key, legacy)
  }
  if (legacy) {
    localStorage.removeItem(key)
  }
}

export function getAccessToken() {
  migrateLegacyToken(ACCESS_KEY)
  return sessionStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken() {
  migrateLegacyToken(REFRESH_KEY)
  return sessionStorage.getItem(REFRESH_KEY)
}

export function setTokens(accessToken, refreshToken) {
  if (accessToken) sessionStorage.setItem(ACCESS_KEY, accessToken)
  if (refreshToken) sessionStorage.setItem(REFRESH_KEY, refreshToken)
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

export function clearTokens() {
  sessionStorage.removeItem(ACCESS_KEY)
  sessionStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}
