import { create } from "zustand"
import { persist } from "zustand/middleware"

export type AuthUser = {
  id: string
  email: string
}

type AuthState = {
  accessToken: string | null
  user: AuthUser | null
  setAuth: (accessToken: string, user: AuthUser) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      user: null,
      setAuth: (accessToken, user) => set({ accessToken, user }),
      clearAuth: () => set({ accessToken: null, user: null }),
    }),
    {
      name: "auth-storage",
    }
  )
)

export function isAuthenticated(): boolean {
  return useAuthStore.getState().accessToken !== null
}
