import type { Metadata } from "next"

export const metadata: Metadata = { title: { absolute: "IFC Global · Certificate Tracker" }, icons: { icon: "/ifc-brand/icon.png" } }

export default function TrackerLayout({children}: {children: React.ReactNode}) {
  return children
}
