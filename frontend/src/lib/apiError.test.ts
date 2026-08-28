import test from 'node:test'
import assert from 'node:assert/strict'

import { apiErrorMessage } from './apiError'

test('extracts FastAPI detail from a Blob error response', async () => {
  const error = {
    response: {
      status: 422,
      data: new Blob([JSON.stringify({ detail: 'Schedule could not be completed.' })]),
    },
  }
  assert.equal(await apiErrorMessage(error), 'Schedule could not be completed.')
})

test('formats FastAPI validation details', async () => {
  const error = {
    response: {
      status: 422,
      data: { detail: [{ loc: ['body', 'day_windows'], msg: 'Field required' }] },
    },
  }
  assert.equal(await apiErrorMessage(error), 'body.day_windows: Field required')
})

test('reports gateway status without rendering an HTML error page', async () => {
  const error = {
    response: {
      status: 502,
      data: new Blob(['<html><body>Bad gateway</body></html>']),
    },
  }
  assert.equal(
    await apiErrorMessage(error, undefined, 'audit-plan service'),
    'The audit-plan service returned HTTP 502. Please try again.',
  )
})

test('turns an Axios network failure into an actionable message', async () => {
  assert.equal(
    await apiErrorMessage({ message: 'Network Error' }, undefined, 'audit-plan service'),
    'Could not reach the audit-plan service. Please check the connection and try again.',
  )
})
