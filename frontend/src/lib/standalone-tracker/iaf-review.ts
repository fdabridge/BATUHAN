type Row=Record<string,any>;
const key=(v:unknown)=>String(v??'').toLocaleLowerCase('tr').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/ı/g,'i').replace(/[^a-z0-9]/g,'');
const standard=(r:Row)=>String(r.standard||'').match(/\d{4,5}/)?.[0]||'';
export function registryExpiryMismatch(row:Row,records:Row[],deadline:string,today:string,registry:'iaf'|'uaf'){
 if(row.stage!=='Certificate'||row.archived||!deadline||deadline>=today||row[registry]?.status!=='Active')return false;
 // A newer issued, current certificate takes precedence over an older cycle.
 return !records.some(other=>other.id!==row.id&&!other.archived&&other.stage==='Certificate'&&key(other.company)===key(row.company)&&key(other.country)===key(row.country)&&standard(other)===standard(row)&&other.issue>row.issue&&other.annual>=today&&other.certificate);
}

export function iafExpiryMismatch(row:Row,records:Row[],deadline:string,today:string){return registryExpiryMismatch(row,records,deadline,today,'iaf')}
