export function tracksInvoices(record: Record<string, any>): boolean {
  const name=String(record.consultant||'').toLocaleLowerCase('tr').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/ı/g,'i').replace(/\s+/g,' ').trim();
  return name !== 'ender karsli';
}

export function requiresInvoiceFollowUp(record: Record<string, any>): boolean {
  return tracksInvoices(record) && record.payment !== 'Paid';
}
