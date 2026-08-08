import assert from 'node:assert/strict'
import test from 'node:test'

import {
  auditorShouldRenderForRequiredScope,
  authoritativeCoverageLabel,
  computeStageCoverage,
  normalizeScopeCode,
  normalizeScopeType,
  normalizeStandardKey,
  type AvailableAuditor,
} from './stageCoverage'


function auditor(
  id: string,
  name: string,
  coveredScope: Record<string, string[]>,
  standardCodes = Object.keys(coveredScope),
): AvailableAuditor {
  return {
    id,
    name,
    covered_scope: coveredScope,
    standard_qualifications: standardCodes.map((standard_code) => ({
      standard_code,
      accreditation_body: 'UAF',
      technical_depth: 'Team Auditor',
      ea_codes: coveredScope[standard_code] ?? [],
      scope_category: null,
    })),
  }
}


test('lead and additional auditor collectively cover separate required codes', () => {
  const available = [
    auditor('lead', 'Lead Auditor', { 'ISO 9001': ['EA 29'] }),
    auditor('additional', 'Additional Auditor', { 'ISO 9001': ['23'] }),
  ]

  const result = computeStageCoverage(
    ['ISO 9001'],
    null,
    {
      leadAuditor: { id: 'lead', name: 'Lead Auditor' },
      auditors: [{ id: 'additional', name: 'Additional Auditor' }],
    },
    available,
    { 'ISO 9001': { type: 'ea', codes: ['EA 23', 'EA 29'] } },
  )

  assert.equal(result[0].covered, true)
  assert.deepEqual(result[0].codeResults, [
    { code: 'EA 23', coveredBy: 'Additional Auditor' },
    { code: 'EA 29', coveredBy: 'Lead Auditor' },
  ])
})


test('saved additional auditor resolves after reload with a stale legacy id', () => {
  const result = computeStageCoverage(
    ['ISO 9001'],
    null,
    { auditors: [{ id: 'legacy-user-id', name: 'Additional Auditor' }] },
    [auditor('auditor-profile-id', 'Additional Auditor', { 'ISO 9001': ['EA 23'] })],
    { 'ISO 9001': { type: 'ea', codes: ['23'] } },
  )

  assert.equal(result[0].covered, true)
  assert.equal(result[0].codeResults?.[0].coveredBy, 'Additional Auditor')
})


test('EA numeric and prefixed formats compare identically', () => {
  assert.equal(normalizeScopeCode('23', 'ea'), normalizeScopeCode('EA 23', 'ea'))
  assert.equal(normalizeScopeCode('EA23', 'ea'), normalizeScopeCode('IAF 23', 'ea'))
})


test('legacy MDQMS type and dotted technical area match current auditor category', () => {
  assert.equal(normalizeScopeType('medical_tas'), 'medical')
  assert.equal(
    normalizeScopeCode('A.1.1', 'medical_tas'),
    normalizeScopeCode('A1.1', 'medical'),
  )

  const result = computeStageCoverage(
    ['MDQMS'],
    null,
    { leadAuditor: { id: 'mdqms', name: 'MDQMS Auditor' } },
    [auditor('mdqms', 'MDQMS Auditor', { 'ISO 13485': ['A1.1'] }, ['ISO 13485'])],
    { 'ISO 13485': { type: 'medical_tas', codes: ['A.1.1'] } },
  )

  assert.equal(result[0].covered, true)
  assert.equal(result[0].codeResults?.[0].coveredBy, 'MDQMS Auditor')
})


test('a code from another standard does not cover ISO 9001', () => {
  const result = computeStageCoverage(
    ['ISO 9001'],
    null,
    { auditors: [{ id: 'auditor', name: 'Auditor' }] },
    [auditor('auditor', 'Auditor', { 'ISO 14001': ['EA 23'] })],
    { 'ISO 9001': { type: 'ea', codes: ['EA 23'] } },
  )

  assert.equal(result[0].covered, false)
})


