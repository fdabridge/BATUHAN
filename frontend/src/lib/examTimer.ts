export interface ExamTimerPayload {
  remaining_seconds?: number | null
  server_now?: string | null
  exam_due_at?: string | null
}

function parseApiUtc(value: string | null | undefined): number | null {
  if (!value) return null
  // Older API responses used naive ISO timestamps even though the database
  // values are UTC. Explicitly mark those values as UTC for compatibility.
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`
  const parsed = Date.parse(normalized)
  return Number.isFinite(parsed) ? parsed : null
}

export function examRemainingSeconds(
  payload: ExamTimerPayload,
  clientNowMs = Date.now(),
): number | null {
  if (
    typeof payload.remaining_seconds === 'number'
    && Number.isFinite(payload.remaining_seconds)
  ) {
    return Math.max(0, Math.ceil(payload.remaining_seconds))
  }

  const dueMs = parseApiUtc(payload.exam_due_at)
  if (dueMs === null) return null

  const serverNowMs = parseApiUtc(payload.server_now)
  const referenceMs = serverNowMs ?? clientNowMs
  return Math.max(0, Math.ceil((dueMs - referenceMs) / 1000))
}
