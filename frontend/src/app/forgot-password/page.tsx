"use client"

import { useState } from "react"
import Image from "next/image"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { toast } from "sonner"

import mailSentIcon from "@/assets/auth/icon-mail-sent.svg"
import { AuthShell } from "@/components/auth/auth-shell"
import { EmailField } from "@/components/auth/fields"
import styles from "@/components/auth/auth.module.css"
import { forgotPasswordSchema, type ForgotPasswordFormValues } from "@/lib/schemas/auth"
import { requestPasswordReset } from "@/lib/auth-api"
import { ApiError, errorMessage } from "@/lib/api"

// "Login Journey" Figma: 8:125 (Forgot password) and, once sent, 8:164
// (Reset confirmation), which keeps the form below so the user can resend.
export default function ForgotPasswordPage() {
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState<string | null>(null)

  const form = useForm<ForgotPasswordFormValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: "" },
  })
  const { errors } = form.formState

  async function onSubmit(values: ForgotPasswordFormValues) {
    setIsSubmitting(true)
    setUnavailable(null)
    try {
      await requestPasswordReset(values.email)
      setSentTo(values.email)
    } catch (error) {
      if (error instanceof ApiError && error.status === 503) {
        // The server has no email configured — say so rather than
        // pretending a link is on its way.
        setUnavailable(errorMessage(error, "Password reset by email isn't available right now."))
      } else if (error instanceof ApiError && error.status === 429) {
        toast.error(errorMessage(error, "Too many reset requests. Please wait and try again."))
      } else {
        toast.error(errorMessage(error, "We couldn't send the reset link. Please try again."))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthShell>
      <div className={styles.card} style={{ gap: sentTo ? 30 : 20 }}>
        <div className={styles.titleBlock}>
          <h1 className={styles.title}>Forgotten your password?</h1>
          <p className={styles.subtitle}>
            We’ll send a link to your email address with instructions about how to reset your
            password.
          </p>
        </div>

        {sentTo && (
          <div className={styles.successBox} role="status">
            <span className={styles.successIcon}>
              <Image src={mailSentIcon} alt="" width={24} height={24} unoptimized />
            </span>
            {/* The design says "has been sent to [email]". The server won't
                reveal whether that email has an account, so neither can we. */}
            <div className={styles.successText}>
              <p>If there’s an account for {sentTo}, password reset instructions have been sent to it.</p>
              <p>If you haven’t received it, please check your spam folder or try again below.</p>
            </div>
          </div>
        )}

        <form className={styles.form} onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <div className={styles.fields}>
            <EmailField
              id="forgot-email"
              label="Email address"
              registration={form.register("email", { onChange: () => setUnavailable(null) })}
              invalid={Boolean(errors.email)}
              message={errors.email?.message ?? unavailable ?? undefined}
            />
          </div>

          <div className={styles.actions}>
            <button type="submit" className={styles.button} disabled={isSubmitting}>
              {isSubmitting ? "Sending…" : "Reset password"}
            </button>
            <p className={`${styles.switchText} ${styles.switchTextWide}`}>
              {sentTo ? "Remembered your password?, " : "Remember your password?, "}
              <Link href="/login">{sentTo ? "Click here" : "click here"}</Link> to sign in.
            </p>
          </div>
        </form>
      </div>
    </AuthShell>
  )
}
