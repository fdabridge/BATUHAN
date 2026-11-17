import assert from 'node:assert/strict'
import test from 'node:test'

import {
  auditPlanSubmissionFingerprint,
  resolveAuditPlanRequest,
} from './auditPlanSubmission'

test('fingerprint is stable and changes with the audit inputs', () => {
  const first = auditPlanSubmissionFingerprint('{"standard":"QMS"}')
  assert.equal(first, auditPlanSubmissionFingerprint('{"standard":"QMS"}'))
  assert.notEqual(first, auditPlanSubmissionFingerprint('{"standard":"EMS"}'))
})

test('a retry reuses its request id but changed inputs create a new one', () => {
  const first = resolveAuditPlanRequest(null, 'form-a', () => 'request-1')
  const retry = resolveAuditPlanRequest(first.storageValue, 'form-a', () => 'request-2')
  const changed = resolveAuditPlanRequest(first.storageValue, 'form-b', () => 'request-2')

  assert.equal(retry.requestId, 'request-1')
  assert.equal(changed.requestId, 'request-2')
})
