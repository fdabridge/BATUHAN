'use client'

import { MessageThread } from '@/components/ui/MessageThread'

export default function ClientMessagesPage() {
  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col p-6">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-gray-900">Messages</h1>
        <p className="mt-0.5 text-sm text-gray-400">
          Communicate with the IFC Global team
        </p>
      </div>
      <div className="flex-1 overflow-hidden rounded-xl border bg-white">
        <MessageThread
          fetchUrl="/client/my-audit-set/messages"
          postUrl="/client/my-audit-set/messages"
        />
      </div>
    </div>
  )
}
