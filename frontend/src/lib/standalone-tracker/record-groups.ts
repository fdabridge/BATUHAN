type Row = Record<string, any>;
const key = (value: unknown) => String(value ?? '').trim().toLocaleLowerCase('tr').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/ı/g, 'i').replace(/\s+/g, ' ');

// Group presentation only. A standard, site, or certification cycle is never deleted.
// Keep the input sort order: the first record determines the group's position.
export function groupRecords(rows: Row[], separate = false): Row[][] {
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    const id = separate || !row.company ? row.id : JSON.stringify([row.company, row.country, row.consultant, row.stage, row.site || ''].map(key));
    const group = groups.get(id);
    if (group) group.push(row); else groups.set(id, [row]);
  }
  return [...groups.values()];
}

export function sameInvoice(rows: Row[]): boolean {
  return rows.length > 1 && rows.every(r => r.invoiceRef === rows[0].invoiceRef && r.invoiced === rows[0].invoiced && (r.fee === 0) === (rows[0].fee === 0) && r.feeBasis === rows[0].feeBasis);
}
