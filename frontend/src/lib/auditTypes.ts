export const SCOPE_EXTENSION = 'scope_extension'
export const SURVEILLANCE_1_SCOPE_EXTENSION = 'surveillance_1_scope_extension'

export function isSurveillanceWorkflowAudit(auditType: string | null | undefined): boolean {
  const normalized = (auditType ?? '').trim().toLowerCase().replace(/[ -]+/g, '_')
  return normalized.startsWith('surveillance') || normalized === SCOPE_EXTENSION
}

export function auditTypeLabel(auditType: string | null | undefined): string {
  const labels: Record<string, string> = {
    initial: 'Initial certification',
    surveillance: 'Surveillance',
    surveillance_1: 'Surveillance 1',
    surveillance_2: 'Surveillance 2',
    [SCOPE_EXTENSION]: 'Scope Extension',
    [SURVEILLANCE_1_SCOPE_EXTENSION]: 'Surveillance 1 + Scope Extension',
    recertification: 'Recertification',
    special: 'Special Audit',
  }
  return labels[auditType ?? ''] ?? (auditType ?? '').replace(/_/g, ' ')
}

export function reportStageForAuditType(auditType: string | null | undefined): string {
  if (auditType === 'surveillance_2') return 'Surveillance 2'
  if (isSurveillanceWorkflowAudit(auditType)) return 'Surveillance 1'
  if (auditType === 'recertification') return 'Recertification'
  return ''
}
