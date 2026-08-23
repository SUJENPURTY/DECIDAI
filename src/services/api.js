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
