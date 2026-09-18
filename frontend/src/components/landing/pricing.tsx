"use client"

import { useState } from "react"
import Link from "next/link"
import { Check } from "lucide-react"
import styles from "./landing.module.css"

// Annual price = 12 months less this discount (the Figma prototype's default).
const ANNUAL_DISCOUNT = 0.2

type Plan = {
  name: string
  description: string
  monthly: number
  cta: string
  includes?: string
  features: string[]
  featured?: boolean
}

// Plan names, prices and feature copy are the Figma design's. There is no
// billing in the app yet, so every button goes to free sign-up.
const PLANS: Plan[] = [
  {
    name: "Free Forever",
    description: "Start your job search smarter - AI tools to begin your career upgrade",
    monthly: 0,
    cta: "Get started",
    features: [
      "Full CV Analysis - Get detailed feedback on strengths/weaknesses",
      "5 Monthly Job Matches - Curated roles matching your exact profile",
      "Application Tracker - See where you’ve applied in one dashboard",
      "3 CV Template Options - Professionally designed formats",
    ],
  },
  {
    name: "Pro Plan",
    description: "For serious job seekers - Everything you need to land interviews faster",
    monthly: 29,
    cta: "Get this plan",
    includes: "Everything in the free plan, and",
    featured: true,
    features: [
      "Unlimited AI Job Matches - No restrictions on opportunities",
      "Advanced CV Optimization - Live editing suggestions as you work",
      "Full Email Integration - Auto-logging all application responses",
      "20+ Premium CV Templates - Stand out from other candidates",
    ],
  },
  {
    name: "Premium Plan",
    description: "Executive-level job hunting - White-glove service for career advancement",
    monthly: 90,
    cta: "Get this plan",
    includes: "Everything in the pro plan, and",
    // Same four lines as Pro in the Figma file — needs real Premium copy.
    features: [
      "Unlimited AI Job Matches - No restrictions on opportunities",
      "Advanced CV Optimization - Live editing suggestions as you work",
      "Full Email Integration - Auto-logging all application responses",
      "20+ Premium CV Templates - Stand out from other candidates",
    ],
  },
]

function price(monthly: number, annual: boolean): string {
  const amount = annual ? Math.round(monthly * 12 * (1 - ANNUAL_DISCOUNT)) : monthly
  return `£${amount}`
}

export function Pricing() {
  const [annual, setAnnual] = useState(false)

  return (
    <section id="pricing" className={styles.pricing} aria-labelledby="pricing-title">
      <div className={styles.pricingHead}>
        <h2 id="pricing-title" className={styles.sectionTitle}>Find the right plan for you</h2>
        <p className={styles.sectionLead}>
          Start free. Upgrade when you want unlimited matches and more templates.
        </p>
        <div className={styles.billingToggle}>
          <button
            type="button"
            className={`${styles.billingLabel} ${annual ? "" : styles.billingLabelActive}`}
            onClick={() => setAnnual(false)}
          >
            Monthly
          </button>
          <button
            type="button"
            role="switch"
            aria-checked={annual}
            aria-label="Annual billing"
            className={styles.switch}
            onClick={() => setAnnual((a) => !a)}
          >
            <span className={styles.switchKnob} />
          </button>
          <button
            type="button"
            className={`${styles.billingLabel} ${annual ? styles.billingLabelActive : ""}`}
            onClick={() => setAnnual(true)}
          >
            Annual
          </button>
        </div>
      </div>

      <div className={styles.plans}>
        {PLANS.map((plan) => (
          <article
            key={plan.name}
            className={`${styles.plan} ${plan.featured ? styles.planFeatured : ""}`}
          >
            <div className={styles.planHead}>
              {plan.featured && <span className={styles.planBadge}>Recommended</span>}
              <h3 className={styles.planName}>{plan.name}</h3>
              <p className={styles.planDesc}>{plan.description}</p>
              <p className={styles.planPrice} data-testid={`price-${plan.monthly}`}>
                {price(plan.monthly, annual)}
              </p>
              <p className={styles.planBilled}>{annual ? "Billed annually" : "Billed monthly"}</p>
            </div>
            <Link href="/register" className={styles.planCta}>
              {plan.cta}
            </Link>
            {plan.includes && <p className={styles.planIncludes}>{plan.includes}</p>}
            <ul className={styles.features}>
              {plan.features.map((feature) => (
                <li key={feature} className={styles.feature}>
                  <Check width={24} height={24} strokeWidth={2.4} aria-hidden="true" />
                  {feature}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  )
}
