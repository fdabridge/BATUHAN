export const ISO_STANDARD_CODES = [
  'QMS', 'EMS', 'OHSMS', 'FSMS', 'MDQMS', 'ISMS', 'ABMS', 'ENMS',
] as const

export type ISOStandardCode = (typeof ISO_STANDARD_CODES)[number]

export type QualificationScopeType = 'ea' | 'food' | 'medical' | 'isms' | 'sector' | 'energy'

export const ENMS_ENERGY_COMPLEXITY_OPTIONS = ['Low', 'Medium', 'High'] as const
export type EnmsEnergyComplexity = (typeof ENMS_ENERGY_COMPLEXITY_OPTIONS)[number]

const STANDARD_BY_NUMBER: Record<string, ISOStandardCode> = {
  '9001': 'QMS',
  '14001': 'EMS',
  '45001': 'OHSMS',
  '22000': 'FSMS',
  '13485': 'MDQMS',
  '27001': 'ISMS',
  '37001': 'ABMS',
  '50001': 'ENMS',
}

const STANDARD_BY_ALIAS: Record<string, ISOStandardCode> = {
  qms: 'QMS',
  ems: 'EMS',
  ohsms: 'OHSMS',
  fsms: 'FSMS',
  mdqms: 'MDQMS',
  mdms: 'MDQMS',
  isms: 'ISMS',
  abms: 'ABMS',
  enms: 'ENMS',
}

export function normalizeISOStandardCode(value: unknown): ISOStandardCode | null {
  const raw = String(value ?? '').trim().toLowerCase()
  if (!raw) return null
  const compact = raw.replace(/[^a-z0-9]/g, '')
  if (STANDARD_BY_ALIAS[compact]) return STANDARD_BY_ALIAS[compact]
  const number = Object.keys(STANDARD_BY_NUMBER).find((candidate) =>
    new RegExp(`(^|\\D)${candidate}(\\D|$)`).test(raw),
  )
  return number ? STANDARD_BY_NUMBER[number] : null
}

export function normalizeISOStandardCodes(values: unknown[]): ISOStandardCode[] {
  const normalized: ISOStandardCode[] = []
  values.forEach((value) => {
    const code = normalizeISOStandardCode(value)
    if (code && !normalized.includes(code)) normalized.push(code)
  })
  return normalized
}

/** Return the qualification-scope family for every supported standard spelling. */
export function qualificationScopeType(value: unknown): QualificationScopeType {
  const raw = String(value ?? '').trim().toLowerCase()
  const compact = raw.replace(/[^a-z0-9]/g, '')
  if (compact.startsWith('fssc')) return 'food'
  if (compact === 'cms' || /(^|\D)37301(\D|$)/.test(raw)) return 'sector'

  switch (normalizeISOStandardCode(value)) {
    case 'FSMS':
      return 'food'
    case 'MDQMS':
      return 'medical'
    case 'ISMS':
      return 'isms'
    case 'ABMS':
      return 'sector'
    case 'ENMS':
      return 'energy'
    default:
      return 'ea'
  }
}

/** Normalize current and legacy EnMS labels to the value stored in qualifications. */
export function normalizeEnmsEnergyComplexity(value: unknown): EnmsEnergyComplexity | '' {
  const normalized = String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/\s+complexity$/, '')
    .trim()
  return ENMS_ENERGY_COMPLEXITY_OPTIONS.find(
    (option) => option.toLowerCase() === normalized,
  ) ?? ''
}
