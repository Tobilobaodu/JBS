import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"

/** Carries a trial's tailored CV from /try/upload, through /try/signup, to
 *  the dashboard. The rewrite itself is stateless — nothing server-side
 *  holds this Markdown — so without this the CV a visitor just saw would
 *  vanish the moment they signed up.
 *
 *  sessionStorage, not localStorage like the trial/auth stores: it holds a
 *  whole CV plus the name and email read from it, and should not outlive
 *  the tab on a shared computer. It also survives the reload a user might
 *  do mid-sign-up, which plain in-memory state would not. */
type TailoredCvState = {
  markdown: string | null
  targetTitle: string
  /** Pre-fill for /try/signup only — the account stores what was submitted. */
  suggestedName: string
  suggestedEmail: string
  saveForSignup: (fields: {
    markdown: string
    targetTitle: string
    suggestedName: string
    suggestedEmail: string
  }) => void
  clear: () => void
}

const EMPTY = { markdown: null, targetTitle: "", suggestedName: "", suggestedEmail: "" }

export const useTailoredCvStore = create<TailoredCvState>()(
  persist(
    (set) => ({
      ...EMPTY,
      saveForSignup: (fields) => set(fields),
      clear: () => set(EMPTY),
    }),
    {
      name: "tailored-cv",
      storage: createJSONStorage(() => sessionStorage),
    }
  )
)
