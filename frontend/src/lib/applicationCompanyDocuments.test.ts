import assert from 'node:assert/strict'
import test from 'node:test'

import {
  mergeCompanyDocumentSelection,
  snapshotCompanyDocumentSelection,
} from './applicationCompanyDocuments'

interface TestDocument {
  name: string
  size: number
  revision: number
}

test('snapshots a live picker selection before the input is cleared', () => {
  const registration = { name: 'registration.pdf', size: 123, revision: 1 }
  const liveSelection: TestDocument[] = [registration]

  const snapshot = snapshotCompanyDocumentSelection(liveSelection)
  liveSelection.length = 0

  assert.deepEqual(snapshot, [registration])
})

test('adds new documents and replaces exact duplicates without dropping prior files', () => {
  const registration = { name: 'registration.pdf', size: 123, revision: 1 }
  const tax = { name: 'tax.pdf', size: 456, revision: 1 }
  const replacement = { name: 'registration.pdf', size: 123, revision: 2 }

  const added = mergeCompanyDocumentSelection([registration], [tax])
  assert.deepEqual(added, [registration, tax])
  assert.deepEqual(
    mergeCompanyDocumentSelection(added, [replacement]),
    [replacement, tax],
  )
})
