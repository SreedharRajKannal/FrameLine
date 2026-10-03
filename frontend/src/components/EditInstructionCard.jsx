import React, { useEffect, useState } from 'react'
import { patchEditInstruction, renderEditPreview } from '../api'

export default function EditInstructionCard({ instruction, onUpdate, onSeek }) {
  const [inst, setInst] = useState(instruction)
  const [rendering, setRendering] = useState(false)
  const [showPreviewModal, setShowPreviewModal] = useState(false)

  useEffect(() => {
    setInst(instruction)
  }, [instruction])

  async function handleStatusChange(newStatus) {
    try {
      const updated = await patchEditInstruction(inst.id, { status: newStatus })
      setInst(updated)
      if (onUpdate) onUpdate(updated)
    } catch (err) {
      alert(`Error updating edit instruction: ${err.message}`)
    }
  }

  async function handleRenderPreview() {
    setRendering(true)
    try {
      const res = await renderEditPreview(inst.id)
      setInst((prev) => ({ ...prev, preview_path: res.preview_path }))
      setShowPreviewModal(true)
    } catch (err) {
      alert(`Error rendering preview: ${err.message}`)
    } finally {
      setRendering(false)
    }
  }

  async function handleSelectInterval(interval) {
    try {
      const updated = await patchEditInstruction(inst.id, {
        start_sec: interval.start_sec,
        end_sec: interval.end_sec,
        ambiguous: false,
      })
      setInst(updated)
      if (onUpdate) onUpdate(updated)
    } catch (err) {
      alert(`Error setting interval: ${err.message}`)
    }
  }

  return (
    <div className={`edit-instruction-card status-${inst.status}`}>
      <div className="card-header">
        <div className="card-header-main">
          <span className="effect-badge">{inst.effect.toUpperCase().replaceAll('_', ' ')}</span>
          {inst.is_global && <span className="global-instruction-badge">GLOBAL · START</span>}
          {inst.target_entity && (
            <span className="target-chip">Target: {inst.target_entity}</span>
          )}
        </div>
        <span className="confidence-pill">{(inst.confidence * 100).toFixed(0)}% confidence</span>
      </div>

      <div className="card-body">
        <p className="reason-text">{inst.reason || 'Proposed from transcript feedback.'}</p>

        {/* Time Interval & Filter info */}
        <div className="interval-info">
          <span>{inst.is_global ? 'Global range: ' : 'Interval: '}</span>
          <button className="btn-link" onClick={() => onSeek && onSeek(inst.start_sec)}>
            {inst.is_global ? 'from beginning · ' : ''}{inst.start_sec.toFixed(1)}s - {inst.end_sec.toFixed(1)}s
          </button>
        </div>

        {inst.filter_string && (
          <div className="filter-string-code">
            <code title={inst.filter_string}>ffmpeg -vf &quot;{inst.filter_string}&quot;</code>
          </div>
        )}

        {/* Ambiguity Picker */}
        {inst.ambiguous && inst.candidate_intervals?.length > 1 && (
          <div className="ambiguity-picker">
            <span className="picker-label">Multiple matches found. Select the target interval:</span>
            <div className="candidate-list">
              {inst.candidate_intervals.map((iv, idx) => (
                <button
                  key={idx}
                  className="btn btn-sm btn-outline"
                  onClick={() => handleSelectInterval(iv)}
                >
                  {iv.start_sec.toFixed(1)}s - {iv.end_sec.toFixed(1)}s
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="card-actions">
        <button
          className="btn btn-sm btn-secondary"
          onClick={handleRenderPreview}
          disabled={rendering}
        >
          {rendering ? 'Rendering preview…' : inst.preview_path ? 'Watch Preview' : 'Render Preview'}
        </button>

        <div className="btn-group">
          <button
            className={`btn btn-sm ${inst.status === 'approved' ? 'btn-success' : 'btn-outline'}`}
            onClick={() => handleStatusChange('approved')}
          >
            {inst.status === 'approved' ? 'Approved' : 'Approve'}
          </button>
          <button
            className={`btn btn-sm ${inst.status === 'rejected' ? 'btn-danger' : 'btn-outline'}`}
            onClick={() => handleStatusChange('rejected')}
          >
            {inst.status === 'rejected' ? 'Rejected' : 'Reject'}
          </button>
        </div>
      </div>

      {/* Side-by-side Preview Modal */}
      {showPreviewModal && inst.preview_path && (
        <div className="preview-modal-overlay" onClick={() => setShowPreviewModal(false)}>
          <div className="preview-modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h4>Before / After Side-by-Side Preview</h4>
              <button className="btn-close" onClick={() => setShowPreviewModal(false)}>✕</button>
            </div>
            <div className="video-preview-wrapper">
              <video
                src={`/${inst.preview_path}`}
                controls
                autoPlay
                style={{ width: '100%', maxHeight: '400px', borderRadius: '8px' }}
              />
            </div>
            <p className="subtle text-center">Left: Original | Right: Filter Applied ({inst.effect})</p>
          </div>
        </div>
      )}
    </div>
  )
}
