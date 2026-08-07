/** Formatting shared by the views, so one lap time reads like every other. */

/** Seconds as m:ss.mmm, the form a lap time is read in. */
export function lapTime(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—'
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds - minutes * 60).toFixed(3).padStart(6, '0')}`
}

/** A signed gap in seconds, with the sign carried by a glyph rather than a hue. */
export function gap(seconds, digits = 3) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—'
  return `${seconds >= 0 ? '+' : '−'}${Math.abs(seconds).toFixed(digits)}`
}

/**
 * A recording's car, split into the entry and the series it ran in.
 *
 * `CarName` is recorded as e.g. `Team WRT 2025 #46:LM` - the entry, not the
 * vehicle. The file has no field naming the model, so this does not invent
 * one: it splits the entry from its series tag and shows both as recorded.
 */
export function carEntry(name) {
  if (!name) return { entry: '—', series: null }
  const at = name.lastIndexOf(':')
  if (at < 0) return { entry: name, series: null }
  return { entry: name.slice(0, at), series: name.slice(at + 1) }
}
