import Image, { type StaticImageData } from "next/image"
import Link from "next/link"
import { ArrowUp, Check, Copyright, X } from "lucide-react"

import heroDocument from "@/assets/landing/hero-document.webp"
import howUpload from "@/assets/landing/how-upload.webp"
import howMatch from "@/assets/landing/how-match.webp"
import howTrack from "@/assets/landing/how-track.webp"
import personOlivia from "@/assets/landing/person-olivia.webp"
import personAlex from "@/assets/landing/person-alex.webp"
import markAmazon from "@/assets/landing/mark-amazon.webp"
import markGoogle from "@/assets/landing/mark-google.webp"
import markFacebook from "@/assets/landing/mark-facebook.webp"
import logoNvidia from "@/assets/landing/logos/nvidia.svg"
import logoGoogle from "@/assets/landing/logos/google.svg"
import logoAmazon from "@/assets/landing/logos/amazon.svg"
import logoMeta from "@/assets/landing/logos/meta.svg"
import logoMicrosoft from "@/assets/landing/logos/microsoft.svg"
import logoIbm from "@/assets/landing/logos/ibm.svg"
import markIbm from "@/assets/landing/logos/ibm-mark.svg"
import markEbay from "@/assets/landing/logos/ebay-mark.svg"
import markMicrosoft from "@/assets/landing/logos/microsoft-mark.svg"
import markApple from "@/assets/landing/logos/apple-mark.svg"

import { BrandMark } from "./brand-mark"
import { LandingNav } from "./landing-nav"
import { Newsletter } from "./newsletter"
import { Pricing } from "./pricing"
import styles from "./landing.module.css"

// Width/height are always passed: under Vitest an image import is a plain
// URL string, and next/image needs explicit dimensions for those.
type Img = { src: StaticImageData | string; width: number; height: number; name: string }

const FEATURED: Img[] = [
  { src: logoNvidia, width: 126, height: 23, name: "NVIDIA" },
  { src: logoGoogle, width: 86, height: 28, name: "Google" },
  { src: logoAmazon, width: 95, height: 28, name: "Amazon" },
  { src: logoMeta, width: 99, height: 20, name: "Meta" },
  { src: logoAmazon, width: 95, height: 28, name: "Amazon" },
  { src: logoGoogle, width: 86, height: 28, name: "Google" },
  { src: logoMicrosoft, width: 128, height: 27, name: "Microsoft" },
  { src: logoNvidia, width: 126, height: 23, name: "NVIDIA" },
  { src: logoIbm, width: 55, height: 21, name: "IBM" },
]

type Mark = { src: StaticImageData | string; cover?: boolean }
const MARKS = {
  amazon: { src: markAmazon, cover: true },
  google: { src: markGoogle, cover: true },
  facebook: { src: markFacebook, cover: true },
  ibm: { src: markIbm },
  ebay: { src: markEbay },
  microsoft: { src: markMicrosoft },
} satisfies Record<string, Mark>

// Figma's card pile, back to front. Each transform is the export's own
// matrix (rotation + offset inside the 717×179 pile).
const JOB_CARDS: { company: string; title: string; mark: Mark; transform: string }[] = [
  { company: "IBM", title: "Senior Front-end Engineer", mark: MARKS.ibm, transform: "matrix(0.992,-0.128,0.128,0.992,0,91.884)" },
  { company: "Amazon", title: "Chief Data Analyst", mark: MARKS.amazon, transform: "matrix(0.997,0.078,-0.078,0.997,498.905,51.003)" },
  { company: "Ebay", title: "Marketing manager", mark: MARKS.ebay, transform: "matrix(0.985,-0.172,0.172,0.985,187.134,41.869)" },
  { company: "Amazon", title: "Senior Front-end Engineer", mark: MARKS.amazon, transform: "matrix(0.962,-0.272,0.272,0.962,234.949,103.057)" },
  { company: "Microsoft", title: "Senior Front-end Engineer", mark: MARKS.microsoft, transform: "matrix(0.965,0.262,-0.262,0.965,340.522,3.421)" },
  { company: "Google", title: "Content Engineer", mark: MARKS.google, transform: "matrix(1.000,-0.027,0.027,1.000,60.134,79.429)" },
  { company: "Facebook", title: "Front-end Engineer", mark: MARKS.facebook, transform: "matrix(0.990,0.141,-0.141,0.990,231.921,63.074)" },
  { company: "Amazon", title: "Senior Front-end Engineer", mark: MARKS.amazon, transform: "matrix(0.969,0.248,-0.248,0.969,449.335,62.464)" },
  { company: "Amazon", title: "Chief operating officer", mark: MARKS.amazon, transform: "matrix(0.985,-0.171,0.171,0.985,307,86.706)" },
]

