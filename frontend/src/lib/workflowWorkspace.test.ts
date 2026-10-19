import assert from 'node:assert/strict'
import test from 'node:test'
import { activePlannerDocumentTypes } from './workflowWorkspace'

test('new initial applications expose FR.218 before commercial documents', () => {
  assert.deepEqual(activePlannerDocumentTypes({
    workflowStatus: 'in_planning', auditType: 'initial', workflowVersion: 2, isTransfer: false,
  }), ['fr218_review'])
  assert.deepEqual(activePlannerDocumentTypes({
    workflowStatus: 'fr218_complete', auditType: 'initial', workflowVersion: 2, isTransfer: false,
  }), ['quotation'])
})

test('legacy initial applications retain their established order', () => {
  assert.deepEqual(activePlannerDocumentTypes({
    workflowStatus: 'in_planning', auditType: 'initial', workflowVersion: 1, isTransfer: false,
  }), ['quotation'])
  assert.deepEqual(activePlannerDocumentTypes({
    workflowStatus: 'agreement_signed', auditType: 'initial', workflowVersion: 1, isTransfer: false,
  }), ['fr218_review'])
})

test('ordinary surveillance shows only the notification during planning', () => {
  assert.deepEqual(activePlannerDocumentTypes({
    workflowStatus: 'in_planning', auditType: 'surveillance_1', workflowVersion: 2, isTransfer: false,
  }), ['surveillance_notification'])
})

test('transfer surveillance uses the transfer and certification document flow', () => {
  assert.deepEqual(activePlannerDocumentTypes({
    workflowStatus: 'in_planning', auditType: 'surveillance_1', workflowVersion: 2, isTransfer: true,
  }), ['transfer_review', 'fr218_review'])
  assert.deepEqual(activePlannerDocumentTypes({
    workflowStatus: 'quotation_sent', auditType: 'surveillance_1', workflowVersion: 2, isTransfer: true,
  }), ['agreement'])
})

test('future-stage documents are absent from early phases', () => {
  const types = activePlannerDocumentTypes({
    workflowStatus: 'fr218_complete', auditType: 'recertification', workflowVersion: 2, isTransfer: false,
  })
  assert.deepEqual(types, ['quotation'])
  assert.equal(types.includes('review_decision'), false)
  assert.equal(types.includes('certificate'), false)
})

test('FR.218 signature phase does not offer a duplicate upload', () => {
  assert.deepEqual(activePlannerDocumentTypes({
    workflowStatus: 'fr218_in_progress', auditType: 'initial', workflowVersion: 2, isTransfer: false,
  }), [])
})
