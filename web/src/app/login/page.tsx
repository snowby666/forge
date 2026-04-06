"use client"

import { useState, type FormEvent } from "react"
import { useRouter } from "next/navigation"
import { CircuitBoard, LogIn } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export default function LoginPage() {
  const [token, setToken] = useState("")
  const router = useRouter()

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!token.trim()) return
    router.push(`/?token=${encodeURIComponent(token.trim())}`)
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <CircuitBoard className="size-5" />
          </div>
          <CardTitle className="text-xl">Forge</CardTitle>
          <CardDescription>
            Enter your access token to continue.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="grid gap-4">
            <Input
              type="password"
              placeholder="Access token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoFocus
            />
            <Button type="submit" className="w-full">
              <LogIn className="mr-2 size-4" />
              Sign in
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
