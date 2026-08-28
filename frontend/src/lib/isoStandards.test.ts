import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeISOStandardCode, normalizeISOStandardCodes } from './isoStandards'

test('normalizes every supported full ISO label to the Certiv.AI code', () => {
  assert.deepEqual(normalizeISOStandardCodes([
    'ISO 9001:2015',
    'ISO 14001:2015',
    'ISO 45001:2018',
    'ISO 22000:2018',
    'ISO 13485:2016',
    'ISO/IEC 27001:2022',
    'ISO 37001:2016',
    'ISO 50001:2018',
  ]), ['QMS', 'EMS', 'OHSMS', 'FSMS', 'MDQMS', 'ISMS', 'ABMS', 'ENMS'])
})

test('supports short aliases, deduplicates, and rejects unknown standards', () => {
  assert.deepEqual(normalizeISOStandardCodes(['FSMS', 'ISO 22000', 'QMS']), ['FSMS', 'QMS'])
  assert.equal(normalizeISOStandardCode('unknown'), null)
})
