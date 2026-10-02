/**
 * Convert seconds to HH:MM:SS:FF timecode string.
 * @param {number} seconds
 * @param {number} fps
 * @param {string} startTc  e.g. "01:00:00:00"
 * @returns {string}
 */
export function secondsToTimecode(seconds, fps = 24, startTc = '01:00:00:00') {
  if (seconds === null || seconds === undefined) return '??:??:??:??'

  // Parse startTc into total frames
  const [sh, sm, ss, sf] = startTc.split(':').map(Number)
  const startFrames = ((sh * 3600 + sm * 60 + ss) * fps + sf) | 0

  const totalFrames = Math.max(0, (seconds * fps) | 0) + startFrames
  const framesPerSec = fps | 0
  const framesPerMin = framesPerSec * 60
  const framesPerHour = framesPerMin * 60

  const h  = (totalFrames / framesPerHour) | 0
  const m  = ((totalFrames % framesPerHour) / framesPerMin) | 0
  const s  = ((totalFrames % framesPerMin) / framesPerSec) | 0
  const f  = totalFrames % framesPerSec

  return [h, m, s, f].map(v => String(v).padStart(2, '0')).join(':')
}

/**
 * Parse HH:MM:SS:FF timecode back to seconds (relative to start timecode).
 * @param {string} tc
 * @param {number} fps
 * @param {string} startTc
 * @returns {number}
 */
export function timecodeToSeconds(tc, fps = 24, startTc = '01:00:00:00') {
  const parts = tc.split(':').map(Number)
  if (parts.length !== 4 || parts.some(isNaN)) return null
  const [h, m, s, f] = parts
  const totalSec = h * 3600 + m * 60 + s + f / fps

  const [sh, sm, ss, sf] = startTc.split(':').map(Number)
  const startSec = sh * 3600 + sm * 60 + ss + sf / fps

  return Math.max(0, totalSec - startSec)
}
