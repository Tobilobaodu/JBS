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

// The design's "watch video" play-circle, as drawn in its Figma export.
function PlayIcon() {
  return (
    <svg width={22} height={22} viewBox="-1.833 -1.833 22 22" aria-hidden="true">
      <path
        d="M 9.167 0 C 4.107 0 0 4.107 0 9.167 C 0 14.227 4.107 18.333 9.167 18.333 C 14.227 18.333 18.333 14.227 18.333 9.167 C 18.333 4.107 14.227 0 9.167 0 Z M 6.875 13.292 L 6.875 5.042 L 13.292 9.167 L 6.875 13.292 Z"
        fill="currentColor"
      />
    </svg>
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
            <PlayIcon />
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

// The design's footer links and social accounts. None of these pages or
// accounts exist yet — "#" is the design's own placeholder; swap in the real
// URLs here once they do.
const FOOTER_LINKS = [
  { href: "#", label: "About us" },
  { href: "#", label: "Privacy Policy" },
  { href: "#", label: "Terms and condition" },
  { href: "#", label: "FAQs" },
]

// Icon paths are the design's own (24×24 boxes, brand blue).
const SOCIAL_LINKS = [
  {
    href: "#",
    label: "LinkedIn",
    icon: (
      <svg width={24} height={24} viewBox="0 0 24 24" aria-hidden="true">
        <path d="M 19 3 C 20.105 3 21 3.895 21 5 L 21 19 C 21 20.105 20.105 21 19 21 L 5 21 C 3.895 21 3 20.105 3 19 L 3 5 C 3 3.895 3.895 3 5 3 L 19 3 Z M 18.5 18.5 L 18.5 13.2 C 18.5 11.4 17.04 9.94 15.24 9.94 C 14.39 9.94 13.4 10.46 12.92 11.24 L 12.92 10.13 L 10.13 10.13 L 10.13 18.5 L 12.92 18.5 L 12.92 13.57 C 12.92 12.8 13.54 12.17 14.31 12.17 C 15.08 12.17 15.71 12.8 15.71 13.57 L 15.71 18.5 L 18.5 18.5 Z M 6.88 8.56 C 7.81 8.56 8.56 7.81 8.56 6.88 C 8.56 5.95 7.81 5.19 6.88 5.19 C 5.95 5.19 5.19 5.95 5.19 6.88 C 5.19 7.81 5.95 8.56 6.88 8.56 Z M 8.27 18.5 L 8.27 10.13 L 5.5 10.13 L 5.5 18.5 L 8.27 18.5 Z" fill="currentColor" />
      </svg>
    ),
  },
  {
    href: "#",
    label: "X",
    icon: (
      <svg width={24} height={24} viewBox="-2.734 -3 24 24" aria-hidden="true">
        <path d="M 0.133 0 L 7.002 9.818 L 0 18 L 2.646 18 L 8.186 11.51 L 12.727 18 L 18.637 18 L 11.439 7.697 L 18.01 0 L 15.404 0 L 10.262 6.01 L 6.064 0 L 0.133 0 Z" fill="currentColor" />
      </svg>
    ),
  },
  {
    href: "#",
    label: "Facebook",
    icon: (
      <svg width={24} height={24} viewBox="-2 -2 24 24" aria-hidden="true">
        <path d="M 20 10 C 20 4.48 15.52 0 10 0 C 4.48 0 0 4.48 0 10 C 0 14.84 3.44 18.87 8 19.8 L 8 13 L 6 13 L 6 10 L 8 10 L 8 7.5 C 8 5.57 9.57 4 11.5 4 L 14 4 L 14 7 L 12 7 C 11.45 7 11 7.45 11 8 L 11 10 L 14 10 L 14 13 L 11 13 L 11 19.95 C 16.05 19.45 20 15.19 20 10 Z" fill="currentColor" />
      </svg>
    ),
  },
]

function LandingFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.footerTop}>
        <Link href="/" className={styles.brand}>
          <BrandMark />
        </Link>
        <ul className={styles.socials}>
          {SOCIAL_LINKS.map((social) => (
            <li key={social.label}>
              <a href={social.href} className={styles.social} aria-label={social.label}>
                {social.icon}
              </a>
            </li>
          ))}
        </ul>
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
              <a href={link.href} className={styles.footerLink}>{link.label}</a>
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
