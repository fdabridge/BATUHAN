type ApiErrorLike = {
  message?: string
  response?: {
    status?: number
    data?: unknown
  }
}

function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail.trim()
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item)
        const entry = item as { msg?: unknown; loc?: unknown }
        const message = typeof entry.msg === 'string' ? entry.msg : ''
        const location = Array.isArray(entry.loc) ? entry.loc.join('.') : ''
        return [location, message].filter(Boolean).join(': ')
      })
      .filter(Boolean)
      .join('; ')
  }
  return ''
}

function parseTextPayload(text: string): string {
  const value = text.trim()
  if (!value) return ''
  try {
    const parsed = JSON.parse(value) as { detail?: unknown }
    return detailText(parsed?.detail)
  } catch {
    // Railway/proxy failures can return an HTML error page. Do not print HTML
    // into the UI, but preserve short plain-text server messages.
    if (/^\s*</.test(value)) return ''
    return value.length <= 300 ? value : ''
  }
}

async function responseDataText(data: unknown): Promise<string> {
  if (typeof data === 'string') return parseTextPayload(data)
  if (typeof Blob !== 'undefined' && data instanceof Blob) {
    return parseTextPayload(await data.text())
  }
  if (data instanceof ArrayBuffer) {
    return parseTextPayload(new TextDecoder().decode(data))
  }
  if (data && typeof data === 'object' && 'detail' in data) {
    return detailText((data as { detail?: unknown }).detail)
  }
  return ''
}

export async function apiErrorMessage(
  error: unknown,
  fallback = 'The request could not be completed.',
  serviceLabel = 'service',
): Promise<string> {
  const candidate = error as ApiErrorLike
  const response = candidate?.response
  const responseMessage = await responseDataText(response?.data)
  if (responseMessage) return responseMessage

  if (response?.status) {
    return `The ${serviceLabel} returned HTTP ${response.status}. Please try again.`
  }
  if (candidate?.message === 'Network Error' || candidate?.message?.toLowerCase().includes('network')) {
    return `Could not reach the ${serviceLabel}. Please check the connection and try again.`
  }
  return candidate?.message?.trim() || fallback
}
