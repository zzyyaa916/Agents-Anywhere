import test from 'node:test'
import assert from 'node:assert/strict'
import { channelReadiness, accountReadiness } from '../src/features/dashboard/runtime-readiness.ts'

test('process readiness does not imply a reconciled channel or a verified account', () => {
  assert.equal(channelReadiness(), 'channelUnknown')
  assert.equal(channelReadiness({state: 'applied'}), 'channelReady')
  for (const state of ['failed', 'restored']) assert.equal(channelReadiness({state}), 'channelFailed')
  for (const state of ['pending', 'switching', 'restoring', 'waiting_online']) assert.equal(channelReadiness({state}), 'channelWaiting')
  assert.equal(accountReadiness(), 'accountUnknown')
  assert.equal(accountReadiness({fetchedAt: null, stale: false}), 'accountUnknown')
  assert.equal(accountReadiness({fetchedAt: '2026-01-01', stale: true}), 'accountStale')
  assert.equal(accountReadiness({fetchedAt: '2026-01-01', stale: false}), 'accountRecent')
  assert.equal(accountReadiness({fetchedAt: '2026-01-01', stale: false, errorCode: 'account_unavailable'}), 'loginRequired')
})
