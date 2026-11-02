function iso(date:Date){return date.toISOString().slice(0,10)}
export function expiryRange(preset:string,today:string):[string,string] {
 const [year,month,day]=today.split('-').map(Number);
 if(preset==='Due this month')return [iso(new Date(Date.UTC(year,month-1,1))),iso(new Date(Date.UTC(year,month,0)))];
 if(preset==='Expired in last month'){
  const lastDayPreviousMonth=new Date(Date.UTC(year,month-1,0)).getUTCDate();
  return [iso(new Date(Date.UTC(year,month-2,Math.min(day,lastDayPreviousMonth)))),iso(new Date(Date.UTC(year,month-1,day-1)))];
 }
 return ['',''];
}
export function inExpiryRange(date:string,from:string,to:string):boolean {
 if(!from&&!to)return true;
 if(!date||(from&&to&&from>to))return false;
 return (!from||date>=from)&&(!to||date<=to);
}
