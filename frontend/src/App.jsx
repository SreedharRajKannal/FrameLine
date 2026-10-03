import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchMeetings, fetchMeeting, patchItem, putSettings,
  postReanchor, importTranscript, uploadVideo, linkMeetingVideo, fetchMeetilyStatus,
  exportEdlUrl, exportCsvUrl, deleteMeeting, updateMeetingTitle,
  generateEditInstructions, fetchEditInstructions,
} from './api.js'
import { secondsToTimecode, timecodeToSeconds } from './timecode.js'
import VideoContextPanel from './components/VideoContextPanel.jsx'
import EditInstructionCard from './components/EditInstructionCard.jsx'


// ─────────────────────────────────────────────────────────
// Toast context (simple local state)
// ─────────────────────────────────────────────────────────
function useToast() {
  const [toasts, setToasts] = useState([])
  const toast = useCallback((msg, type = 'info') => {
    const id = Date.now()
    setToasts(t => [...t, { id, msg, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3000)
  }, [])
  return { toasts, toast }
}

// ─────────────────────────────────────────────────────────
// Status dot component
// ─────────────────────────────────────────────────────────
function StatusDot({ status }) {
  const cls = status === 'ok' ? 'ok' : status === 'err' ? 'err' : ''
  return <span className={`status-dot ${cls}`} title={status} />
}

// ─────────────────────────────────────────────────────────
// Type / priority badges
// ─────────────────────────────────────────────────────────
const TYPE_ICONS = { change: '●', question: '?', approval: '✓' }
function TypeBadge({ type }) {
  return <span className={`badge badge-${type}`}>{TYPE_ICONS[type] || '●'} {type}</span>
}
function PriorityBadge({ priority }) {
  return <span className={`badge badge-priority-${priority}`}>{priority}</span>
}
function CategoryBadge({ category }) {
  return <span className="badge badge-category">{category.replace('_', ' ')}</span>
}

// ─────────────────────────────────────────────────────────
// Timecode display for an item
// ─────────────────────────────────────────────────────────
function ItemTimecode({ item, settings }) {
  if (item.is_global) return <span className="item-tc no-anchor">global</span>
  if (item.anchor_sec === null || item.anchor_sec === undefined)
    return <span className="item-tc no-anchor">no anchor</span>
  const tc = secondsToTimecode(item.anchor_sec, settings?.fps, settings?.start_timecode)
  return <span className="item-tc">{tc}</span>
}

// ─────────────────────────────────────────────────────────
// Single item card
// ─────────────────────────────────────────────────────────
function ItemCard({ item, settings, selected, onSelect }) {
  return (
    <div
      className={[
        'item-card',
        selected ? 'selected' : '',
        item.needs_review && !item.withdrawn ? 'needs-review-highlight' : '',
      ].join(' ')}
      onClick={() => onSelect(item)}
      id={`item-${item.id}`}
    >
      <div className="item-card-top">
        <TypeBadge type={item.type} />
        <PriorityBadge priority={item.priority} />
        <CategoryBadge category={item.category} />
        {item.needs_review && !item.withdrawn && (
          <span className="badge badge-needs-review">⚠ review</span>
        )}
        {item.withdrawn && <span className="badge badge-withdrawn">withdrawn</span>}
        {item.status !== 'pending' && (
          <span className={`badge badge-status-${item.status}`}>{item.status}</span>
        )}
        {item.is_global && <span className="badge badge-global">🌐 global</span>}
        <ItemTimecode item={item} settings={settings} />
      </div>

      <div className="item-note">{item.note}</div>
      <div className="item-quote">{item.quote}</div>

      <div className="item-confidence">
        <span>confidence</span>
        <span className="item-confidence-bar">
          <span className="item-confidence-fill" style={{ width: `${item.confidence * 100}%` }} />
        </span>
        <span style={{ marginLeft: 6 }}>{Math.round(item.confidence * 100)}%</span>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// Detail / edit panel
// ─────────────────────────────────────────────────────────
function DetailPanel({ item, settings, onClose, onItemUpdated, toast }) {
  const [note, setNote] = useState(item.note)
  const [type, setType] = useState(item.type)
  const [category, setCategory] = useState(item.category)
  const [priority, setPriority] = useState(item.priority)
  const [isGlobal, setIsGlobal] = useState(item.is_global)
  const [withdrawn, setWithdrawn] = useState(item.withdrawn)
  const [tcStr, setTcStr] = useState(
    item.anchor_sec !== null && item.anchor_sec !== undefined
      ? secondsToTimecode(item.anchor_sec, settings?.fps, settings?.start_timecode)
      : ''
  )
  const [saving, setSaving] = useState(false)

  const save = async (patch) => {
    setSaving(true)
    try {
      const updated = await patchItem(item.id, patch)
      onItemUpdated(updated)
      toast('Saved', 'success')
    } catch (e) {
      toast(`Save failed: ${e.message}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleBlurNote = () => { if (note !== item.note) save({ note }) }
  const handleBlurType = () => { if (type !== item.type) save({ type }) }
  const handleBlurCategory = () => { if (category !== item.category) save({ category }) }
  const handleBlurPriority = () => { if (priority !== item.priority) save({ priority }) }
  const handleToggleGlobal = (v) => { setIsGlobal(v); save({ is_global: v }) }
  const handleToggleWithdrawn = (v) => { setWithdrawn(v); save({ withdrawn: v }) }

  const handleTcBlur = () => {
    const sec = timecodeToSeconds(tcStr, settings?.fps, settings?.start_timecode)
    if (sec !== null && sec !== item.anchor_sec) save({ anchor_sec: sec })
  }

  const handleApprove = () => save({ status: 'approved', needs_review: false })
  const handleReject  = () => save({ status: 'rejected',  needs_review: false })

  return (
    <div className="detail-panel">
      <div className="detail-header">
        <TypeBadge type={item.type} />
        <PriorityBadge priority={item.priority} />
        <button className="detail-close" onClick={onClose}>✕</button>
      </div>

      <div className="detail-body">
        {/* Quote */}
        <div className="detail-section">
          <div className="detail-label">Client quote</div>
          <div className="detail-quote">{item.quote}</div>
        </div>

        {/* Note */}
        <div className="detail-section">
          <div className="detail-label">Actionable note</div>
          <textarea
            className="detail-input"
            rows={3}
            value={note}
            onChange={e => setNote(e.target.value)}
            onBlur={handleBlurNote}
          />
        </div>

        {/* Type / Category / Priority */}
        <div className="detail-row">
          <div className="detail-section">
            <div className="detail-label">Type</div>
            <select className="detail-select" value={type}
              onChange={e => setType(e.target.value)} onBlur={handleBlurType}>
              <option value="change">Change</option>
              <option value="question">Question</option>
              <option value="approval">Approval</option>
            </select>
          </div>
          <div className="detail-section">
            <div className="detail-label">Priority</div>
            <select className="detail-select" value={priority}
              onChange={e => setPriority(e.target.value)} onBlur={handleBlurPriority}>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
        </div>

        <div className="detail-section">
          <div className="detail-label">Category</div>
          <select className="detail-select" value={category}
            onChange={e => setCategory(e.target.value)} onBlur={handleBlurCategory}>
            <option value="color">Color</option>
            <option value="sound">Sound</option>
            <option value="pacing">Pacing</option>
            <option value="text_graphics">Text / Graphics</option>
            <option value="edit">Edit</option>
            <option value="other">Other</option>
          </select>
        </div>

        {/* Timecode */}
        <div className="detail-section">
          <div className="detail-label">Timecode (HH:MM:SS:FF)</div>
          <input
            className="detail-tc-input"
            type="text"
            value={tcStr}
            placeholder="01:00:00:00"
            onChange={e => setTcStr(e.target.value)}
            onBlur={handleTcBlur}
          />
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
            Anchor: {item.anchor_source} · seg: {item.segment_start_sec?.toFixed(1)}s
          </div>
        </div>

        {/* Toggles */}
        <div className="detail-section">
          <div className="toggle-row">
            <label>Global note (no timecode)</label>
            <label className="switch">
              <input type="checkbox" checked={isGlobal}
                onChange={e => handleToggleGlobal(e.target.checked)} />
              <span className="switch-slider" />
            </label>
          </div>
          <div className="toggle-row">
            <label>Withdrawn by client</label>
            <label className="switch">
              <input type="checkbox" checked={withdrawn}
                onChange={e => handleToggleWithdrawn(e.target.checked)} />
              <span className="switch-slider" />
            </label>
          </div>
        </div>

        {/* Actions */}
        <div className="detail-section">
          <div className="detail-label">Decision</div>
          <div className="detail-actions">
            <button className="btn btn-approve" onClick={handleApprove} disabled={saving}>
              ✓ Approve
            </button>
            <button className="btn btn-reject" onClick={handleReject} disabled={saving}>
              ✕ Reject
            </button>
            {saving && <span className="spinner" />}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// Settings panel
// ─────────────────────────────────────────────────────────
function SettingsPanel({ meetingId, settings, onSaved, toast }) {
  const [form, setForm] = useState({ ...settings })
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await putSettings(meetingId, form)
      await postReanchor(meetingId)
      onSaved(form)
      toast('Settings saved & reanchored', 'success')
    } catch (e) {
      toast(`Error: ${e.message}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  const field = (key, label, type = 'text', step) => (
    <div className="settings-field" key={key}>
      <label>{label}</label>
      <input
        className="settings-input"
        type={type}
        step={step}
        value={form[key]}
        onChange={e => setForm(f => ({ ...f, [key]: type === 'number' ? parseFloat(e.target.value) : e.target.value }))}
      />
    </div>
  )

  return (
    <div className="settings-panel">
      <div className="settings-title">⚙ Project Settings</div>
      <div className="settings-group">
        {field('fps', 'Frame Rate (fps)', 'number', 0.001)}
        {field('start_timecode', 'Start Timecode (HH:MM:SS:FF)')}
        {field('sync_offset_sec', 'Sync Offset (seconds)', 'number', 0.1)}
        {field('lookback_sec', 'Lookback (seconds)', 'number', 0.5)}
        {field('version_label', 'Version Label')}
      </div>
      <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
        {saving ? <><span className="spinner" /> Saving…</> : '💾 Save & Reanchor'}
      </button>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// Meeting page
// ─────────────────────────────────────────────────────────
function MeetingPage({ meetingId, toast, onNotFound }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedItem, setSelectedItem] = useState(null)
  const [editInstructions, setEditInstructions] = useState([])
  const [generatingEdits, setGeneratingEdits] = useState(false)
  const [editError, setEditError] = useState(null)
  const [videoUrl, setVideoUrl] = useState(null)
  const [tab, setTab] = useState('items') // 'items' | 'settings'
  const [filterReview, setFilterReview] = useState(false)
  const videoRef = useRef(null)
  const fileInputRef = useRef(null)

  useEffect(() => {
    setLoading(true)
    setData(null)
    setSelectedItem(null)
    fetchMeeting(meetingId)
      .then(d => {
        setData(d)
        setVideoUrl(d.video_id ? `/api/videos/${d.video_id}/stream` : null)
        fetchEditInstructions(meetingId).then(setEditInstructions).catch(() => setEditInstructions([]))
      })
      .catch(e => {
        if (e.message.includes('404')) {
          toast('Meeting not found (it may have been deleted)', 'error')
          if (onNotFound) onNotFound()
        } else {
          toast(`Failed to load meeting: ${e.message}`, 'error')
        }
      })
      .finally(() => setLoading(false))
  }, [meetingId])

  useEffect(() => {
    if (!meetingId || data?.status !== 'processing') return
    let active = true
    const refresh = async () => {
      try {
        const latest = await fetchMeeting(meetingId)
        if (active) setData(latest)
      } catch (error) {
        if (active) toast(`Transcript processing status failed: ${error.message}`, 'error')
      }
    }
    const timer = setInterval(refresh, 1500)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [meetingId, data?.status, toast])

  const handleItemUpdated = useCallback((updated) => {
    setData(d => ({
      ...d,
      items: d.items.map(i => i.id === updated.id ? updated : i),
    }))
    setSelectedItem(updated)
  }, [])

  const handleGenerateEdits = async () => {
    setGeneratingEdits(true)
    setEditError(null)
    try {
      const generated = await generateEditInstructions(meetingId, data.video_id || null)
      setEditInstructions(generated)
      if (generated.length === 0) {
        setEditError('Qwen returned no edit instructions. Check Ollama and confirm the transcript has actionable change items.')
      } else {
        toast(`Generated ${generated.length} edit instruction${generated.length === 1 ? '' : 's'}`, 'success')
      }
    } catch (error) {
      setEditError(`Edit generation failed: ${error.message}`)
      toast(`Edit generation failed: ${error.message}`, 'error')
    } finally {
      setGeneratingEdits(false)
    }
  }

  const handleEditInstructionUpdated = (updated) => {
    setEditInstructions(current => current.map(instruction =>
      instruction.id === updated.id ? updated : instruction
    ))
  }

  const handleSelectItem = (item) => {
    setSelectedItem(item)
    // Seek video
    if (videoRef.current && item.anchor_sec !== null && item.anchor_sec !== undefined && !item.is_global) {
      videoRef.current.currentTime = item.anchor_sec
    }
  }

  const handleVideoFile = async (e) => {
    const f = e.target.files[0]
    if (!f) return

    try {
      const upload = await uploadVideo(f)
      const videoId = upload.video_id
      if (!videoId) throw new Error('Upload response missing video_id')

      await linkMeetingVideo(meetingId, videoId)
      setData(d => ({ ...d, video_id: videoId }))
      setVideoUrl(`/api/videos/${videoId}/stream`)
      toast('Video uploaded and linked; YOLO indexing started', 'success')
    } catch (err) {
      toast(`Video upload failed: ${err.message}`, 'error')
    }
  }

  const handleApproveAllHighConf = async () => {
    if (!data) return
    const targets = data.items.filter(i => i.confidence >= 0.8 && i.status === 'pending' && !i.withdrawn)
    for (const item of targets) {
      try {
        const updated = await patchItem(item.id, { status: 'approved', needs_review: false })
        handleItemUpdated(updated)
      } catch {}
    }
    toast(`Approved ${targets.length} high-confidence items`, 'success')
  }

  const handleSettingsSaved = (newSettings) => {
    setData(d => ({ ...d, settings: newSettings }))
    // Reload items after reanchor
    fetchMeeting(meetingId).then(d => setData(d)).catch(() => {})
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 10 }}>
        <span className="spinner" />
        <span style={{ color: 'var(--text-secondary)' }}>Loading meeting…</span>
      </div>
    )
  }
  if (!data) return null

  const settings = data.settings || {}
  let items = data.items || []
  // Sort needs_review first
  items = [...items].sort((a, b) => {
    if (a.needs_review && !b.needs_review) return -1
    if (!a.needs_review && b.needs_review) return 1
    return 0
  })
  if (filterReview) items = items.filter(i => i.needs_review)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Tab bar */}
      <div className="tab-bar">
        <button className={`tab ${tab === 'items' ? 'active' : ''}`} onClick={() => setTab('items')}>
          Items ({data.items?.length || 0})
        </button>
        <button className={`tab ${tab === 'vision' ? 'active' : ''}`} onClick={() => setTab('vision')}>
          📹 Video Context
        </button>
        <button className={`tab ${tab === 'edits' ? 'active' : ''}`} onClick={() => setTab('edits')}>
          Edit Instructions ({editInstructions.length})
        </button>
        <button className={`tab ${tab === 'settings' ? 'active' : ''}`} onClick={() => setTab('settings')}>
          ⚙ Settings
        </button>
        <div style={{ flex: 1 }} />
        <div className="export-row" style={{ border: 'none', padding: '0 0 0 8px' }}>
          <a className="btn btn-secondary btn-sm"
            href={exportEdlUrl(meetingId)} download={`${meetingId}.edl`}>
            ⬇ EDL
          </a>
          <a className="btn btn-secondary btn-sm"
            href={exportCsvUrl(meetingId)} download={`${meetingId}.csv`}>
            ⬇ CSV
          </a>
        </div>
      </div>

      {tab === 'settings' ? (
        <div style={{ flex: 1, overflow: 'auto' }}>
          <SettingsPanel
            meetingId={meetingId}
            settings={settings}
            onSaved={handleSettingsSaved}
            toast={toast}
          />
        </div>
      ) : tab === 'vision' ? (
        <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          <VideoContextPanel
            videoId={data.video_id || ''}
            onSeek={(tSec) => {
              if (videoRef.current) videoRef.current.currentTime = tSec
            }}
          />
        </div>
      ) : tab === 'edits' ? (
        <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          <div className="items-header">
            <span className="items-count">Qwen edit instructions</span>
            <span className="items-spacer" />
            <button className="btn btn-primary btn-sm" onClick={handleGenerateEdits} disabled={generatingEdits || !data.items?.length}>
              {generatingEdits ? <><span className="spinner" /> Generating…</> : 'Generate from feedback'}
            </button>
          </div>
          {editError && <div className="alert alert-error">{editError}</div>}
          {editInstructions.length === 0 ? (
            <div className="empty-state">
              No edit instructions yet. Generate them from the transcript feedback.
              {data.video_id ? ' The linked video context and entity intervals will be included in Qwen’s prompt.' : ' Link a video to include visual context.'}
            </div>
          ) : editInstructions.map(instruction => (
            <EditInstructionCard
              key={instruction.id}
              instruction={instruction}
              onUpdate={handleEditInstructionUpdated}
              onSeek={(timeSec) => {
                if (videoRef.current) videoRef.current.currentTime = timeSec
              }}
            />
          ))}
        </div>
      ) : (

        <div className="meeting-layout" style={{ flex: 1, overflow: 'hidden' }}>

          {/* ── Video pane ── */}
          <div className="video-pane">
            <div className="video-header">
              <div className="video-title">
                {data.transcript?.title || meetingId}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept="video/*"
                style={{ display: 'none' }}
                onChange={handleVideoFile}
              />
              <button className="btn btn-secondary btn-sm"
                onClick={() => fileInputRef.current?.click()}>
                📂 Choose video
              </button>
            </div>

            <div className="video-container">
              {videoUrl ? (
                <video
                  ref={videoRef}
                  src={videoUrl}
                  controls
                  style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                />
              ) : (
                <div className="video-placeholder">
                  <div className="video-placeholder-icon">🎬</div>
                  <p>Click "Choose video" to load a local file.<br />No upload — file stays on your machine.</p>
                </div>
              )}
            </div>

            <div className="video-footer">
              {videoRef.current && (
                <VideoTimecodeDisplay videoRef={videoRef} settings={settings} />
              )}
              {!videoRef.current && (
                <span className="current-tc" style={{ color: 'var(--text-muted)' }}>no video loaded</span>
              )}
            </div>
          </div>

          {/* ── Items pane ── */}
          <div className="items-pane">
            <div className="items-header">
              <span className="items-count">{items.length} items</span>
              <button
                className={`toggle-btn ${filterReview ? 'active' : ''}`}
                onClick={() => setFilterReview(f => !f)}
              >
                ⚠ Needs review
              </button>
              <span className="items-spacer" />
            </div>

            <div className="bulk-actions">
              <button className="btn btn-approve btn-sm" onClick={handleApproveAllHighConf}>
                ✓ Approve all high-confidence
              </button>
            </div>

            <div className="items-list">
              {items.length === 0 ? (
                <div className="empty-state">
                  {data.status === 'processing'
                    ? 'Transcript imported. Extracting feedback items…'
                    : data.status === 'failed'
                      ? 'Feedback extraction failed. Re-import the transcript or check the backend log.'
                      : 'No feedback items were extracted from this transcript.'}
                </div>
              ) : (
                items.map(item => (
                  <ItemCard
                    key={item.id}
                    item={item}
                    settings={settings}
                    selected={selectedItem?.id === item.id}
                    onSelect={handleSelectItem}
                  />
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Detail panel */}
      {selectedItem && tab === 'items' && (
        <DetailPanel
          item={selectedItem}
          settings={settings}
          onClose={() => setSelectedItem(null)}
          onItemUpdated={handleItemUpdated}
          toast={toast}
        />
      )}
    </div>
  )
}

// Live timecode display (updates on timeupdate)
function VideoTimecodeDisplay({ videoRef, settings }) {
  const [tc, setTc] = useState('--:--:--:--')
  useEffect(() => {
    const el = videoRef.current
    if (!el) return
    const handler = () => {
      setTc(secondsToTimecode(el.currentTime, settings?.fps, settings?.start_timecode))
    }
    el.addEventListener('timeupdate', handler)
    return () => el.removeEventListener('timeupdate', handler)
  }, [videoRef.current, settings])
  return <span className="current-tc">{tc}</span>
}

// ─────────────────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────────────────
function Sidebar({ activeMeetingId, onSelect, toast }) {
  const [meetings, setMeetings] = useState([])
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)

  const load = useCallback(() => {
    fetchMeetings().then(setMeetings).catch(() => {})
  }, [])

  // Auto-refresh every 5 seconds
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [load])

  const handleImport = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    setUploading(true)
    try {
      const result = await importTranscript(f)
      toast('Transcript imported', 'success')
      load()
      if (result?.meeting_id) onSelect(result.meeting_id)
    } catch (err) {
      toast(`Import failed: ${err.message}`, 'error')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const handleDelete = async (e, id) => {
    e.stopPropagation()
    if (!confirm('Are you sure you want to delete this meeting?')) return
    try {
      await deleteMeeting(id)
      toast('Meeting deleted', 'success')
      if (activeMeetingId === id) onSelect(null)
      load()
    } catch (err) {
      toast(`Delete failed: ${err.message}`, 'error')
    }
  }

  const handleRename = async (e, m) => {
    e.stopPropagation()
    const newTitle = prompt('Enter new title:', m.title || '')
    if (newTitle !== null && newTitle.trim() !== '' && newTitle !== m.title) {
      try {
        await updateMeetingTitle(m.meeting_id, newTitle.trim())
        toast('Title updated', 'success')
        load()
      } catch (err) {
        toast(`Rename failed: ${err.message}`, 'error')
      }
    }
  }

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-title">Meetings</span>
        <button className="btn-icon" onClick={load} title="Refresh">↻</button>
        <input ref={fileRef} type="file" accept=".json,.txt" style={{ display: 'none' }} onChange={handleImport} />
        <button className="btn-icon" onClick={() => fileRef.current?.click()} disabled={uploading} title="Import transcript">
          {uploading ? <span className="spinner" style={{ width: 12, height: 12 }} /> : '⬆'}
        </button>
      </div>

      <div className="meetings-list">
        {meetings.length === 0 ? (
          <div className="empty-state">
            No meetings yet.<br />
            Import a transcript or wait for a Meetily webhook.
          </div>
        ) : (
          meetings.map(m => (
            <div
              key={m.meeting_id}
              className={`meeting-item ${activeMeetingId === m.meeting_id ? 'active' : ''}`}
              onClick={() => onSelect(m.meeting_id)}
            >
              <div className="meeting-item-info">
                <div className="meeting-item-title">
                  {m.title || '(untitled)'}
                  {m.status === 'processing' && <span style={{ marginLeft: 5, fontSize: '0.8em', color: '#ffb86c' }}>(processing...)</span>}
                </div>
                <div className="meeting-item-id">{m.meeting_id}</div>
              </div>
              <div style={{ display: 'flex' }}>
                <button 
                  className="btn-icon" 
                  onClick={(e) => handleRename(e, m)}
                  title="Rename meeting"
                  style={{ marginRight: 5 }}
                >
                  ✎
                </button>
                <button 
                  className="btn-icon delete-btn" 
                  onClick={(e) => handleDelete(e, m.meeting_id)}
                  title="Delete meeting"
                >
                  🗑
                </button>
              </div>
            </div>
          ))

        )}
      </div>

      <div className="upload-zone" onClick={() => fileRef.current?.click()}>
        ⬆ Import transcript file
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// App root
// ─────────────────────────────────────────────────────────
export default function App() {
  const [activeMeetingId, setActiveMeetingId] = useState(null)
  const [meetilyStatus, setMeetilyStatus] = useState(null)
  const { toasts, toast } = useToast()

  useEffect(() => {
    fetchMeetilyStatus()
      .then(s => setMeetilyStatus(s))
      .catch(() => setMeetilyStatus({ status: 'unreachable' }))
  }, [])

  const statusOk = meetilyStatus?.status === 'ok' || meetilyStatus?.status === 'connected'

  return (
    <div className="app-layout">
      {/* Top bar */}
      <div className="topbar">
        <div className="topbar-logo" style={{ cursor: 'pointer' }} onClick={() => setActiveMeetingId(null)}>
          Frame<span>line</span>
        </div>
        <div className="topbar-spacer" />
        <div className="topbar-offline-banner">
          <StatusDot status={statusOk ? 'ok' : 'err'} />
          Running fully offline
        </div>
      </div>

      {/* Main */}
      <div className="main-area">
        <Sidebar activeMeetingId={activeMeetingId} onSelect={setActiveMeetingId} toast={toast} />

        <div className="content-area">
          {activeMeetingId ? (
            <MeetingPage 
              key={activeMeetingId} 
              meetingId={activeMeetingId} 
              toast={toast} 
              onNotFound={() => setActiveMeetingId(null)}
            />
          ) : (
            <div className="welcome">
              <div className="welcome-icon">🎬</div>
              <h2>Welcome to Frameline</h2>
              <p>Select a meeting from the sidebar or import a transcript to begin reviewing client feedback.</p>
            </div>
          )}
        </div>
      </div>

      {/* Toasts */}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast ${t.type}`}>{t.msg}</div>
        ))}
      </div>
    </div>
  )
}
