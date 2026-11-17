import { useEffect, useRef, useState } from 'react'
import { ask, getHealth, getTools } from './api.js'
import Message from './Message.jsx'

const SUGGESTIONS = [
  'Quel est le mix électrique en ce moment ?',
  'Quels ont été les 3 jours les plus venteux et la production éolienne ces jours-là ?',
  'Quelle est la part du nucléaire en août ?',
  'Quel temps est prévu à Bordeaux demain ?',
]

export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState({ state: 'checking' })
  const [tools, setTools] = useState([])
  const endRef = useRef(null)
  const inputRef = useRef(null)

  // Vérifie que l'API répond et récupère la liste des outils MCP
  useEffect(() => {
    getHealth()
      .then((h) => setStatus({ state: 'ok', model: h.model }))
      .catch(() => setStatus({ state: 'down' }))
    getTools().then(setTools).catch(() => setTools([]))
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // La zone de saisie grandit avec le texte (jusqu'à ~5 lignes)
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  }, [input])

  async function send(question) {
    const text = question.trim()
    if (!text || loading) return

    // Historique envoyé à l'agent (sans les messages d'erreur)
    const history = messages
      .filter((m) => !m.error)
      .map(({ role, content }) => ({ role, content }))

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setLoading(true)
    const start = performance.now()

    try {
      const data = await ask(text, history)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.answer,
          toolCalls: data.tool_calls,
          seconds: ((performance.now() - start) / 1000).toFixed(1),
        },
      ])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Erreur : ${err.message}`, error: true },
      ])
    } finally {
      setLoading(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  return (
    <div className="app">
      <div className="backdrop" aria-hidden="true">
        <div className="glow" />
        <div className="dots" />
        <div className="grain" />
      </div>

      <header>
        <div className="brand">
          <span className="logo">⚡</span>
          <div>
            <h1>Energy MCP Agent</h1>
            <p className="hide-mobile">Électricité &amp; météo en France · RTE éCO2mix + Open-Meteo</p>
          </div>
        </div>
        <div className="header-right">
          <div className={`status ${status.state}`}>
            <span className="dot" />
            {status.state === 'ok' && (
              <>
                <span className="hide-mobile">{status.model} · </span>
                {tools.length} outils MCP
              </>
            )}
            {status.state === 'checking' && 'Connexion…'}
            {status.state === 'down' && 'API hors ligne'}
          </div>
          <a className="credit-btn" href="https://pablopro.dev" target="_blank" rel="noreferrer">
            <span className="hide-mobile">pablopro.dev </span>↗
          </a>
        </div>
      </header>

      <main>
        {messages.length === 0 ? (
          <div className="empty">
            <span className="eyebrow">Agent IA · MCP · LangGraph</span>
            <h2>
              Pose une question
              <br />
              <span>sur l'énergie en France</span>
            </h2>
            <p>
              L'agent choisit lui-même ses outils : requêtes SQL sur l'historique, mix
              électrique en direct ou prévisions météo.
            </p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)} disabled={status.state === 'down'}>
                  {s}
                </button>
              ))}
            </div>
            {status.state === 'down' && (
              <p className="hint">
                Lance l'API d'abord : <code>uvicorn backend.main:app --reload</code>
              </p>
            )}
          </div>
        ) : (
          <div className="messages">
            {messages.map((m, i) => (
              <Message key={i} message={m} />
            ))}
            {loading && (
              <div className="message assistant">
                <div className="avatar">⚡</div>
                <div className="bubble typing">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        )}
      </main>

      <footer>
        <div className="composer">
          <textarea
            ref={inputRef}
            rows={1}
            enterKeyHint="send"
            value={input}
            placeholder="Pose ta question sur l'énergie…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={loading}
          />
          <button onClick={() => send(input)} disabled={loading || !input.trim()} aria-label="Envoyer">
            <span className="hide-mobile">Envoyer</span>
            <span className="show-mobile">➤</span>
          </button>
        </div>
        <div className="footer-row">
          {messages.length > 0 ? (
            <button className="reset" onClick={() => setMessages([])} disabled={loading}>
              ↺ Nouvelle conversation
            </button>
          ) : (
            <span className="footer-note">Modèle local via Ollama · aucune donnée envoyée à un service d'IA externe</span>
          )}
          <a className="credit" href="https://pablopro.dev" target="_blank" rel="noreferrer">
            Développé par <strong>pablopro.dev</strong>
          </a>
        </div>
      </footer>
    </div>
  )
}
