import type { Metadata } from "next"
import { Geist, JetBrains_Mono } from "next/font/google"
import { Toaster } from "sonner"
import "./globals.css"

import { TooltipProvider } from "@/components/ui/tooltip"

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
})

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
})

export const metadata: Metadata = {
  title: "Forge Dashboard",
  description: "Hackathon automation command center",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      className={`dark ${geistSans.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <TooltipProvider>{children}</TooltipProvider>
        <Toaster theme="dark" richColors position="bottom-right" />
      </body>
    </html>
  )
}
