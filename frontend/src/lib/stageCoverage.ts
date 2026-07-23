export interface StageTeamMember {
  id?: string | null
  name: string
}

export interface StageTeamAssignments {
  leadAuditor?: StageTeamMember | null
  auditors?: StageTeamMember[]
  technicalExperts?: StageTeamMember[]
  observers?: StageTeamMember[]
  trainees?: StageTeamMember[]
}

export interface AvailabilityQualification {
  standard_code: string
  accreditation_body?: string | null
  technical_depth?: string | null
  ea_codes?: string[]
  scope_category?: string | null
}

export interface AvailableAuditor {
  id: string
  name: string
  standard_qualifications: AvailabilityQualification[]
  covered_scope?: Record<string, string[]>
}

export interface StageRequiredScopeEntry {
  type: string
  codes: string[]
}

export type StageRequiredScope = Record<string, StageRequiredScopeEntry>

export interface StageCoverageResult {
  standard: string
  covered: boolean
  coveredBy: string | null
  reason: string | null
  codeResults?: { code: string; coveredBy: string | null }[]
}

const STANDARD_ALIASES: Record<string, string> = {
  qms: '9001',
  ems: '14001',
  ohsms: '45001',
  fsms: '22000',
  isms: '27001',
  enms: '50001',
  abms: '37001',
  cms: '37301',
  mdqms: '13485',
  mdms: '13485',
}

const STANDARD_NUMBERS = ['9001', '14001', '45001', '22000', '27001', '50001', '37001', '37301', '13485']
const EA_CODE_STANDARDS = new Set(['9001', '14001', '45001'])

export function normalizeStandardKey(value: string): string {
  const raw = (value ?? '').trim().toLowerCase()
  const compact = raw.replace(/[^a-z0-9]/g, '')
  if (compact.startsWith('fssc')) return 'fssc22000'
  if (STANDARD_ALIASES[compact]) return STANDARD_ALIASES[compact]
  const number = STANDARD_NUMBERS.find((candidate) => {
    const match = raw.match(new RegExp(`(^|\\D)${candidate}(\\D|$)`))
    return !!match
  })
  return number ?? compact
}

export function normalizeScopeCode(value: string, scopeType = 'ea'): string {
  const raw = (value ?? '').trim().toUpperCase()
  if (scopeType === 'ea') {
    const match = raw.match(/^(?:EA|IAF)?\s*0*(\d+)$/)
    if (match) return `EA:${Number(match[1])}`
  }
  return raw.replace(/\s+/g, '')
}

function normalizePersonName(value: string | null | undefined): string {
  return (value ?? '').trim().toLocaleLowerCase()
}

export function findAuditorForTeamMember<T extends AvailableAuditor>(
  member: StageTeamMember,
  availableAuditors: T[],
): T | null {
  if (member.id) {
    const exact = availableAuditors.find((auditor) => auditor.id === member.id)
    if (exact) return exact
  }
  const normalizedName = normalizePersonName(member.name)
  if (!normalizedName) return null
  const nameMatches = availableAuditors.filter(
    (auditor) => normalizePersonName(auditor.name) === normalizedName,
  )
  return nameMatches.length === 1 ? nameMatches[0] : null
}

export function eligibleStageTeam(assignments: StageTeamAssignments): StageTeamMember[] {
  return [
    ...(assignments.leadAuditor ? [assignments.leadAuditor] : []),
    ...(assignments.auditors ?? []),
    ...(assignments.technicalExperts ?? []),
  ]
}

function resolvedTeamAuditors<T extends AvailableAuditor>(
  assignments: StageTeamAssignments,
  availableAuditors: T[],
): T[] {
  const resolved: T[] = []
  for (const member of eligibleStageTeam(assignments)) {
    const auditor = findAuditorForTeamMember(member, availableAuditors)
    if (auditor && !resolved.some((current) => current.id === auditor.id)) {
      resolved.push(auditor)
    }
  }
  return resolved
}

function requiredScopeEntry(
  requiredScope: StageRequiredScope | null | undefined,
  standard: string,
): StageRequiredScopeEntry | null {
  if (!requiredScope) return null
  if (requiredScope[standard]) return requiredScope[standard]
  const target = normalizeStandardKey(standard)
  const match = Object.entries(requiredScope).find(
    ([key]) => normalizeStandardKey(key) === target,
  )
  return match?.[1] ?? null
}

