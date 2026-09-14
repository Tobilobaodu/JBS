"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { toast } from "sonner"

import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { trialSignupSchema, type TrialSignupFormValues } from "@/lib/schemas/auth"
import { loginAccount, registerAccount } from "@/lib/auth-api"
import { claimTrialSession } from "@/lib/trial-api"
import { ApiError, errorMessage } from "@/lib/api"
import { useAuthStore } from "@/store/auth-store"
import { useTrialStore } from "@/store/trial-store"
import { useTailoredCvStore } from "@/store/tailored-cv-store"

/** Step after "Continue" on /try/upload: name and email pre-filled from the
 *  CV, one password field, then straight to the dashboard — where the
 *  tailored CV carried in useTailoredCvStore can be downloaded. Separate
 *  from /register, which stays the plain sign-up for people arriving
 *  without a trial. */
export default function TrialSignupPage() {
  const router = useRouter()
  const setAuth = useAuthStore((s) => s.setAuth)
  const isAuthenticated = useAuthStore((s) => !!s.accessToken)
  const trialSessionId = useTrialStore((s) => s.trialSessionId)
  const markTrialSessionClaimed = useTrialStore((s) => s.markTrialSessionClaimed)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [emailTaken, setEmailTaken] = useState(false)

  const form = useForm<TrialSignupFormValues>({
    resolver: zodResolver(trialSignupSchema),
    defaultValues: { fullName: "", email: "", password: "" },
  })

  // Pre-fill after mount rather than via defaultValues: the store is read
  // from sessionStorage, which the server render can't see, so filling it
  // during render would mismatch on hydration.
  useEffect(() => {
    if (isAuthenticated) {
      router.replace("/dashboard")
      return
    }
    const apply = () => {
      const { markdown, suggestedName, suggestedEmail } = useTailoredCvStore.getState()
      if (!markdown) {
        // Reached directly, or the tab was closed and reopened: there is
        // nothing to carry over, so send them to start the trial.
        router.replace("/try/upload")
        return
      }
      form.reset({ fullName: suggestedName, email: suggestedEmail, password: "" })
    }
    if (useTailoredCvStore.persist.hasHydrated()) apply()
    else return useTailoredCvStore.persist.onFinishHydration(apply)
    // Runs once on arrival; form and router are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function onSubmit(values: TrialSignupFormValues) {
    setIsSubmitting(true)
    setEmailTaken(false)
    try {
      await registerAccount(values.email, values.password, values.fullName)
      // /auth/register returns no token — log in straight after.
      const loginResult = await loginAccount(values.email, values.password)
      setAuth(
        loginResult.accessToken,
        {
          id: loginResult.user.id,
          email: loginResult.user.email,
          fullName: loginResult.user.fullName ?? values.fullName,
        },
        loginResult.refreshToken
      )
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setEmailTaken(true)
      } else if (error instanceof ApiError && error.status === 429) {
        toast.error(errorMessage(error, "Too many attempts. Please wait and try again."))
      } else {
        toast.error(errorMessage(error, "Could not create your account."))
      }
      setIsSubmitting(false)
      return
    }

    // Attach the trial's CV to the new account. Not fatal: the account
    // exists and the tailored CV is still carried client-side, so a failed
    // claim is surfaced but doesn't stop them reaching the dashboard.
    if (trialSessionId) {
      try {
        await claimTrialSession(trialSessionId)
        markTrialSessionClaimed()
      } catch (error) {
        toast.error(errorMessage(error, "Your uploaded CV couldn't be attached to this account."))
      }
    }
    router.push("/dashboard")
  }

  return (
    <div style={{ maxWidth: 420, margin: "0 auto", padding: "96px 24px" }}>
      <h1 style={{ fontSize: 32, margin: "0 0 8px" }}>SAVE YOUR TAILORED CV</h1>
      <p style={{ margin: "0 0 24px", fontSize: 14, color: "var(--color-neutral-700)" }}>
        Create your account to download it. We&apos;ve filled in your name and email from your
        CV. Check they&apos;re right.
      </p>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          style={{ display: "flex", flexDirection: "column", gap: 20 }}
          noValidate
        >
          <FormField
            control={form.control}
            name="fullName"
            render={({ field }) => (
              <FormItem className="field">
                <FormLabel>Full name</FormLabel>
                <FormControl>
                  <input
                    type="text"
                    autoComplete="name"
                    className="input"
                    data-testid="input-signup-name"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem className="field">
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <input
                    type="email"
                    autoComplete="email"
                    className="input"
                    data-testid="input-signup-email"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          {emailTaken && (
            <p
              role="alert"
              data-testid="status-email-taken"
              style={{ margin: "-8px 0 0", fontSize: 13, color: "var(--color-accent-700)" }}
            >
              An account with this email already exists.{" "}
              <Link href="/login">Log in instead</Link>
            </p>
          )}
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem className="field">
                <FormLabel>Password</FormLabel>
                <div style={{ display: "flex", gap: 8 }}>
                  <FormControl>
                    <input
                      type={showPassword ? "text" : "password"}
                      autoComplete="new-password"
                      className="input"
                      style={{ flex: 1, minWidth: 0 }}
                      data-testid="input-signup-password"
                      {...field}
                    />
                  </FormControl>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    data-testid="button-toggle-password"
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword((v) => !v)}
                  >
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
                <p style={{ margin: 0, fontSize: 12, color: "var(--color-neutral-600)" }}>
                  At least 12 characters.
                </p>
                <FormMessage />
              </FormItem>
            )}
          />
          <button
            type="submit"
            className="btn btn-primary"
            data-testid="button-signup-submit"
            disabled={isSubmitting}
            style={{ marginTop: 4 }}
          >
            {isSubmitting ? "Creating account…" : "Create account and continue"}
          </button>
        </form>
      </Form>
      <p style={{ marginTop: 24, textAlign: "center", fontSize: 13, color: "var(--color-neutral-700)" }}>
        Already have an account? <Link href="/login">Log in</Link>
      </p>
    </div>
  )
}
