"use client"

import { useState } from "react"
import Image from "next/image"
import type { UseFormRegisterReturn } from "react-hook-form"

import eyeIcon from "@/assets/auth/icon-eye.svg"
import warningIcon from "@/assets/auth/icon-warning.svg"
import styles from "./auth.module.css"

// The login journey's two input patterns (Figma "Input field" 8:3 and
// "Password" 8:10), shared by login, forgot-password and reset-password.

type FieldProps = {
  id: string
  label: string
  registration: UseFormRegisterReturn
  /** Red border (and the warning icon on email) without necessarily a message. */
  invalid?: boolean
  /** Shown under the input; may include a link. */
  message?: React.ReactNode
  autoComplete?: string
}

export function EmailField({ id, label, registration, invalid, message, autoComplete = "email" }: FieldProps) {
  const messageId = `${id}-error`
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label} <span className={styles.required} aria-hidden="true">*</span>
      </label>
      <div className={`${styles.inputBox} ${invalid ? styles.inputBoxError : ""}`}>
        <input
          id={id}
          type="email"
          autoComplete={autoComplete}
          placeholder="email@domain.com"
          required
          aria-invalid={Boolean(invalid)}
          aria-describedby={message ? messageId : undefined}
          className={styles.input}
          {...registration}
        />
        {invalid && message && (
          <span className={styles.inputIcon}>
            <Image src={warningIcon} alt="" width={23} height={23} unoptimized />
          </span>
        )}
      </div>
      {message && (
        <p id={messageId} className={styles.errorText}>{message}</p>
      )}
    </div>
  )
}

export function PasswordField({
  id,
  label,
  registration,
  invalid,
  message,
  autoComplete = "current-password",
  footer,
}: FieldProps & { footer?: React.ReactNode }) {
  const [visible, setVisible] = useState(false)
  const messageId = `${id}-error`
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label} <span className={styles.required} aria-hidden="true">*</span>
      </label>
      <div className={`${styles.inputBox} ${invalid ? styles.inputBoxError : ""}`}>
        <input
          id={id}
          type={visible ? "text" : "password"}
          autoComplete={autoComplete}
          placeholder="******"
          required
          aria-invalid={Boolean(invalid)}
          aria-describedby={message ? messageId : undefined}
          className={`${styles.input} ${styles.passwordInput}`}
          {...registration}
        />
        <button
          type="button"
          className={styles.inputIcon}
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
        >
          <Image src={eyeIcon} alt="" width={23} height={23} unoptimized />
        </button>
      </div>
      {message && (
        <p id={messageId} role="alert" className={styles.errorText}>{message}</p>
      )}
      {footer}
    </div>
  )
}
