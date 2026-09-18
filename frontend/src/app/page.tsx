import type { Metadata } from "next"
import { LandingPage } from "@/components/landing/landing-page"

export const metadata: Metadata = {
  title: "Fix+Apply — Job search made easy",
  description:
    "AI-powered CV review, job matching and tailoring. Upload your CV and get evidence-backed fixes in seconds.",
}

export default function Home() {
  return <LandingPage />
}
