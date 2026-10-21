import test from 'node:test'
import assert from 'node:assert/strict'

import { isTransientApiFailure, retryTransientApiRequest } from './apiRetry'

test('classifies network and gateway failures as transient', () => {
  assert.equal(isTransientApiFailure({ code: 'ERR_NETWORK', message: 'Network Error' }), true)
  assert.equal(isTransientApiFailure({ response: { status: 503 } }), true)
  assert.equal(isTransientApiFailure({ response: { status: 422 } }), false)
})

test('retries transient failures and eventually returns the response', async () => {
  let calls = 0
  const retryAttempts: number[] = []

  const result = await retryTransientApiRequest(async () => {
    calls += 1
    if (calls < 3) throw { code: 'ERR_NETWORK', message: 'Network Error' }
    return 'generated'
  }, {
    retries: 2,
    onRetry: (_error, attempt) => retryAttempts.push(attempt),
    wait: async () => undefined,
  })

  assert.equal(result, 'generated')
  assert.equal(calls, 3)
  assert.deepEqual(retryAttempts, [1, 2])
})

test('does not retry validation or other non-transient responses', async () => {
  let calls = 0

  await assert.rejects(
    retryTransientApiRequest(async () => {
      calls += 1
      throw { response: { status: 422 } }
    }, {
      retries: 2,
      wait: async () => undefined,
    }),
  )

  assert.equal(calls, 1)
})
