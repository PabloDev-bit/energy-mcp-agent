import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Les appels à /api/... sont redirigés vers l'API FastAPI (port 8000) :
// le navigateur ne parle qu'à Vite, donc pas de problème de CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
