import type { CSSProperties } from 'react'

type CertivaLogoProps = {
  variant?: 'primary' | 'reversed'
  iconOnly?: boolean
  className?: string
  title?: string
}

/**
 * Approved Certiva production artwork from the supplied brand system.
 * Keep the geometry and proportions in sync with the master SVG files.
 */
export function CertivaLogo({
  variant = 'primary',
  iconOnly = false,
  className = '',
  title = 'Certiva',
}: CertivaLogoProps) {
  const foreground = variant === 'reversed' ? '#FFFFFF' : '#1A4731'
  const iconBackground = variant === 'reversed' ? 'rgba(255,255,255,0.12)' : '#1A4731'
  const width = iconOnly ? 44 : 160
  const wordmarkStyle: CSSProperties = {
    fontFamily: 'var(--font-certiva-wordmark), Inter, system-ui, sans-serif',
    letterSpacing: '-0.5px',
  }

  return (
    <svg
      width={width}
      height="44"
      viewBox={`0 0 ${width} 44`}
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label={title}
      className={className}
    >
      <title>{title}</title>
      <rect width="44" height="44" rx="10" fill={iconBackground} />
      <g transform="translate(9, 9)">
        <path d="M5.2 2.6h11.7l3.9 3.9v16.9H5.2V2.6z" stroke="white" strokeWidth="1.95" strokeLinejoin="round" fill="none" />
        <path d="M16.9 2.6v3.9h3.9" stroke="white" strokeWidth="1.95" strokeLinejoin="round" fill="none" />
        <path d="M9.1 13.65l2.6 2.6 5.2-5.2" stroke="white" strokeWidth="1.95" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </g>
      {!iconOnly && (
        <text
          x="56"
          y="30"
          fontSize="24"
          fontWeight="400"
          fill={foreground}
          style={wordmarkStyle}
        >
          certiva
        </text>
      )}
    </svg>
  )
}
