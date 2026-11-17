// Appels à l'API FastAPI (via le proxy Vite : /api -> http://127.0.0.1:8000)

async function request(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
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
