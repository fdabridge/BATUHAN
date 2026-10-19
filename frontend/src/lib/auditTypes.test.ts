import assert from 'node:assert/strict'
import test from 'node:test'
import {
  auditTypeLabel,
  isSurveillanceWorkflowAudit,
  reportStageForAuditType,
} from './auditTypes'

for (const auditType of [
  'surveillance_1',
  'surveillance_2',
  'scope_extension',
  'surveillance_1_scope_extension',
]) {
  test(`${auditType} uses the surveillance workflow`, () => {
    assert.equal(isSurveillanceWorkflowAudit(auditType), true)
  })
}

test('keeps standalone and combined scope-extension labels distinct', () => {
  assert.equal(auditTypeLabel('scope_extension'), 'Scope Extension')
  assert.equal(auditTypeLabel('surveillance_1_scope_extension'), 'Surveillance 1 + Scope Extension')
})

test('maps both scope-extension choices to Surveillance 1 report clauses', () => {
  assert.equal(reportStageForAuditType('scope_extension'), 'Surveillance 1')
  assert.equal(reportStageForAuditType('surveillance_1_scope_extension'), 'Surveillance 1')
})
