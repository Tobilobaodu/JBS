import Link from "next/link"
import { Button } from "@/components/ui/button"

export default function LandingPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-24 text-center">
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        Evidence-backed CV tailoring and cover letters
      </h1>
      <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
        Upload your CV, paste a job link, and let our engine tailor your
        application in minutes.
      </p>
      <div className="mt-8 flex items-center justify-center gap-3">
        <Button size="lg" asChild>
          <Link href="/try">Try it free — no credit card</Link>
        </Button>
        <Button size="lg" variant="outline" asChild>
          <Link href="/login">Log in</Link>
        </Button>
      </div>
    </div>
  )
}
