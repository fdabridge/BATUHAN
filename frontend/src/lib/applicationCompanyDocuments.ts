export interface CompanyDocumentSelection {
  name: string
  size: number
}

/**
 * Copy the browser's live FileList before the picker input is cleared.
 * FileList is tied to the input and can become empty before a deferred React
 * state updater runs.
 */
export function snapshotCompanyDocumentSelection<T extends CompanyDocumentSelection>(
  files: ArrayLike<T> | null,
): T[] {
  return files ? Array.from(files) : []
}

/** Merge a selection while replacing an exact name/size duplicate in place. */
export function mergeCompanyDocumentSelection<T extends CompanyDocumentSelection>(
  current: readonly T[],
  selected: readonly T[],
): T[] {
  const next = [...current]
  for (const file of selected) {
    const duplicateIndex = next.findIndex(
      (item) => item.name === file.name && item.size === file.size,
    )
    if (duplicateIndex >= 0) next[duplicateIndex] = file
    else next.push(file)
  }
  return next
}
