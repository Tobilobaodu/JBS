/** Best-guess name and email from extracted CV text, used only to pre-fill
 *  the trial sign-up form — the user sees both, editable, before anything
 *  is submitted. Deliberately simple pattern-matching rather than an LLM
 *  call: instant, free, and a wrong guess costs one edit. Returns "" when
 *  nothing plausible is found, so the field is left blank rather than
 *  filled with a heading. */

const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/

// Lines that open many CVs but are never the candidate's name.
const HEADING_RE =
  /^(curriculum vitae|resume|résumé|cv|profile|personal (details|information|profile)|contact( details| information)?|summary|professional summary|about me)$/i

// Only the top of a CV is searched: a name further down is almost always a
// referee or a manager, not the candidate.
const NAME_SEARCH_LINES = 8

export function extractEmail(text: string): string {
  const match = text.match(EMAIL_RE)
  return match ? match[0].toLowerCase() : ""
}

export function extractName(text: string): string {
  const lines = text.split(/\r?\n/).slice(0, NAME_SEARCH_LINES * 3)
  let seen = 0
  for (const rawLine of lines) {
    const line = cleanLine(rawLine)
    if (!line) continue
    if (++seen > NAME_SEARCH_LINES) break
    if (looksLikeName(line)) return toDisplayCase(line)
  }
  return ""
}

function cleanLine(line: string): string {
  return line
    .replace(/^[#>*\-\s]+/, "") // markdown heading/bullet/quote markers
    .replace(/[*_`]+/g, "") // markdown emphasis
    .replace(/^name\s*[:\-]\s*/i, "")
    .replace(/\s+/g, " ")
    .trim()
}

function looksLikeName(line: string): boolean {
  if (line.length > 60 || HEADING_RE.test(line)) return false
  if (/[@\d|/\\:,;()]/.test(line)) return false
  const words = line.split(" ")
  if (words.length < 2 || words.length > 4) return false
  // Letters (any script), plus the apostrophes, hyphens and dots names use.
  return words.every((word) => /^\p{L}[\p{L}'’.\-]*$/u.test(word))
}

/** "JANE DOE" and "jane doe" become "Jane Doe"; a name already in mixed
 *  case ("Jane McDonald", "Oluwaseun de Souza") is left exactly as written. */
function toDisplayCase(name: string): string {
  const isMixedCase = name !== name.toUpperCase() && name !== name.toLowerCase()
  if (isMixedCase) return name
  return name
    .toLowerCase()
    .replace(/(^|[\s'’\-])(\p{L})/gu, (_, sep: string, ch: string) => sep + ch.toUpperCase())
}
