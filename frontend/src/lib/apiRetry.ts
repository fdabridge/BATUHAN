type ApiFailure = {
  code?: string
  message?: string
  response?: {
    status?: number
  }
}

const TRANSIENT_STATUS_CODES = new Set([408, 425, 429, 500, 502, 503, 504])
const TRANSIENT_ERROR_CODES = new Set([
  'ECONNABORTED',
  'ECONNRESET',
  'ERR_BAD_RESPONSE',
  'ERR_NETWORK',
  'ETIMEDOUT',
])

export function isTransientApiFailure(error: unknown): boolean {
  const candidate = error as ApiFailure
  const status = candidate?.response?.status
  if (status) return TRANSIENT_STATUS_CODES.has(status)

  const code = candidate?.code?.toUpperCase()
  if (code && TRANSIENT_ERROR_CODES.has(code)) return true

  const message = candidate?.message?.toLowerCase() ?? ''
  return message.includes('network error') || message.includes('timeout')
}

type RetryOptions = {
  retries?: number
  delayMs?: number
  onRetry?: (error: unknown, attempt: number) => void
  wait?: (delayMs: number) => Promise<void>
}

const defaultWait = (delayMs: number) => new Promise<void>((resolve) => {
  setTimeout(resolve, delayMs)
})

export async function retryTransientApiRequest<T>(
  request: () => Promise<T>,
  options: RetryOptions = {},
): Promise<T> {
  const retries = options.retries ?? 2
  const delayMs = options.delayMs ?? 1500
  const wait = options.wait ?? defaultWait

  let attempt = 0
  while (true) {
    try {
      return await request()
    } catch (error) {
      if (attempt >= retries || !isTransientApiFailure(error)) throw error
      attempt += 1
      options.onRetry?.(error, attempt)
      await wait(delayMs * attempt)
    }
  }
}
