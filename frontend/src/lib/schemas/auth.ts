import { z } from "zod"

// Mirrors backend app/schemas/auth.py: RegisterRequest.password min_length=12.
// This MUST match the backend. It previously said 8 while the backend
// required 12, so a 8-11 character password passed client validation and
// then failed server-side with a 422 the register page did not surface —
// the account was silently never created.
export const registerSchema = z
  .object({
    email: z.string().email("Enter a valid email address."),
    password: z.string().min(12, "Password must be at least 12 characters."),
    confirmPassword: z.string(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  })

export type RegisterFormValues = z.infer<typeof registerSchema>

// /try/signup: name and email arrive pre-filled from the CV, and there is a
// single password field with a show/hide toggle instead of a confirm field.
// Limits mirror RegisterRequest (password min 12, fullName max 200).
export const trialSignupSchema = z.object({
  fullName: z
    .string()
    .trim()
    .min(1, "Enter your name.")
    .max(200, "Name must be 200 characters or fewer."),
  email: z.string().trim().email("Enter a valid email address."),
  password: z.string().min(12, "Password must be at least 12 characters."),
})

export type TrialSignupFormValues = z.infer<typeof trialSignupSchema>

export const loginSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(1, "Password is required."),
})

export type LoginFormValues = z.infer<typeof loginSchema>
