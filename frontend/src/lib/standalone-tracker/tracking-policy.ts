export function tracksInvoices(record: Record<string, any>): boolean {
  const name=String(record.consultant||'').toLocaleLowerCase('tr').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/ı/g,'i').replace(/\s+/g,' ').trim();
  return name !== 'ender karsli';
}

export function requiresInvoiceFollowUp(record: Record<string, any>): boolean {
  return tracksInvoices(record) && record.payment !== 'Paid';
}

// Certificate status is authoritative for this view. Missing invoice references
// or amounts must not hide an explicitly invoiced, unpaid certificate.
export function isInvoicedUnpaidCertificate(record: Record<string, any>): boolean {
  return !record.archived && record.stage === 'Certificate' &&
    tracksInvoices(record) && record.invoiced === 'Yes' &&
    (record.payment === 'Unpaid' || record.payment === 'Part-paid');
}
