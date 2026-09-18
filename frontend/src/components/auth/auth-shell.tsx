"use client"

import Image from "next/image"
import Link from "next/link"
import copyrightIcon from "@/assets/auth/icon-copyright.svg"
import { BrandMark } from "@/components/landing/brand-mark"
import { FOOTER_ABOUT, FOOTER_LINKS } from "@/components/landing/footer-links"
import { useAuthStore } from "@/store/auth-store"
import styles from "./auth.module.css"

// Page frame for the login journey: the wider pill nav with a LOGIN button
// (Figma "Nav" 8:32) and the short footer. Client-only for the auth check,
// same as the landing nav — signed-in visitors get "Dashboard" instead.
export function AuthShell({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((state) => state.user)

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.nav}>
          <Link href="/" className={styles.brand}>
            <BrandMark />
          </Link>
          <div className={styles.navRight}>
            <nav aria-label="Main" className={styles.navLinks}>
              <Link href="/#how" className={styles.navLink}>How it works</Link>
              <Link href="/#cv-fixer" className={styles.navLink}>CV fixer</Link>
              <Link href="/#pricing" className={styles.navLink}>Pricing</Link>
            </nav>
            <Link href="/dashboard/job-feed" className={`${styles.button} ${styles.findJob}`}>Find a job</Link>
            {user ? (
              <Link href="/dashboard" className={styles.button}>Dashboard</Link>
            ) : (
              <Link href="/login" className={styles.button}>Login</Link>
            )}
          </div>
        </div>
      </header>

      <main className={styles.main}>{children}</main>

      <footer className={styles.footer}>
        <p className={styles.footerAbout}>{FOOTER_ABOUT}</p>
        <div className={styles.footerBottom}>
          <span className={`${styles.overline} ${styles.copyright}`}>
            <span className={styles.copyrightIcon}>
              <Image src={copyrightIcon} alt="" width={14} height={12} unoptimized />
            </span>
            {new Date().getFullYear()} All rights reserved.
          </span>
          <ul className={styles.footerLinks}>
            {FOOTER_LINKS.map((link) => (
              <li key={link.label}>
                <a href={link.href} className={`${styles.overline} ${styles.footerLink}`}>
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </footer>
    </div>
  )
}
