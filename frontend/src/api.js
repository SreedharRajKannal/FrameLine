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

export async function uploadVideo(file) {
  const form = new FormData()
  form.append('file', file)
  const r = await fetch(`${API}/videos`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function linkMeetingVideo(meetingId, videoId) {
  const r = await fetch(`${API}/meetings/${meetingId}/video`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_id: videoId }),
  })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function updateMeetingTitle(meetingId, title) {
  const r = await fetch(`${API}/meetings/${meetingId}/title`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
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

// ── Phase 3 Vision & Edit API ────────────────────────────────────────────────
export async function triggerVisionPass(videoId) {
  const r = await fetch(`${API}/videos/${videoId}/vision`, { method: 'POST' })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function fetchVisionStatus(videoId) {
  const r = await fetch(`${API}/videos/${videoId}/vision/status`)
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function fetchVideoContext(videoId) {
  const r = await fetch(`${API}/videos/${videoId}/context`)
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function fetchEntities(videoId) {
  const r = await fetch(`${API}/videos/${videoId}/entities`)
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function generateEditInstructions(meetingId, videoId) {
  const r = await fetch(`${API}/meetings/${meetingId}/edits/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_id: videoId }),
  })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function fetchEditInstructions(meetingId) {
  const r = await fetch(`${API}/meetings/${meetingId}/edits`)
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function patchEditInstruction(instId, patch) {
  const r = await fetch(`${API}/edits/${instId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

export async function renderEditPreview(instId) {
  const r = await fetch(`${API}/edits/${instId}/preview`, { method: 'POST' })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}

