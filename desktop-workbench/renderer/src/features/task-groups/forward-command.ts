const defaultInstructions = "请审核当前任务结果，指出问题及后续建议。"

export function parseForwardCommand(text: string, names: string[] = ["Claude Code", "Codex", "Claude", "DSH"]) {
  const prefix = /^转发给\s*/.exec(text.trim())
  if (!prefix) return null
  const rest = text.trim().slice(prefix[0].length)
  const colon = rest.search(/[：:]/)
  let targets: string[] = []
  let instructions = ""
  if (colon >= 0) {
    targets = rest.slice(0, colon).split(/[、，,]/).map(name => name.trim()).filter(Boolean)
    instructions = rest.slice(colon + 1).trim()
  } else {
    let remaining = rest
    const ordered = [...names].sort((a, b) => b.length - a.length)
    while (remaining) {
      const known = ordered.find(name => remaining.toLowerCase().startsWith(name.toLowerCase()) && /^(?:$|[\s、，,；;。])/.test(remaining.slice(name.length)))
      if (!known) {
        if (targets.length) {
          const unknown = /^([^\s、，,；;。]+)(?:[\s；;。]+([\s\S]*))?$/.exec(remaining)
          if (unknown) { targets.push(unknown[1]!); remaining = unknown[2] ?? "" }
        }
        break
      }
      targets.push(known)
      remaining = remaining.slice(known.length)
      const separator = /^\s*[、，,]\s*/.exec(remaining)
      if (!separator) break
      remaining = remaining.slice(separator[0].length)
    }
    if (!targets.length) {
      const match = /^([^\s、，,；;。]+)(?:[\s；;。]+([\s\S]*))?$/.exec(rest)
      if (!match) return null
      targets = [match[1]!]
      instructions = match[2]?.trim() ?? ""
    } else instructions = remaining.replace(/^[\s；;。]+/, "").trim()
  }
  if (!targets.length) return null
  return { targets, instructions: instructions || defaultInstructions }
}
