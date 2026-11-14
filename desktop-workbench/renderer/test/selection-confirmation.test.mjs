import assert from 'node:assert/strict'
import test from 'node:test'
import { registerSource } from './helpers/onboarding-source.mjs'
const source = registerSource()
const { selectionConfirmation } = await import('../src/components/session/catalog-selection.ts')
source.deregister()

const translate = key => ({ 'reasoningModes.low': '低', modelAndReasoning: '模型和思考强度', permissionMode: '权限模式' }[key] ?? key)
const models = { runtime: 'claude', models: [{ id: 'fable', displayName: 'Fable 5.2', metadata: {}, group: null, selectionId: 'model', reasoningItems: [{ id: 'low', displayName: 'Low', metadata: {}, selectionId: 'fable-low' }] }] }
const permissions = { runtime: 'claude', permissions: [{ id: 'default', displayName: 'Ask permissions', metadata: {}, selectionId: 'ask' }] }
const confirmed = (requested, selections, metadata = {selection_effect: 'applied'}, modelCatalog = models) => selectionConfirmation('s', requested, { sessionId: 's', selections, metadata }, modelCatalog, permissions, translate)

test('confirmation includes the acknowledged model and exact effort', () => {
  assert.deepEqual(confirmed({model: 'fable-low'}, {model: 'fable-low'}), {label: 'Fable 5.2 · 低', pending: false})
})
test('unmatched or missing response cannot be called confirmed', () => {
  assert.equal(confirmed({model: 'fable-low'}, {model: 'old'}), null)
  assert.equal(selectionConfirmation('s', {model: 'fable-low'}, null, models, permissions, translate), null)
  assert.equal(confirmed({model: 'fable-low'}, {}), null)
})
test('a runtime accepted deferred switch explicitly applies next turn', () => {
  assert.deepEqual(confirmed({model: 'fable-low'}, {model: 'fable-low'}, {selection_effect: 'next_turn', pendingSelectionScopes: ['model']}), {label: 'Fable 5.2 · 低', pending: true})
})
test('another pending scope does not confirm a model switch', () => {
  assert.equal(confirmed({model: 'fable-low'}, {model: 'old'}, {pendingSelectionScopes: ['permission']}), null)
})
test('a combined update confirms every requested scope', () => {
  assert.equal(confirmed({model: 'fable-low', permission: 'ask'}, {model: 'fable-low', permission: 'old'}), null)
  assert.deepEqual(confirmed({model: 'fable-low', permission: 'ask'}, {model: 'fable-low', permission: 'ask'}), {label: 'Fable 5.2 · 低 · Ask permissions', pending: false})
})
test('missing catalog uses a readable label rather than an opaque selection token', () => {
  assert.deepEqual(confirmed({model: 'private-selection-token'}, {model: 'private-selection-token'}, {selection_effect: 'applied'}, null), {label: '模型和思考强度', pending: false})
})
test('an empty update is not a success notification', () => {
  assert.equal(confirmed({}, {}), null)
})

test('default model is never announced as confirmed', () => {
  assert.equal(confirmed({model: null}, {model: null}), null)
})

test('an echoed request without an effect signal is not confirmed', () => {
  assert.equal(confirmed({model: 'fable-low'}, {model: 'fable-low'}, {}), null)
})
test('another session cannot confirm this request', () => {
  assert.equal(selectionConfirmation('s', {model: 'fable-low'}, {sessionId: 'other', selections: {model: 'fable-low'}, metadata: {selection_effect: 'applied'}}, models, permissions, translate), null)
})
test('catalog aliases with the same model and effort compare semantically', () => {
  const aliases = {...models, models: [...models.models, {...models.models[0], reasoningItems: [{id:'low', displayName:'Low', metadata:{}, selectionId:'alias-low'}]}]}
  assert.deepEqual(confirmed({model: 'alias-low'}, {model: 'fable-low'}, {selection_effect: 'applied'}, aliases), {label:'Fable 5.2 · 低', pending:false})
})
