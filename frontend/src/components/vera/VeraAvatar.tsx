'use client'

import { useEffect, useRef, useState } from 'react'
import styles from './VeraAvatar.module.css'

export type VeraMood = 'idle' | 'wave' | 'listening' | 'thinking' | 'speaking' | 'success'

type Props = {
  mood?: VeraMood
  className?: string
  label?: string
}

const FRAME_POSITIONS = [
  '0% 0%',
  '33.3333% 0%',
  '66.6667% 0%',
  '100% 0%',
  '0% 100%',
  '33.3333% 100%',
  '66.6667% 100%',
  '100% 100%',
]

const MOOD_FRAMES: Record<VeraMood, number[]> = {
  idle: [0, 1],
  wave: [2, 3],
  listening: [4],
  thinking: [5, 5, 0],
  speaking: [6, 0, 6],
  success: [7],
}

const FRAME_DELAYS: Record<VeraMood, number> = {
  idle: 1100,
  wave: 330,
  listening: 1800,
  thinking: 620,
  speaking: 420,
  success: 1000,
}

export function VeraAvatar({ mood = 'idle', className = '', label = 'Vera' }: Props) {
  const [frameIndex, setFrameIndex] = useState(0)
  const frameCursor = useRef(0)

  useEffect(() => {
    frameCursor.current = 0
    setFrameIndex(MOOD_FRAMES[mood][0])
    if (MOOD_FRAMES[mood].length === 1) return

    if (mood === 'idle') {
      let blinkTimer: number
      let resetTimer: number
      const scheduleBlink = () => {
        blinkTimer = window.setTimeout(() => {
          setFrameIndex(1)
          resetTimer = window.setTimeout(() => {
            setFrameIndex(0)
            scheduleBlink()
          }, 150)
        }, 3200)
      }
      scheduleBlink()
      return () => {
        window.clearTimeout(blinkTimer)
        window.clearTimeout(resetTimer)
      }
    }

    const timer = window.setInterval(() => {
      frameCursor.current = (frameCursor.current + 1) % MOOD_FRAMES[mood].length
      setFrameIndex(MOOD_FRAMES[mood][frameCursor.current])
    }, FRAME_DELAYS[mood])
    return () => window.clearInterval(timer)
  }, [mood])

  return (
    <span
      role="img"
      aria-label={label}
      className={`${styles.avatar} ${styles[mood]} ${className}`}
      style={{ backgroundPosition: FRAME_POSITIONS[frameIndex] }}
    />
  )
}
