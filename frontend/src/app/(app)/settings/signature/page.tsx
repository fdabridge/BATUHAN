import { SignatureSettings } from '@/components/SignatureSettings'

export default function CBSignaturePage() {
  return (
    <div className="mx-auto max-w-[1200px] py-4">
      <h1 className="mb-6 text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>
        My Signature
      </h1>
      <SignatureSettings />
    </div>
  )
}
