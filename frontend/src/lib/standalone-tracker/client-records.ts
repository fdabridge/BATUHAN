type Row = Record<string, any>;

// Use the full register, never the currently filtered/grouped table. Do not
// fuzzy-match names: two similar names can be different legal entities.
export function clientRecords(records: Row[], client: Row): Row[] {
  return records.filter(r => r.kind === 'certificate' && !r.archived &&
    r.company === client.company && (r.country || '') === (client.country || ''));
}
