"use client"

import { useState, type FormEvent } from "react"
import Image from "next/image"
import { useRouter } from "next/navigation"
import { ArrowRight } from "lucide-react"
import envelope from "@/assets/landing/newsletter.webp"
import styles from "./landing.module.css"

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/

// There is no mailing-list backend yet, so this can't really subscribe
// anyone. Rather than fake a "Subscribed" state, it hands the address to
// sign-up (prefilled); the job feed there is the closest thing to it.
export function Newsletter() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const valid = EMAIL_RE.test(email.trim())

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!valid) return
    router.push(`/register?email=${encodeURIComponent(email.trim())}`)
  }

  return (
    <section className={styles.signup} aria-labelledby="signup-title">
      <div className={styles.signupHead}>
        <Image src={envelope} alt="" width={116} height={92} />
        <h2 id="signup-title" className={styles.sectionTitle}>
          Get curated jobs weekly, No spam, just opportunities.
        </h2>
        <p className={styles.sectionLead}>Weekly handpicked matches + CV tips. Unsubscribe anytime.</p>
      </div>
      <form className={styles.signupForm} onSubmit={onSubmit} noValidate>
        <div className={styles.signupField}>
          <input
            type="email"
            autoComplete="email"
            aria-label="Email address"
            placeholder="Enter your email address"
            className={styles.signupInput}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <button type="submit" className={styles.signupSubmit} disabled={!valid}>
            Send me jobs
            <ArrowRight width={22} height={22} strokeWidth={2.2} aria-hidden="true" />
          </button>
        </div>
        <p className={styles.signupNote}>
          Next, you’ll create a free account to see your matches.
        </p>
      </form>
    </section>
  )
}
