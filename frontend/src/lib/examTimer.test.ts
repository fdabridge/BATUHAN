import assert from 'node:assert/strict'
import test from 'node:test'

import { examRemainingSeconds } from './examTimer'


test('naive API timestamps are interpreted as UTC instead of browser local time', () => {
  assert.equal(
    examRemainingSeconds({
      server_now: '2026-07-29T08:00:00',
      exam_due_at: '2026-07-29T08:30:00',
    }),
    30 * 60,
  )
})


test('server-authoritative remaining time takes precedence over client clock', () => {
  assert.equal(
    examRemainingSeconds({
      remaining_seconds: 1799.2,
      server_now: '2026-07-29T08:00:00Z',
      exam_due_at: '2020-01-01T00:00:00Z',
    }, Date.parse('2035-01-01T00:00:00Z')),
    1800,
  )
})


test('untimed exams return no countdown', () => {
  assert.equal(examRemainingSeconds({ remaining_seconds: null, exam_due_at: null }), null)
})
