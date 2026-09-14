import { describe, expect, it } from "vitest"
import { extractEmail, extractName } from "@/lib/cv-contact"

describe("extractEmail", () => {
  it("finds the first email and lowercases it", () => {
    expect(extractEmail("Jane Doe\nJane.Doe@Example.co.uk | 07123 456789")).toBe(
      "jane.doe@example.co.uk"
    )
  })

  it("returns an empty string when there is no email", () => {
    expect(extractEmail("Jane Doe\nLondon")).toBe("")
  })
})

describe("extractName", () => {
  it("takes the first line when it is a name, title-casing all caps", () => {
    expect(extractName("TOBILOBA ODU\nProduct Designer\n\nEarlier Career")).toBe(
      "Tobiloba Odu"
    )
  })

  it("skips a 'Curriculum Vitae' heading and markdown markers", () => {
    expect(extractName("# Curriculum Vitae\n\n## **Jane Doe**\njane@example.com")).toBe(
      "Jane Doe"
    )
  })

  it("strips a 'Name:' label", () => {
    expect(extractName("Name: Amaka Okafor-Bello\nEmail: a@b.com")).toBe("Amaka Okafor-Bello")
  })

  it("keeps a mixed-case name exactly as written", () => {
    expect(extractName("Seán McDonald\nEngineer")).toBe("Seán McDonald")
  })

  it("does not mistake a contact line or a single word for a name", () => {
    expect(extractName("Resume\njane@example.com | 07123 456789\nLondon, UK\nDesigner")).toBe("")
  })

  it("ignores names far down the CV, which are usually referees", () => {
    const filler = Array.from({ length: 10 }, (_, i) => `Line number ${i}`).join("\n")
    expect(extractName(`${filler}\nJohn Referee`)).toBe("")
  })
})
