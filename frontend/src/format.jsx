// Mise en forme légère des réponses de l'agent : **gras**, listes "- " et "1. "

function inline(text, keyPrefix) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>
    ) : (
      part
    ),
  )
}

export function FormattedText({ text }) {
  const blocks = []
  let list = null

  text.split('\n').forEach((raw, i) => {
    const line = raw.trimEnd()
    const bullet = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/)

    if (bullet) {
      if (!list) {
        list = { ordered: /^\s*\d+\./.test(line), items: [] }
        blocks.push(list)
      }
      list.items.push(inline(bullet[1], `li-${i}`))
      return
    }

    list = null
    if (line.trim()) blocks.push(<p key={`p-${i}`}>{inline(line, `p-${i}`)}</p>)
  })

  return blocks.map((block, i) => {
    if (block.items) {
      const Tag = block.ordered ? 'ol' : 'ul'
      return (
        <Tag key={`l-${i}`}>
          {block.items.map((item, j) => (
            <li key={j}>{item}</li>
          ))}
        </Tag>
      )
    }
    return block
  })
}
