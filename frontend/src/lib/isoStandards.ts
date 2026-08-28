export const ISO_STANDARD_CODES = [
  'QMS', 'EMS', 'OHSMS', 'FSMS', 'MDQMS', 'ISMS', 'ABMS', 'ENMS',
] as const

export type ISOStandardCode = (typeof ISO_STANDARD_CODES)[number]

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
