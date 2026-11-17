import { useState } from 'react'
import { FormattedText } from './format.jsx'

const TOOL_LABELS = {
  run_query: 'Requête SQL sur la base',
  get_schema: 'Lecture du schéma',
  get_live_mix: 'Mix RTE en direct',
  get_weather_forecast: 'Prévisions Open-Meteo',
  get_data_coverage: 'Couverture de la base',
}

function ToolCalls({ calls }) {
  const [open, setOpen] = useState(false)
  if (!calls?.length) return null

  return (
    <div className="tools">
      <button className="tools-toggle" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} {calls.length} outil{calls.length > 1 ? 's' : ''} MCP utilisé
        {calls.length > 1 ? 's' : ''} : {calls.map((c) => TOOL_LABELS[c.name] || c.name).join(', ')}
      </button>
      {open &&
        calls.map((call, i) => (
          <div key={i} className="tool-call">
            <span className="tool-name">{call.name}</span>
            {call.args.sql ? (
              <pre>{call.args.sql}</pre>
            ) : (
              Object.keys(call.args).length > 0 && <pre>{JSON.stringify(call.args, null, 2)}</pre>
            )}
          </div>
        ))}
    </div>
  )
}

export default function Message({ message }) {
  if (message.role === 'user') {
    return (
      <div className="message user">
        <div className="bubble">{message.content}</div>
      </div>
    )
  }

  return (
    <div className={`message assistant ${message.error ? 'error' : ''}`}>
      <div className="avatar">⚡</div>
      <div className="bubble">
        <FormattedText text={message.content} />
        <ToolCalls calls={message.toolCalls} />
        {message.seconds && <div className="meta">Répondu en {message.seconds} s</div>}
      </div>
    </div>
  )
}
