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
import { loginSchema, type LoginFormValues } from "@/lib/schemas/auth"
import { loginAccount } from "@/lib/auth-api"
import { ApiError, errorMessage } from "@/lib/api"
import { useAuthStore } from "@/store/auth-store"
import { usePostAuthRedirect } from "@/hooks/use-post-auth-redirect"

export default function LoginPage() {
  const redirectAfterAuth = usePostAuthRedirect()
  const setAuth = useAuthStore((state) => state.setAuth)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  })

  async function onSubmit(values: LoginFormValues) {
    setIsSubmitting(true)
    try {
      const result = await loginAccount(values.email, values.password)
      setAuth(result.accessToken, {
        id: result.user.id,
        email: result.user.email,
      })
      await redirectAfterAuth()
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) {
        toast.error(errorMessage(error, "Too many attempts. Please wait and try again."))
      } else {
        toast.error(errorMessage(error, "Invalid email or password."))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col justify-center px-4 py-24">
      <Card>
        <CardHeader>
          <CardTitle>Log in</CardTitle>
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
                        autoComplete="current-password"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button type="submit" disabled={isSubmitting} className="mt-2">
                {isSubmitting ? "Logging in…" : "Log in"}
              </Button>
            </form>
          </Form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            Don&apos;t have an account?{" "}
            <Link href="/register" className="underline">
              Create one
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
