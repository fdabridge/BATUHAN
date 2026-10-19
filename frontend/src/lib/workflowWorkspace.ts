import { isSurveillanceWorkflowAudit } from './auditTypes'

export interface WorkflowWorkspaceInput {
  workflowStatus: string | null | undefined
  auditType: string | null | undefined
  workflowVersion: number | null | undefined
  isTransfer: boolean
}

/**
 * Document types the planner may actively release in the current phase.
 * This is a presentation allowlist; the backend remains the authority for
 * transition and signature gates.
 */
export function activePlannerDocumentTypes({
  workflowStatus,
  auditType,
  workflowVersion,
  isTransfer,
}: WorkflowWorkspaceInput): string[] {
  if (!workflowStatus || workflowStatus === 'pending_review') return []

  const surveillance = isSurveillanceWorkflowAudit(auditType)
  const transferSurveillance = surveillance && isTransfer
  const fr218First = (workflowVersion ?? 1) >= 2 && (!surveillance || transferSurveillance)

  if (workflowStatus === 'in_planning') {
    if (surveillance && !transferSurveillance) return ['surveillance_notification']
    return isTransfer
      ? ['transfer_review', fr218First ? 'fr218_review' : 'quotation']
      : [fr218First ? 'fr218_review' : 'quotation']
  }
  // The FR.218 has already been released at this point; this phase waits for
  // its required signatures instead of offering a duplicate upload.
  if (workflowStatus === 'fr218_in_progress') return []
  if (workflowStatus === 'fr218_complete') {
    return fr218First ? ['quotation'] : ['audit_programme', 'team_info']
  }
  if (workflowStatus === 'quotation_sent') return ['agreement']
  if (workflowStatus === 'agreement_signed') {
    return fr218First || surveillance
      ? ['audit_programme', 'team_info']
      : ['fr218_review']
  }
  if (workflowStatus === 'notification_sent') return ['team_info']
  if (['stage1_scheduled', 'stage1_complete', 'stage2_scheduled', 'audit_scheduled'].includes(workflowStatus)) {
    return ['team_info']
  }
  if (['stage2_complete', 'under_review'].includes(workflowStatus)) return ['review_decision']
  return []
}
