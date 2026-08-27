/**
 * The segmented-gradient score bar used identically on Overview, Report
 * detail, and the CVs/Jobs/Recent-matches tables (mockup screens 1-4). Two
 * sizes: "md" is the stacked label/bar/NN-of-100 block (resume-summary
 * grids), "sm" is the compact inline bar+number used inside table cells.
 * `score={null}` renders the mockup's "Scoring…" / em-dash placeholder for
 * a CV or match that hasn't been analysed yet — callers should pass null
 * rather than 0 while a backend analysis job is still running.
 */

const STRIPED_ACCENT =
  "repeating-linear-gradient(90deg, var(--color-accent) 0 3px, transparent 3px 5px)"
const STRIPED_NEUTRAL =
  "repeating-linear-gradient(90deg, var(--color-neutral-400) 0 3px, transparent 3px 5px)"

export function ScoreBar({
  score,
  note,
  size = "md",
  width,
}: {
  score: number | null
  note?: string
  size?: "md" | "sm"
  width?: number
}) {
  const clamped = score == null ? null : Math.max(0, Math.min(100, score))
  const barHeight = size === "sm" ? 10 : 16

  const bar = (
    <div
      style={{
        display: "flex",
        height: barHeight,
        gap: 2,
        width: size === "sm" ? (width ?? 96) : undefined,
      }}
    >
      {clamped != null && (
        <div style={{ width: `${clamped}%`, background: STRIPED_ACCENT }} />
      )}
      <div style={{ flex: 1, background: STRIPED_NEUTRAL }} />
    </div>
  )

  if (size === "sm") {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {bar}
        {clamped == null ? (
          <span style={{ fontSize: 13, color: "var(--color-neutral-600)" }}>—</span>
        ) : (
          <span style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 13 }}>
            {Math.round(clamped)}
          </span>
        )}
      </div>
    )
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {bar}
      {clamped == null ? (
        <span style={{ fontSize: 13, color: "var(--color-neutral-600)" }}>Scoring…</span>
      ) : (
        <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
          <div style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 20 }}>
            {Math.round(clamped)}
            <span style={{ fontSize: 13, color: "var(--color-neutral-600)" }}>/100</span>
          </div>
          {note && (
            <div style={{ fontSize: 12, lineHeight: 1.4, color: "var(--color-neutral-700)" }}>
              {note}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
