export function Footer() {
  return (
    <footer className="border-t bg-background">
      <div className="mx-auto max-w-6xl px-4 py-8 text-sm text-muted-foreground">
        © {new Date().getFullYear()} CV Tailoring. All rights reserved.
      </div>
    </footer>
  )
}