function coveredCodesForStandard(
  coveredScope: Record<string, string[]> | undefined,
  standard: string,
): string[] {
  if (!coveredScope) return []
  if (coveredScope[standard]) return coveredScope[standard]
  const target = normalizeStandardKey(standard)
  const match = Object.entries(coveredScope).find(
    ([key]) => normalizeStandardKey(key) === target,
  )
  return match?.[1] ?? []
}

function codeListIncludes(
  codes: string[] | undefined,
  code: string,
  scopeType: string,
): boolean {
  const target = normalizeScopeCode(code, scopeType)
  return (codes ?? []).some(
    (candidate) => normalizeScopeCode(candidate, scopeType) === target,
  )
}

function qualificationForStandard(
  auditor: AvailableAuditor,
  standard: string,
): AvailabilityQualification[] {
  const target = normalizeStandardKey(standard)
  return auditor.standard_qualifications.filter(
    (qualification) => normalizeStandardKey(qualification.standard_code) === target,
  )
}

function labelName(
  name: string | null,
  technicalExpertNames: Set<string>,
): string | null {
  return name && technicalExpertNames.has(name) ? `${name} (TE)` : name
}

export function computeStageCoverage(
  requiredStandards: string[],
  clientEACode: string | null,
  assignments: StageTeamAssignments,
  availableAuditors: AvailableAuditor[],
  requiredScope?: StageRequiredScope | null,
): StageCoverageResult[] {
  const teamAuditors = resolvedTeamAuditors(assignments, availableAuditors)
  const technicalExpertNames = new Set(
    (assignments.technicalExperts ?? []).map((member) => member.name),
  )

  return requiredStandards.map((standard) => {
    const standardKey = normalizeStandardKey(standard)
    const scopeEntry = requiredScopeEntry(requiredScope, standard)

    if (scopeEntry && scopeEntry.codes.length > 0) {
      const codeResults = scopeEntry.codes.map((code) => {
        const coveringAuditor = teamAuditors.find((auditor) => {
          const coveredCodes = coveredCodesForStandard(
            auditor.covered_scope,
            standard,
          )
          return codeListIncludes(coveredCodes, code, scopeEntry.type)
        })
        return {
          code,
          coveredBy: labelName(
            coveringAuditor?.name ?? null,
            technicalExpertNames,
          ),
        }
      })
      const allCodesCovered = codeResults.every(
        (result) => result.coveredBy !== null,
      )
      return {
        standard,
        covered: allCodesCovered,
        coveredBy:
          codeResults.find((result) => result.coveredBy)?.coveredBy ?? null,
        reason: allCodesCovered
          ? null
          : `missing codes: ${codeResults
              .filter((result) => !result.coveredBy)
              .map((result) => result.code)
              .join(', ')}`,
        codeResults,
      }
    }

    const coveringAuditor = teamAuditors.find((auditor) => {
      const qualifications = qualificationForStandard(auditor, standard)
      if (qualifications.length === 0) return false
      if (!EA_CODE_STANDARDS.has(standardKey) || !clientEACode) return true
      return qualifications.some((qualification) =>
        codeListIncludes(qualification.ea_codes, clientEACode, 'ea'),
      )
    })

    return {
      standard,
      covered: !!coveringAuditor,
      coveredBy: labelName(
        coveringAuditor?.name ?? null,
        technicalExpertNames,
      ),
      reason: coveringAuditor
        ? null
        : EA_CODE_STANDARDS.has(standardKey) && clientEACode
          ? `needs qualification + ${clientEACode}`
          : 'no qualified team member',
    }
  })
}

export function authoritativeCoverageLabel(
  member: StageTeamMember,
  availableAuditors: AvailableAuditor[],
): string {
  const auditor = findAuditorForTeamMember(member, availableAuditors)
  if (!auditor) return 'no matching qualification'
  const parts = Object.entries(auditor.covered_scope ?? {})
    .filter(([, codes]) => codes.length > 0)
    .map(([standard, codes]) => `${codes.join(' ')} (${standard})`)
  return parts.length > 0 ? parts.join(' | ') : 'no matching qualification'
}
