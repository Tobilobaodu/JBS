"use client"

import { useState } from "react"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { registerSchema, type RegisterFormValues } from "@/lib/schemas/auth"
import { registerAccount, loginAccount } from "@/lib/auth-api"
import { ApiError, errorMessage } from "@/lib/api"
import { useAuthStore } from "@/store/auth-store"
import { usePostAuthRedirect } from "@/hooks/use-post-auth-redirect"

export default function RegisterPage() {
  const redirectAfterAuth = usePostAuthRedirect()
  const setAuth = useAuthStore((state) => state.setAuth)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const form = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: "", password: "", confirmPassword: "" },
  })

  async function onSubmit(values: RegisterFormValues) {
    setIsSubmitting(true)
    try {
      await registerAccount(values.email, values.password)
      // Registration does not return a token (app/api/v1/auth.py::register
      // returns 201 UserResponse only) — log in immediately after.
      const loginResult = await loginAccount(values.email, values.password)
      setAuth(loginResult.accessToken, {
        id: loginResult.user.id,
        email: loginResult.user.email,
      })
      await redirectAfterAuth()
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        toast.error(errorMessage(error, "An account with this email already exists."))
      } else if (error instanceof ApiError && error.status === 429) {
        toast.error(errorMessage(error, "Too many attempts. Please wait and try again."))
      } else {
        toast.error(errorMessage(error, "Could not create your account."))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col justify-center px-4 py-24">
      <Card>
        <CardHeader>
          <CardTitle>Create your account</CardTitle>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(onSubmit)}
              className="flex flex-col gap-4"
              noValidate
            >
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input type="email" autoComplete="email" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Password</FormLabel>
                    <FormControl>
                      <Input
                        type="password"
                        autoComplete="new-password"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="confirmPassword"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Confirm password</FormLabel>
                    <FormControl>
                      <Input
                        type="password"
                        autoComplete="new-password"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button type="submit" disabled={isSubmitting} className="mt-2">
                {isSubmitting ? "Creating account…" : "Create account"}
              </Button>
            </form>
          </Form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="underline">
              Log in
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
