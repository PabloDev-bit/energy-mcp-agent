// Appels à l'API FastAPI.
// - En local : /api, redirigé par le proxy Vite vers http://127.0.0.1:8000
// - En ligne (Vercel) : l'adresse publique de l'API, définie dans VITE_API_URL
const BASE_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')

async function request(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      // Évite la page d'avertissement de ngrok sur l'offre gratuite
      'ngrok-skip-browser-warning': 'true',
      ...options.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `Erreur HTTP ${response.status}`)
  }
  return response.json()
}

export const getHealth = () => request('/health')
export const getTools = () => request('/tools')

export const ask = (question, history) =>
  request('/ask', {
    method: 'POST',
    body: JSON.stringify({ question, history }),
  })
