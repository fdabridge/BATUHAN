type PendingAuditPlanSubmission = {
  fingerprint: string
  requestId: string
}

/** Compactly identify the current form without storing company data in sessionStorage. */
export function auditPlanSubmissionFingerprint(serializedForm: string): string {
  let hash = 2166136261
  for (let index = 0; index < serializedForm.length; index += 1) {
    hash ^= serializedForm.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

export function resolveAuditPlanRequest(
  storedValue: string | null,
  fingerprint: string,
  createId: () => string,
): { requestId: string; storageValue: string } {
  if (storedValue) {
    try {
      const stored = JSON.parse(storedValue) as PendingAuditPlanSubmission
      if (stored.fingerprint === fingerprint && stored.requestId) {
        return { requestId: stored.requestId, storageValue: storedValue }
      }
    } catch {
      // Replace malformed or outdated browser state.
    }
  }

  const pending: PendingAuditPlanSubmission = {
    fingerprint,
    requestId: createId(),
  }
  return { requestId: pending.requestId, storageValue: JSON.stringify(pending) }
}