test('observers and trainees do not contribute to stage coverage', () => {
  const available = [
    auditor('observer', 'Observer', { 'ISO 9001': ['EA 23'] }),
    auditor('trainee', 'Trainee', { 'ISO 9001': ['EA 29'] }),
  ]
  const result = computeStageCoverage(
    ['ISO 9001'],
    null,
    {
      observers: [{ id: 'observer', name: 'Observer' }],
      trainees: [{ id: 'trainee', name: 'Trainee' }],
    },
    available,
    { 'ISO 9001': { type: 'ea', codes: ['EA 23', 'EA 29'] } },
  )

  assert.equal(result[0].covered, false)
  assert.ok(result[0].codeResults?.every((entry) => entry.coveredBy === null))
})


test('integrated standards are evaluated independently', () => {
  const available = [
    auditor('qms', 'QMS Auditor', { 'ISO 9001:2015': ['EA 23'] }),
    auditor('ems', 'EMS Auditor', { EMS: ['EA 29'] }),
  ]
  const result = computeStageCoverage(
    ['ISO 9001', 'ISO 14001'],
    null,
    {
      auditors: [
        { id: 'qms', name: 'QMS Auditor' },
        { id: 'ems', name: 'EMS Auditor' },
      ],
    },
    available,
    {
      QMS: { type: 'ea', codes: ['23'] },
      'ISO 14001:2015': { type: 'ea', codes: ['EA 29'] },
    },
  )

  assert.deepEqual(result.map((entry) => entry.covered), [true, true])
  assert.equal(normalizeStandardKey('QMS'), normalizeStandardKey('ISO 9001:2015'))
})


test('technical experts contribute only through the exact standard coverage', () => {
  const result = computeStageCoverage(
    ['ISO 9001', 'ISO 14001'],
    null,
    { technicalExperts: [{ id: 'te', name: 'Technical Expert' }] },
    [auditor('te', 'Technical Expert', { 'ISO 9001': ['EA 23'] })],
    {
      'ISO 9001': { type: 'ea', codes: ['EA 23'] },
      'ISO 14001': { type: 'ea', codes: ['EA 23'] },
    },
  )

  assert.equal(result[0].codeResults?.[0].coveredBy, 'Technical Expert (TE)')
  assert.equal(result[1].covered, false)
})


test('selected chip label is generated from the same covered_scope as coverage', () => {
  const member = { id: 'auditor', name: 'Auditor', ea_code: 'EA 99' }
  const available = [
    auditor('auditor', 'Auditor', { 'ISO 9001': ['EA 23'] }),
  ]

  assert.equal(
    authoritativeCoverageLabel(member, available),
    'EA 23 (ISO 9001)',
  )
  const coverage = computeStageCoverage(
    ['ISO 9001'],
    null,
    { auditors: [member] },
    available,
    { 'ISO 9001': { type: 'ea', codes: ['EA 23'] } },
  )
  assert.equal(coverage[0].covered, true)
})


test('legacy ENMS auditor remains renderable without false complexity coverage', () => {
  const legacyEnmsAuditor = auditor(
    'enms',
    'ENMS Auditor',
    {},
    ['ENMS'],
  )
  const requiredScope = {
    'ISO 50001': { type: 'energy', codes: ['High'] },
  }

  assert.equal(
    auditorShouldRenderForRequiredScope(legacyEnmsAuditor, requiredScope),
    true,
  )
  assert.equal(
    authoritativeCoverageLabel(
      { id: 'enms', name: 'ENMS Auditor' },
      [legacyEnmsAuditor],
    ),
    'ENMS qualified · required scope not covered',
  )
  const coverage = computeStageCoverage(
    ['ISO 50001'],
    null,
    { leadAuditor: { id: 'enms', name: 'ENMS Auditor' } },
    [legacyEnmsAuditor],
    requiredScope,
  )
  assert.equal(coverage[0].covered, false)
})