const STEPS = [
  {
    icon: howUpload,
    title: "Upload your cv",
    body: "Get a free CV review in seconds, we’ll highlight strengths, you get tailored fixes + keyword optimization.",
  },
  {
    icon: howMatch,
    title: "Get matched",
    body: "See jobs that fit your skills, not just keywords, ranked by fit score. No more scrolling, just quality matches.",
  },
  {
    icon: howTrack,
    title: "Track & Succeed",
    body: "Sync your email for real-time updates, track applications and get insights on rejections/offers.",
  },
]

function MarqueeGroup({ hidden }: { hidden?: boolean }) {
  return (
    <div className={styles.marqueeGroup} aria-hidden={hidden || undefined}>
      {FEATURED.map((logo, i) => (
        <Image
          key={i}
          src={logo.src}
          width={logo.width}
          height={logo.height}
          alt={hidden ? "" : logo.name}
          unoptimized
        />
      ))}
    </div>
  )
}

function Hero() {
  return (
    <section className={styles.hero}>
      <div className={styles.heroDoc} aria-hidden="true">
        <Image src={heroDocument} alt="" width={586} height={755} priority />
      </div>

      <div className={styles.heroContent}>
        <div className={styles.heroText}>
          <h1 className={styles.heroTitle}>Job search made easy</h1>
          <p className={styles.heroSub}>
            AI-powered job matches for your skills, No more spraying and praying, get results.
          </p>
        </div>
        <div className={styles.heroActions}>
          {/* /try mints the anonymous trial session, then forwards to upload. */}
          <Link href="/try" className={styles.btnPrimary}>
            <ArrowUp width={18} height={18} strokeWidth={2.6} aria-hidden="true" />
            Upload CV
          </Link>
          {/* The design's "Watch video" has no video behind it yet. */}
          <a href="#how" className={styles.btnSoft}>
            See how it works
          </a>
        </div>
      </div>

      <div className={styles.featured}>
        <span className={styles.overline}>Featured companies</span>
        <div className={styles.marquee}>
          <div className={styles.marqueeTrack}>
            <MarqueeGroup />
            <MarqueeGroup hidden />
          </div>
        </div>
      </div>
    </section>
  )
}

function Profile({
  name,
  role,
  company,
  photo,
  brand,
}: {
  name: string
  role: string
  company: string
  photo: StaticImageData | string
  brand: React.ReactNode
}) {
  return (
    <div className={styles.profile}>
      <div className={styles.avatars}>
        <div className={styles.brandCircle}>
          <div className={styles.brandCircleInner}>{brand}</div>
        </div>
        <div className={styles.person}>
          <Image src={photo} alt="" width={88} height={88} />
        </div>
      </div>
      <div className={styles.profileText}>
        <span className={styles.profileName}>{name}</span>
        <span className={styles.profileRole}>{role}</span>
        <span className={styles.overline}>{company}</span>
      </div>
    </div>
  )
}

