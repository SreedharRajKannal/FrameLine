import React, { useState, useEffect, useRef } from 'react'
import { fetchVisionStatus, fetchVideoContext, fetchEntities, triggerVisionPass } from '../api'

export default function VideoContextPanel({ videoId, onSeek }) {
  const [status, setStatus] = useState(null)
  const [context, setContext] = useState(null)
  const [entities, setEntities] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const loadedVideoId = useRef('')

  useEffect(() => {
    setStatus(null)
    setContext(null)
    setEntities([])
    setError(null)
    loadedVideoId.current = ''
    if (!videoId) return
    pollStatus()
    const timer = setInterval(pollStatus, 2000)
    return () => clearInterval(timer)
  }, [videoId])

  async function loadData() {
    try {
      const [ctx, ents] = await Promise.all([
        fetchVideoContext(videoId),
        fetchEntities(videoId),
      ])
      setContext(ctx)
      setEntities(ents)
      setError(null)
      loadedVideoId.current = videoId
    } catch (err) {
      setError(`Could not load video context: ${err.message}`)
    }
  }

  async function pollStatus() {
    if (!videoId) return
    const s = await fetchVisionStatus(videoId).catch(() => null)
    if (s) {
      setStatus(s)
      if (s.status === 'completed' && loadedVideoId.current !== videoId) await loadData()
      if (s.status === 'failed') setError(s.message || 'YOLO indexing failed')
    }
  }

  async function handleRunAnalysis() {
    if (!videoId) return
    setLoading(true)
    setError(null)
    setContext(null)
    setEntities([])
    loadedVideoId.current = ''
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
        <h3>Video Context & Frame Analysis</h3>
        {status?.status !== 'running' && (
          <button className="btn btn-sm btn-primary" onClick={handleRunAnalysis} disabled={loading}>
            {loading ? 'Starting...' : context ? 'Re-analyze Frames' : 'Analyze Frames'}
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
            <span>YOLO indexing: {status.progress_pct}%</span>
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

      {!context && status?.status === 'running' && (
        <p className="subtle">Waiting for YOLO to finish indexing this video…</p>
      )}

      {!context && status?.status === 'completed' && !error && (
        <p className="subtle">YOLO indexing completed; no context was returned.</p>
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
