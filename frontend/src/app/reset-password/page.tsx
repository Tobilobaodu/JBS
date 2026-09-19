"use client"

import { useState, useSyncExternalStore } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { toast } from "sonner"

import { AuthShell } from "@/components/auth/auth-shell"
import { PasswordField } from "@/components/auth/fields"
import styles from "@/components/auth/auth.module.css"
import { resetPasswordSchema, type ResetPasswordFormValues } from "@/lib/schemas/auth"
import { confirmPasswordReset } from "@/lib/auth-api"
import { ApiError, errorMessage } from "@/lib/api"
import { useAuthStore } from "@/store/auth-store"

// Where the emailed link lands: /reset-password#token=…  The token rides
// in the fragment, which browsers never send to a server, so it stays out
// of access logs and Referer headers. Not in the Figma file; built from the
// same card, field and button as the other login-journey screens.

const subscribe = (onChange: () => void) => {
  window.addEventListener("hashchange", onChange)
  return () => window.removeEventListener("hashchange", onChange)
}
const readToken = () => new URLSearchParams(window.location.hash.slice(1)).get("token") ?? ""

export default function ResetPasswordPage() {
  const router = useRouter()
  // Server snapshot is null (unknown) so nothing flashes before hydration.
  const token = useSyncExternalStore<string | null>(subscribe, readToken, () => null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [linkInvalid, setLinkInvalid] = useState(false)

  const form = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { password: "" },
  })
  const { errors } = form.formState

  async function onSubmit(values: ResetPasswordFormValues) {
    if (!token) return
    setIsSubmitting(true)
    try {
      await confirmPasswordReset(token, values.password)
      // The backend revoked every session of this account; drop any stale
      // one this browser was holding too.
      useAuthStore.getState().clearAuth()
      router.push("/login?reset=done")
    } catch (error) {
      if (error instanceof ApiError && error.status === 400) {
        setLinkInvalid(true)
      } else if (error instanceof ApiError && error.status === 429) {
        toast.error(errorMessage(error, "Too many attempts. Please wait and try again."))
      } else {
        toast.error(errorMessage(error, "We couldn't change your password. Please try again."))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const requestNewLink = <Link href="/forgot-password">request a new link</Link>

  return (
    <AuthShell>
      <div className={styles.card}>
        <div className={styles.titleBlock}>
          <h1 className={styles.title}>Choose a new password</h1>
          <p className={styles.subtitle}>
            Use at least 12 characters. You’ll be signed out everywhere and can log in with the
            new password straight away.
          </p>
        </div>

        {token === "" ? (
          <p className={styles.errorText} role="alert">
            This reset link is incomplete. Please {requestNewLink}.
          </p>
        ) : (
          <form className={styles.form} onSubmit={form.handleSubmit(onSubmit)} noValidate>
            <div className={styles.fields}>
              <PasswordField
                id="reset-password"
                label="New password"
                autoComplete="new-password"
                registration={form.register("password")}
                invalid={Boolean(errors.password) || linkInvalid}
                message={
                  errors.password?.message ??
                  (linkInvalid ? (
                    <>This reset link is invalid or has expired. Please {requestNewLink}.</>
                  ) : undefined)
                }
              />
            </div>
            <div className={styles.actions}>
              <button type="submit" className={styles.button} disabled={isSubmitting || !token}>
                {isSubmitting ? "Saving…" : "Save password"}
              </button>
              <p className={`${styles.switchText} ${styles.switchTextWide}`}>
                Remembered your password?, <Link href="/login">click here</Link> to sign in.
              </p>
            </div>
          </form>
        )}
      </div>
    </AuthShell>
  )
}
