const BADGE: Record<string, { bg: string; fg: string; label: string }> = {
  active:             { bg: '#e8f4ef', fg: '#1A4731', label: 'Active' },
  approaching_expiry: { bg: '#FEF3C7', fg: '#D97706', label: 'Renewing soon' },
  expired:            { bg: '#FEE2E2', fg: '#DC2626', label: 'Expired' },
}

export function CertBadge({ status }: { status: string | null }) {
  const s = status ? BADGE[status] : null
  if (!s) return <span className="text-gray-400">—</span>
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ background: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  )
}
