export function parseForwardCommand(text: string) {
  const match = /^转发给\s*([^\s，,：:；;。]+)(?:[\s，,：:；;。]+([\s\S]*))?$/.exec(text.trim())
  return match ? { target: match[1]!, instructions: match[2]?.trim() || "请审核当前代码和任务结果，指出问题及后续建议。" } : null
}
