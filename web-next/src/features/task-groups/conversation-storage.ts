export function conversationServer(session: unknown) {
  const server = session && typeof session === "object" && "serverUrl" in session ? session.serverUrl : undefined
  return typeof server === "string" ? server : process.env.NEXT_PUBLIC_AGENTS_ANYWHERE_API || (typeof window === "undefined" ? "" : window.location.origin)
}

export function conversationScope(userId: string, server: string) {
  return `aa-conversations:${JSON.stringify([server, userId])}`
}

export function readConversationState(key: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(key) ?? "null")
    return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}
  } catch { return {} }
}

export function writeConversationState(key: string, value: unknown) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); return true } catch { return false }
}
