"use client"

import { useState, useSyncExternalStore } from "react"
import { toast } from "sonner"

import { ApiError, errorMessage } from "@/lib/api"
import { downloadResumePdf } from "@/lib/trial-api"
import { useTailoredCvStore } from "@/store/tailored-cv-store"

const noopSubscribe = () => () => {}

/** The tailored CV a visitor made on the trial page before signing up,
 *  carried over in sessionStorage (see tailored-cv-store.ts). It is not
 *  saved to the account, so the card says so plainly rather than implying
 *  it will still be here next time. */
export function TailoredCvCard() {
  const markdown = useTailoredCvStore((s) => s.markdown)
  const targetTitle = useTailoredCvStore((s) => s.targetTitle)
  const clear = useTailoredCvStore((s) => s.clear)
  const [isExporting, setIsExporting] = useState(false)
  // sessionStorage is invisible to the server render; rendering nothing
  // until the client takes over avoids a hydration mismatch. (false on the
  // server and during hydration, true on the client after.)
  const isClient = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  )

  if (!isClient || !markdown) return null

  async function onDownload() {
    if (!markdown) return
    setIsExporting(true)
    try {
      const blob = await downloadResumePdf({
        tailoredResumeMarkdown: markdown,
        fileName: targetTitle ? `Tailored CV - ${targetTitle}` : "Tailored CV",
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = "tailored-cv.pdf"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(
        error instanceof ApiError && error.status === 429
          ? "Export limit reached for the hour. Try again later."
          : errorMessage(error, "We couldn't build the PDF. Please try again.")
      )
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <section
      data-testid="card-tailored-cv"
      style={{ background: "var(--color-surface)", padding: 32, display: "flex", flexDirection: "column", gap: 16 }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 6 }}>
            Ready to download
          </div>
          <h2 style={{ fontSize: 25, margin: "0 0 6px" }}>
            Your tailored CV{targetTitle ? ` · ${targetTitle}` : ""}
          </h2>
          <p style={{ margin: 0, fontSize: 13, color: "var(--color-neutral-700)", maxWidth: "58ch" }}>
            Download it now. It&apos;s kept in this browser tab only, so it won&apos;t be here after you close it.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="btn btn-primary"
            data-testid="button-download-tailored-cv"
            disabled={isExporting}
            onClick={onDownload}
          >
            {isExporting ? "Building PDF…" : "Download PDF"}
          </button>
          <button type="button" className="btn btn-secondary" data-testid="button-dismiss-tailored-cv" onClick={clear}>
            Dismiss
          </button>
        </div>
      </div>
      <details>
        <summary style={{ cursor: "pointer", fontSize: 13 }}>Preview</summary>
        <pre
          data-testid="text-carried-tailored-cv"
          style={{
            maxHeight: 420,
            overflow: "auto",
            whiteSpace: "pre-wrap",
            background: "var(--color-bg)",
            border: "1px solid var(--color-divider)",
            padding: 16,
            fontSize: 13,
            margin: "12px 0 0",
          }}
        >
          {markdown}
        </pre>
      </details>
    </section>
  )
}
