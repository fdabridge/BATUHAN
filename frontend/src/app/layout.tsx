import type { Metadata } from 'next'
import { Inter, Manrope } from 'next/font/google'
import './globals.css'
import { Providers } from '@/components/providers'

const manrope = Manrope({
  subsets: ['latin'],
  variable: '--font-certiva',
})
const inter = Inter({
  subsets: ['latin'],
  variable: '--font-certiva-wordmark',
})

export const metadata: Metadata = {
  title: {
    default: 'Certiva',
    template: '%s | Certiva',
  },
  applicationName: 'Certiva',
  description: 'Certification, audit planning, document signing, and compliance workflow platform',
  icons: {
    icon: '/favicon.svg',
    shortcut: '/favicon.svg',
    apple: '/favicon.svg',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={`${manrope.variable} ${inter.variable}`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