function MatchShowcase() {
  return (
    <section id="cv-fixer" className={styles.showcase} aria-labelledby="cv-fixer-title">
      <div className={styles.showcaseHead}>
        <h2 id="cv-fixer-title" className={styles.sectionTitle}>
          AI powered job search, filtering &amp; matching
        </h2>
        <p className={styles.sectionLead}>
          Precision matches, zero guesswork. We analyze your CV like a hiring manager would.
        </p>
      </div>

      {/* Illustration only: example people and roles, not real data. */}
      <div className={styles.matchRow} aria-hidden="true">
        <Profile
          name="Olivia Rivera"
          role="Product Manager"
          company="Facebook"
          photo={personOlivia}
          brand={<Image src={MARKS.facebook.src} alt="" width={88} height={88} />}
        />
        <div className={styles.matchLink}>
          <span className={styles.noMatch}>
            <X width={12} height={12} strokeWidth={3} />
          </span>
          <span className={styles.matchPill}>
            <span className={styles.matchPillIcon}>
              <Check width={12} height={12} strokeWidth={3} />
            </span>
            Match found!
          </span>
        </div>
        <Profile
          name="Alex Adesanya"
          role="Chief marketing officer"
          company="Apple"
          photo={personAlex}
          brand={<Image src={markApple} alt="" width={50} height={63} unoptimized />}
        />
      </div>

      <div className={styles.cardPile} aria-hidden="true">
        <div className={styles.cardPileInner}>
          {JOB_CARDS.map((card, i) => (
            <div key={i} className={styles.jobCard} style={{ transform: card.transform }}>
              <span className={styles.jobCardLogo}>
                <Image
                  src={card.mark.src}
                  alt=""
                  width={30}
                  height={30}
                  unoptimized={!card.mark.cover}
                  style={card.mark.cover ? undefined : { objectFit: "contain" }}
                />
              </span>
              <span className={styles.jobCardText}>
                <span className={styles.jobCardCompany}>{card.company}</span>
                <span className={styles.jobCardTitle}>{card.title}</span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function HowItWorks() {
  return (
    <section id="how" className={styles.how} aria-labelledby="how-title">
      <h2 id="how-title" className={styles.sectionTitle}>How it works</h2>
      <p className={styles.sectionLead}>
        Your dream job, simplified.
        <br />
        AI does the heavy lifting, you get the offers.
      </p>
      <ol className={styles.steps}>
        {STEPS.map((step, i) => (
          <li key={step.title} className={styles.step}>
            <Image src={step.icon} alt="" width={94} height={125} />
            <div className={styles.stepText}>
              <span className={styles.stepNumber} aria-hidden="true">{i + 1}</span>
              <h3 className={styles.stepTitle}>{step.title}</h3>
              <p className={styles.stepBody}>{step.body}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

const FOOTER_LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#pricing", label: "Pricing" },
  { href: "/try", label: "Try it free" },
  { href: "/login", label: "Log in" },
]

function LandingFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.footerTop}>
        <Link href="/" className={styles.brand}>
          <BrandMark />
        </Link>
      </div>
      <p className={styles.footerAbout}>
        Fix+Apply reviews your CV, matches it against real job posts and tailors it for each
        application. Every suggestion is traced back to something already in your CV — we
        never invent experience you don’t have.
      </p>
      <div className={styles.footerBottom}>
        <span className={styles.copyright}>
          <Copyright width={16} height={16} aria-hidden="true" />
          {new Date().getFullYear()} All rights reserved.
        </span>
        <ul className={styles.footerLinks}>
          {FOOTER_LINKS.map((link) => (
            <li key={link.label}>
              <Link href={link.href} className={styles.footerLink}>{link.label}</Link>
            </li>
          ))}
        </ul>
      </div>
    </footer>
  )
}

export function LandingPage() {
  return (
    <div className={styles.page}>
      <LandingNav />
      <main>
        <Hero />
        <MatchShowcase />
        <HowItWorks />
        <Pricing />
        <Newsletter />
      </main>
      <LandingFooter />
    </div>
  )
}
