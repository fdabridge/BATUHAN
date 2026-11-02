'use client'

import React, {createContext, useContext, useEffect, useRef, useState} from 'react'

export function Button({variant='default',className='',...props}:React.ButtonHTMLAttributes<HTMLButtonElement>&{variant?:string}){
 return <button type="button" className={`tracker-button tracker-${variant} ${className}`} {...props}/>
}
export function Input(props:React.InputHTMLAttributes<HTMLInputElement>){return <input {...props}/>}
export function Table(props:React.TableHTMLAttributes<HTMLTableElement>){return <div className="tracker-table-scroll"><table {...props}/></div>}
export function TableHeader(props:React.HTMLAttributes<HTMLTableSectionElement>){return <thead {...props}/>}
export function TableBody(props:React.HTMLAttributes<HTMLTableSectionElement>){return <tbody {...props}/>}
export function TableRow(props:React.HTMLAttributes<HTMLTableRowElement>){return <tr {...props}/>}
export function TableHead(props:React.ThHTMLAttributes<HTMLTableCellElement>){return <th {...props}/>}
export function TableCell(props:React.TdHTMLAttributes<HTMLTableCellElement>){return <td {...props}/>}

const SheetContext=createContext<{open:boolean,onOpenChange:(v:boolean)=>void}>({open:false,onOpenChange:()=>{}})
export function Sheet({open,onOpenChange,children}:{open:boolean,onOpenChange:(v:boolean)=>void,children:React.ReactNode}){
 return <SheetContext.Provider value={{open,onOpenChange}}>{children}</SheetContext.Provider>
}
export function SheetContent({className='',children}:{className?:string,children:React.ReactNode}){
 const {open,onOpenChange}=useContext(SheetContext), ref=useRef<HTMLDialogElement>(null)
 useEffect(()=>{const d=ref.current;if(open&&!d?.open)d?.showModal();if(!open&&d?.open)d.close()},[open])
 return <dialog ref={ref} className={`tracker-dialog ${className}`} aria-label="Record details" onCancel={e=>{e.preventDefault();onOpenChange(false)}}>
  {children}<button className="tracker-close" aria-label="Close panel" onClick={()=>onOpenChange(false)}>×</button>
 </dialog>
}
export function SheetHeader(props:React.HTMLAttributes<HTMLDivElement>){return <div data-slot="sheet-header" {...props}/>}
export function SheetTitle(props:React.HTMLAttributes<HTMLHeadingElement>){return <h2 data-slot="sheet-title" {...props}/>}
export function SheetDescription(props:React.HTMLAttributes<HTMLParagraphElement>){return <p {...props}/>}

const emit=(message:string,kind:string)=>window.dispatchEvent(new CustomEvent('ifc-tracker-notice',{detail:{message,kind}}))
export const toast={success:(m:string)=>emit(m,'success'),error:(m:string)=>emit(m,'error')}
export function Toaster(_: {richColors?:boolean}){
 const [notice,setNotice]=useState<{message:string,kind:string}|null>(null)
 useEffect(()=>{const listener=(e:Event)=>setNotice((e as CustomEvent).detail);window.addEventListener('ifc-tracker-notice',listener);return()=>window.removeEventListener('ifc-tracker-notice',listener)},[])
 useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(null),6000);return()=>clearTimeout(timer)},[notice])
 return notice?<div role="status" className={`tracker-notice ${notice.kind}`}>{notice.message}<button aria-label="Dismiss notification" onClick={()=>setNotice(null)}>×</button></div>:null
}
