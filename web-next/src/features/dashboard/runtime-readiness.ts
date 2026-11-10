import type { ChannelRuntimeState } from "./types"

export function channelReadiness(channel?: Pick<ChannelRuntimeState, "state">): "channelUnknown" | "channelReady" | "channelFailed" | "channelWaiting" {
  if (!channel || channel.state === "unsupported") return "channelUnknown"
  if (channel.state === "applied") return "channelReady"
  if (channel.state === "failed" || channel.state === "restored") return "channelFailed"
  return "channelWaiting"
}

export function accountReadiness(snapshot?: { fetchedAt: string | null; stale: boolean; errorCode?: string | null }): "accountUnknown" | "accountStale" | "accountRecent" | "loginRequired" {
  if (snapshot?.errorCode === "account_unavailable") return "loginRequired"
  if (!snapshot?.fetchedAt) return "accountUnknown"
  return snapshot.stale || snapshot.errorCode ? "accountStale" : "accountRecent"
}
