import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ENMS_ENERGY_COMPLEXITY_OPTIONS,
  normalizeEnmsEnergyComplexity,
  normalizeISOStandardCode,
  normalizeISOStandardCodes,
  qualificationScopeType,
} from './isoStandards'

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

test('recognizes EnMS qualification scope for every supported planner spelling', () => {
  for (const value of ['ENMS', 'EnMS', 'ISO 50001', 'ISO 50001:2018', 'ISO 50001 (ENMS)']) {
    assert.equal(qualificationScopeType(value), 'energy')
  }
})

test('provides and normalizes the EnMS energy-complexity categories', () => {
  assert.deepEqual(ENMS_ENERGY_COMPLEXITY_OPTIONS, ['Low', 'Medium', 'High'])
  assert.equal(normalizeEnmsEnergyComplexity('low'), 'Low')
  assert.equal(normalizeEnmsEnergyComplexity('Medium complexity'), 'Medium')
  assert.equal(normalizeEnmsEnergyComplexity('HIGH COMPLEXITY'), 'High')
  assert.equal(normalizeEnmsEnergyComplexity(''), '')
  assert.equal(normalizeEnmsEnergyComplexity('unknown'), '')
})
