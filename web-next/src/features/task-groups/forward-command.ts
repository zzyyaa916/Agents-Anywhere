export function parseForwardCommand(text: string, names: string[] = ["Claude Code", "Codex", "Claude", "DSH"]) {
  const prefix = /^转发给\s*/.exec(text.trim())
  if (!prefix) return null
  const rest = text.trim().slice(prefix[0].length)
  const known = [...names].sort((a, b) => b.length - a.length).find(name => rest.toLowerCase().startsWith(name.toLowerCase()) && /^(?:$|[\s，,：:；;。])/.test(rest.slice(name.length)))
  const match = known ? [rest, known, rest.slice(known.length).replace(/^[\s，,：:；;。]+/, "")] : /^([^\s，,：:；;。]+)(?:[\s，,：:；;。]+([\s\S]*))?$/.exec(rest)
  return match ? { target: match[1]!, instructions: match[2]?.trim() || "请审核当前代码和任务结果，指出问题及后续建议。" } : null
}
