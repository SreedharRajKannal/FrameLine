import React, { useState, useEffect } from 'react'
import { fetchVisionStatus, fetchVideoContext, fetchEntities, triggerVisionPass } from '../api'

export default function VideoContextPanel({ videoId, onSeek }) {
  const [status, setStatus] = useState(null)
  const [context, setContext] = useState(null)
  const [entities, setEntities] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!videoId) return
    loadData()
    const timer = setInterval(pollStatus, 3000)
    return () => clearInterval(timer)
  }, [videoId])

  async function loadData() {
    try {
      const s = await fetchVisionStatus(videoId).catch(() => null)
      if (s) setStatus(s)
      const ctx = await fetchVideoContext(videoId).catch(() => null)
      if (ctx) setContext(ctx)
      const ents = await fetchEntities(videoId).catch(() => [])
      if (ents) setEntities(ents)
    } catch (err) {
      logger.error(err)
    }
  }

  async function pollStatus() {
    if (!videoId) return
    const s = await fetchVisionStatus(videoId).catch(() => null)
    if (s) {
      setStatus(s)
      if (s.status === 'completed' && (!context || !entities.length)) {
        loadData()
      }
    }
  }

  async function handleRunVision() {
    if (!videoId) return
    setLoading(true)
    setError(null)
    try {
      await triggerVisionPass(videoId)
      await pollStatus()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (!videoId) {
    return (
      <div className="panel video-context-panel empty">
        <p className="subtle">No video linked to this meeting yet.</p>
      </div>
    )
  }

  return (
    <div className="panel video-context-panel">
      <div className="panel-header">
        <h3>📹 Video Context & MiniCPM-V Vision</h3>
        {(!status || status.status === 'not_started') && (
          <button className="btn btn-sm btn-primary" onClick={handleRunVision} disabled={loading}>
            {loading ? 'Starting...' : '⚡ Run Vision Pass'}
          </button>
        )}
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Progress Bar & Buffering Indicator */}
      {status && status.status === 'running' && (
        <div className="vision-progress-card">
          <div className="progress-bar-container">
            <div
              className="progress-bar-fill"
              style={{ width: `${Math.min(100, status.progress_pct || 0)}%` }}
            />
          </div>
          <p className="progress-text" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="spinner" style={{ width: 14, height: 14 }} />
            <span>⏳ MiniCPM-V Analyzing Video Context: {status.progress_pct}%</span>
            <span className="subtle">{status.message}</span>
          </p>
        </div>
      )}


      {/* Global Summary */}
      {context && (
        <div className="video-summary-box">
          <p><strong>Global Context:</strong> {context.global_summary}</p>
        </div>
      )}

      {/* Entity Index */}
      {entities.length > 0 && (
        <div className="entity-index-section">
          <h4>🏷️ Entity Index ({entities.length})</h4>
          <div className="entity-chip-list">
            {entities.map((ent) => (
              <div key={ent.key} className="entity-chip">
                <span className="entity-name">{ent.key}</span>
                {ent.color && <span className="entity-color">({ent.color})</span>}
                <div className="entity-intervals">
                  {ent.intervals?.map((iv, idx) => (
                    <button
                      key={idx}
                      className="btn-time-badge"
                      onClick={() => onSeek && onSeek(iv.start_sec)}
                      title={`Seek to ${iv.start_sec}s`}
                    >
                      {iv.start_sec.toFixed(1)}s - {iv.end_sec.toFixed(1)}s
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Scene Timeline */}
      {context?.scene_segments?.length > 0 && (
        <div className="scene-timeline-section">
          <h4>🎬 Scene Timeline</h4>
          <div className="scene-list">
            {context.scene_segments.map((seg, idx) => (
              <div
                key={idx}
                className="scene-card"
                onClick={() => onSeek && onSeek(seg.start_sec)}
              >
                <div className="scene-time">
                  {seg.start_sec.toFixed(1)}s - {seg.end_sec.toFixed(1)}s
                </div>
                <div className="scene-info">
                  <p className="scene-desc">{seg.summary}</p>
                  {seg.key_objects?.length > 0 && (
                    <div className="scene-tags">
                      {seg.key_objects.map((obj) => (
                        <span key={obj} className="tag">{obj}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
