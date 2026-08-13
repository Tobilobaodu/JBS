"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/store/auth-store"

/**
 * Gates authenticated routes. Waits for the Zustand `persist` middleware to
 * rehydrate from localStorage before deciding to redirect — otherwise every
 * dashboard page would bounce to /login for a logged-in user on first paint,
 * since the server-rendered default state has no token yet.
 */
export function useRequireAuth() {
  const router = useRouter()
  const accessToken = useAuthStore((state) => state.accessToken)
  // zustand's persist middleware never attaches `.persist` when `window` is
  // undefined (Next.js's server-side render pass of this client component) —
  // treat that as "not hydrated yet", which is accurate: there's no
  // localStorage to hydrate from on the server anyway.
  const [hasHydrated, setHasHydrated] = useState(
    () => useAuthStore.persist?.hasHydrated() ?? false
  )

  useEffect(() => {
    // Defensive re-check for the narrow race between the useState
    // initializer above running and this effect attaching — hydration can
    // complete in that window. Intentional synchronous setState, not a
    // derived-state anti-pattern.
    if (useAuthStore.persist.hasHydrated()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHasHydrated(true)
    }
    return useAuthStore.persist.onFinishHydration(() => setHasHydrated(true))
  }, [])

  useEffect(() => {
    if (hasHydrated && !accessToken) {
      router.replace("/login")
    }
  }, [hasHydrated, accessToken, router])

  return { isReady: hasHydrated && !!accessToken }
}
