type VeraMarkProps = {
  className?: string
  thinking?: boolean
}

/**
 * Vera's mark is derived from Certiva's approved document/check icon.  The
 * folded corner and three quiet status dots give the assistant a distinct
 * presence without introducing a generic robot mascot.
 */
export function VeraMark({ className = '', thinking = false }: VeraMarkProps) {
  return (
    <svg
      viewBox="0 0 48 48"
      role="img"
      aria-label="Vera"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect width="48" height="48" rx="15" fill="#1A4731" />
      <path
        d="M14 10.5h13.1l7 7v20H14v-27Z"
        fill="none"
        stroke="#FFFFFF"
        strokeWidth="2.4"
        strokeLinejoin="round"
      />
      <path d="M27.1 10.5v7h7" fill="none" stroke="#FFFFFF" strokeWidth="2.4" strokeLinejoin="round" />
      {thinking ? (
        <g fill="#52C27A">
          <circle cx="19" cy="28" r="1.7" className="animate-pulse" />
          <circle cx="24" cy="28" r="1.7" className="animate-pulse [animation-delay:120ms]" />
          <circle cx="29" cy="28" r="1.7" className="animate-pulse [animation-delay:240ms]" />
        </g>
      ) : (
        <path
          d="m18.8 27.7 3.7 3.7 7.3-7.3"
          fill="none"
          stroke="#52C27A"
          strokeWidth="2.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </svg>
  )
}
