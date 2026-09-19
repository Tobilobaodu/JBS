"use client"

import { useState, useSyncExternalStore } from "react"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { toast } from "sonner"

import { AuthShell } from "@/components/auth/auth-shell"
import { EmailField, PasswordField } from "@/components/auth/fields"
import styles from "@/components/auth/auth.module.css"
import { loginSchema, type LoginFormValues } from "@/lib/schemas/auth"
import { loginAccount } from "@/lib/auth-api"
import { ApiError, errorMessage } from "@/lib/api"
import { useAuthStore } from "@/store/auth-store"
import { usePostAuthRedirect } from "@/hooks/use-post-auth-redirect"

// /reset-password sends people here as /login?reset=done. Read from
// location rather than useSearchParams so the page needs no Suspense
// boundary; the server snapshot is "no notice".
const noop = () => () => {}
const readResetDone = () => new URLSearchParams(window.location.search).get("reset") === "done"

// Built from the "Login Journey" Figma: 8:47 (Login) and 8:86 (Login – Error).
export default function LoginPage() {
  const redirectAfterAuth = usePostAuthRedirect()
  const setAuth = useAuthStore((state) => state.setAuth)
  const [isSubmitting, setIsSubmitting] = useState(false)
  // A 401 is shown on the form (both fields red), not as a toast. One
  // message for both cases on purpose: the API doesn't reveal whether the
  // email exists (security plan: no user enumeration), so neither do we.
  const [wrongCredentials, setWrongCredentials] = useState(false)
  const passwordWasReset = useSyncExternalStore(noop, readResetDone, () => false)

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  })
  const { errors } = form.formState

  // Editing either field clears the stale "wrong combination" state.
  const clearCredentialsError = () => setWrongCredentials(false)
  const emailField = form.register("email", { onChange: clearCredentialsError })
  const passwordField = form.register("password", { onChange: clearCredentialsError })

  async function onSubmit(values: LoginFormValues) {
    setIsSubmitting(true)
    setWrongCredentials(false)
    try {
      const result = await loginAccount(values.email, values.password)
      setAuth(
        result.accessToken,
        {
          id: result.user.id,
          email: result.user.email,
        },
        // Stored so an expired access token can be renewed silently
        // (lib/api.ts) instead of forcing this form again.
        result.refreshToken
      )
      await redirectAfterAuth()
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setWrongCredentials(true)
      } else if (error instanceof ApiError && error.status === 429) {
        toast.error(errorMessage(error, "Too many attempts. Please wait and try again."))
      } else {
        toast.error(errorMessage(error, "We couldn't log you in. Please try again."))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const passwordMessage = errors.password?.message
    ?? (wrongCredentials ? "Wrong email address and password combination" : undefined)

  return (
    <AuthShell>
      <div className={styles.card}>
        <h1 className={styles.title}>Login</h1>
        {passwordWasReset && (
          <div className={styles.successBox} role="status">
            Your password has been changed. Log in with your new password.
          </div>
        )}
        <form className={styles.form} onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <div className={styles.fields}>
            <EmailField
              id="login-email"
              label="Email address"
              registration={emailField}
              invalid={Boolean(errors.email) || wrongCredentials}
              message={errors.email?.message}
            />
            <PasswordField
              id="login-password"
              label="Password"
              registration={passwordField}
              invalid={Boolean(errors.password) || wrongCredentials}
              message={passwordMessage}
              footer={
                <Link href="/forgot-password" className={styles.smallLink}>
                  Reset password
                </Link>
              }
            />
          </div>

          <div className={styles.actions}>
            <button type="submit" className={styles.button} disabled={isSubmitting}>
              {isSubmitting ? "Logging in…" : "Login"}
            </button>
            <p className={styles.switchText}>
              Don’t have an account yet, <Link href="/register">click here</Link> to sign up.
            </p>
          </div>
        </form>
      </div>
    </AuthShell>
  )
}
