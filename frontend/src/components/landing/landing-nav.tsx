"use client"

import Link from "next/link"
import { Search } from "lucide-react"
import { useAuthStore } from "@/store/auth-store"
import { BrandMark } from "./brand-mark"
import styles from "./landing.module.css"

// Client-only for the auth check: a signed-in visitor gets "Dashboard"
// where a new one gets "Log in". The Figma nav has neither — without one,
// a returning user has no way in from the home page.
export function LandingNav() {
  const user = useAuthStore((state) => state.user)

  return (
    <header className={styles.nav}>
      <Link href="/" className={styles.brand}>
        <BrandMark />
      </Link>
      <div className={styles.navRight}>
        <nav aria-label="Main" className={styles.navLinks}>
          <a href="#how" className={styles.navLink}>How it works</a>
          <a href="#cv-fixer" className={styles.navLink}>CV fixer</a>
          <a href="#pricing" className={styles.navLink}>Pricing</a>
        </nav>
        {user ? (
          <Link href="/dashboard" className={styles.navLink}>Dashboard</Link>
        ) : (
          <Link href="/login" className={styles.navLink}>Log in</Link>
        )}
        {/* Job feed sits behind auth: signed-out visitors are sent to
            /login by the dashboard guard, then land on /dashboard. */}
        <Link href="/dashboard/job-feed" className={styles.navCta} aria-label="Find a job">
          <Search width={15} height={15} strokeWidth={3} aria-hidden="true" />
          <span className={styles.navCtaLabel}>Find a job</span>
        </Link>
      </div>
    </header>
  )
}
