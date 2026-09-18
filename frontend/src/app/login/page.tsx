"use client"

import { useState } from "react"
import Image from "next/image"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { toast } from "sonner"

import eyeIcon from "@/assets/auth/icon-eye.svg"
import warningIcon from "@/assets/auth/icon-warning.svg"
import { AuthShell } from "@/components/auth/auth-shell"
import styles from "@/components/auth/auth.module.css"
import { loginSchema, type LoginFormValues } from "@/lib/schemas/auth"
import { loginAccount } from "@/lib/auth-api"
import { ApiError, errorMessage } from "@/lib/api"
import { useAuthStore } from "@/store/auth-store"
import { usePostAuthRedirect } from "@/hooks/use-post-auth-redirect"

// Built from the "Login Journey" Figma: 8:47 (Login) and 8:86 (Login – Error).
export default function LoginPage() {
  const redirectAfterAuth = usePostAuthRedirect()
  const setAuth = useAuthStore((state) => state.setAuth)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  // A 401 is shown on the form (both fields red), not as a toast. One
  // message for both cases on purpose: the API doesn't reveal whether the
  // email exists (security plan: no user enumeration), so neither do we.
  const [wrongCredentials, setWrongCredentials] = useState(false)

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

  const emailInvalid = Boolean(errors.email) || wrongCredentials
  const passwordInvalid = Boolean(errors.password) || wrongCredentials
  const passwordMessage = errors.password?.message
    ?? (wrongCredentials ? "Wrong email address and password combination" : null)

  return (
    <AuthShell>
      <div className={styles.card}>
        <h1 className={styles.title}>Login</h1>
        <form className={styles.form} onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <div className={styles.fields}>
            <div className={styles.field}>
              <label htmlFor="login-email" className={styles.label}>
                Email address <span className={styles.required} aria-hidden="true">*</span>
              </label>
              <div className={`${styles.inputBox} ${emailInvalid ? styles.inputBoxError : ""}`}>
                <input
                  id="login-email"
                  type="email"
                  autoComplete="email"
                  placeholder="email@domain.com"
                  required
                  aria-invalid={emailInvalid}
                  aria-describedby={errors.email ? "login-email-error" : undefined}
                  className={styles.input}
                  {...emailField}
                />
                {errors.email && (
                  <span className={styles.inputIcon}>
                    <Image src={warningIcon} alt="" width={23} height={23} unoptimized />
                  </span>
                )}
              </div>
              {errors.email && (
                <p id="login-email-error" className={styles.errorText}>{errors.email.message}</p>
              )}
            </div>

            <div className={styles.field}>
              <label htmlFor="login-password" className={styles.label}>
                Password <span className={styles.required} aria-hidden="true">*</span>
              </label>
              <div className={`${styles.inputBox} ${passwordInvalid ? styles.inputBoxError : ""}`}>
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="******"
                  required
                  aria-invalid={passwordInvalid}
                  aria-describedby={passwordMessage ? "login-password-error" : undefined}
                  className={`${styles.input} ${styles.passwordInput}`}
                  {...passwordField}
                />
                <button
                  type="button"
                  className={styles.inputIcon}
                  onClick={() => setShowPassword((s) => !s)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                >
                  <Image src={eyeIcon} alt="" width={23} height={23} unoptimized />
                </button>
              </div>
              {passwordMessage && (
                <p id="login-password-error" role="alert" className={styles.errorText}>
                  {passwordMessage}
                </p>
              )}
            </div>
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
