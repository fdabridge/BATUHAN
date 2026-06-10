import { SignatureSettings } from '@/components/SignatureSettings'

export default function AuditorSignaturePage() {
  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-semibold text-gray-900">My Signature</h1>
      <SignatureSettings />
    </div>
  )
}
