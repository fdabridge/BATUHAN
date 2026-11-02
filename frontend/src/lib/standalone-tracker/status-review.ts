type Row=Record<string,any>;
export type StatusPatch={id:string,identity:Row,before:Row,changes:Row};
// A review changes only the fields checked against its captured online record.
// A later colleague save takes precedence, including intentional clearing of fields.
export function applyStatusReview(row:Row,patches:StatusPatch[],reviewedAt:string):Row{
 const patch=patches.find(p=>p.id===row.id);
 if(!patch||row.updatedAt&&row.updatedAt>reviewedAt)return row;
 if(Object.entries(patch.identity).some(([key,value])=>row[key]!==value))return row;
 const changes:Row={};
 for(const [key,value] of Object.entries(patch.changes)){
  if(JSON.stringify(row[key]??null)===JSON.stringify(patch.before[key]??null))changes[key]=value;
 }
 return {...row,...changes};
}
export const renewalStatuses=['Renewing','Renewed','Not renewing','Awaiting reply','Quotation sent','Assigned','Non-accredited','TÜRKAK transfer'];
export function matchesFollowUp(row:Row,filter:string,renewal?:Row){
 const hasFollowUp=!!(row.followUp||row.reminderDate||row.renewalStatus||renewal);
 if(filter==='Follow-up recorded')return hasFollowUp;
 if(filter==='No follow-up recorded')return !hasFollowUp;
 if(filter==='Reminder sent')return !!row.reminderDate;
 if(filter==='Renewal in progress')return row.renewalStatus==='Renewing'||(!row.renewalStatus&&!!renewal);
 if(renewalStatuses.includes(filter))return row.renewalStatus===filter;
 return true;
}
