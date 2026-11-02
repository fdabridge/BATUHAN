'use client'

import {useEffect} from 'react'
import {useRouter} from 'next/navigation'
import {useAuth} from '@/lib/auth'
import Tracker from '@/components/standalone-tracker/Tracker'
import './tracker.css'

export default function CertificateTrackerPage(){
 const {user,token,isLoading}=useAuth(),router=useRouter()
 useEffect(()=>{if(!isLoading&&!token)router.replace('/login')},[isLoading,token,router])
 if(isLoading||!token)return <p className="p-8">Loading…</p>
 if(!user)return <p className="p-8">Loading your account…</p>
 return <Tracker/>
}
