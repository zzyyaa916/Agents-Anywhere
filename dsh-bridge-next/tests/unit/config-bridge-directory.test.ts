import assert from 'node:assert/strict'
import test from 'node:test'
import { join } from 'node:path'
import { userInfo } from 'node:os'
import { bridgeDirectory, Config } from '../../src/host/config.js'

test('bridgeDirectory keeps the per-user default when not configured', () => {
  const expected = join(userInfo().homedir, '.agents-anywhere', 'dsh-bridge')
  assert.equal(bridgeDirectory(), expected)
  assert.equal(bridgeDirectory({}), expected)
  assert.equal(bridgeDirectory({ bridgeDirectory: undefined }), expected)
})

test('a configured bridgeDirectory is used verbatim and must be absolute', () => {
  assert.equal(bridgeDirectory({ bridgeDirectory: '/home/aa-fork/.agents-anywhere/dsh-bridge' }), '/home/aa-fork/.agents-anywhere/dsh-bridge')
  assert.throws(() => bridgeDirectory({ bridgeDirectory: 'relative/dsh-bridge' }), /绝对路径/)
})

test('the plugin schema accepts bridgeDirectory and leaves it unset by default', () => {
  assert.equal(Config({}).bridgeDirectory, undefined)
  assert.equal(Config({ bridgeDirectory: '/srv/bridge' }).bridgeDirectory, '/srv/bridge')
})
