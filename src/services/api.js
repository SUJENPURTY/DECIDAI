import {supabase} from './supabase'
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
async function headers(){const token=(await supabase?.auth.getSession())?.data?.session?.access_token;return token?{Authorization:`Bearer ${token}`}:{}}

export async function analyzeCase(formData) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/analyze-case`, { method: 'POST', headers:await headers(), body: formData })
  } catch {
    throw new Error('DECIDAI cannot reach the analysis service. Please make sure the backend is running and try again.')
  }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.detail || 'We could not analyse this case. Please try again.')
  return payload
}

async function request(path, options) {
  let response
  try { response = await fetch(`${API_BASE_URL}${path}`, {...options,headers:{...(await headers()),...(options?.headers||{})}}) }
  catch { throw new Error('DECIDAI cannot reach the decision service. Please make sure the backend is running and try again.') }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.detail || 'The request could not be completed. Please try again.')
  return payload
}

export const getDashboardStats = () => request('/api/dashboard/stats')
export const getCases = () => request('/api/cases')
export const getCase = id => request(`/api/cases/${id}`)
export const submitDecision = (id, decision) => request(`/api/cases/${id}/decision`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(decision)})
export const getTeamInvitations = () => request('/api/team/invitations')
export const createTeamInvitation = invitation => request('/api/team/invitations', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(invitation)})
export const revokeTeamInvitation = id => request(`/api/team/invitations/${id}/revoke`, {method:'POST'})
export const updateTeamMemberRole = (id, role) => request(`/api/team/members/${id}/role`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({role})})
export const removeTeamMember = id => request(`/api/team/members/${id}`, {method:'DELETE'})
export const getBillingPlan = () => request('/api/billing/plan')
export const getAnalytics = () => request('/api/analytics')

export async function getTeamMembers(){
  if(!supabase)throw new Error('Authentication is not configured.')
  const {data,error}=await supabase.from('profiles').select('id,full_name,email,role,created_at').order('created_at')
  if(error)throw new Error('We could not load workspace members. Please try again.')
  return data||[]
}

export async function getTeamAuditLog(){
  if(!supabase)throw new Error('Authentication is not configured.')
  const {data,error}=await supabase.from('organization_member_audit_logs').select(
    'id,event_type,actor_user_id,target_user_id,details,created_at'
  ).order('created_at',{ascending:false})
  if(error)throw new Error('We could not load the team audit log. Please try again.')
  return data||[]
}

async function notificationUser(){
  if(!supabase)throw new Error('Authentication is not configured.')
  const {data:{user}}=await supabase.auth.getUser()
  if(!user)throw new Error('Please sign in to view notifications.')
  return user
}

export async function getNotifications(){
  const user=await notificationUser()
  const {data:notifications,error}=await supabase.from('organization_notifications').select(
    'id,event_type,title,body,decision_case_id,created_at'
  ).order('created_at',{ascending:false})
  if(error)throw new Error('We could not load notifications. Please try again.')
  const ids=(notifications||[]).map(notification=>notification.id)
  if(!ids.length)return []
  const {data:reads,error:readsError}=await supabase.from('notification_reads').select('notification_id').eq('user_id',user.id).in('notification_id',ids)
  if(readsError)throw new Error('We could not load notifications. Please try again.')
  const readIds=new Set((reads||[]).map(read=>read.notification_id))
  return notifications.map(notification=>({...notification,read:readIds.has(notification.id)}))
}

export async function markNotificationRead(notificationId){
  const user=await notificationUser()
  const {error}=await supabase.from('notification_reads').upsert(
    {notification_id:notificationId,user_id:user.id},{onConflict:'notification_id,user_id'}
  )
  if(error)throw new Error('We could not mark this notification as read. Please try again.')
}
