const API = '/api'

export async function fetchMeetings() {
  const r = await fetch(`${API}/meetings`)
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function fetchMeeting(id) {
  const r = await fetch(`${API}/meetings/${id}`)
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function deleteMeeting(id) {
  const r = await fetch(`${API}/meetings/${id}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function patchItem(id, patch) {
  const r = await fetch(`${API}/items/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function putSettings(meetingId, settings) {
  const r = await fetch(`${API}/meetings/${meetingId}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function postReanchor(meetingId) {
  const r = await fetch(`${API}/meetings/${meetingId}/reanchor`, { method: 'POST' })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function postReprocess(meetingId) {
  const r = await fetch(`${API}/meetings/${meetingId}/reprocess`, { method: 'POST' })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function importTranscript(file) {
  const form = new FormData()
  form.append('file', file)
  const r = await fetch(`${API}/meetings/import`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function fetchMeetilyStatus() {
  const r = await fetch(`${API}/meetily/status`)
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export function exportEdlUrl(meetingId) {
  return `${API}/meetings/${meetingId}/export.edl`
}

export function exportCsvUrl(meetingId) {
  return `${API}/meetings/${meetingId}/export.csv`
}
