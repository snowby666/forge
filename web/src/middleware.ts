import { NextRequest, NextResponse } from "next/server"

const PUBLIC_PATHS = ["/login", "/health", "/healthz", "/favicon.ico"]

function isPublic(pathname: string) {
  if (PUBLIC_PATHS.includes(pathname)) return true
  if (pathname.startsWith("/api/")) return true
  if (pathname.startsWith("/_next/")) return true
  return false
}

export function middleware(request: NextRequest) {
  const { pathname, searchParams } = request.nextUrl
  const expectedToken = process.env.FORGE_WEB_TOKEN

  if (!expectedToken || isPublic(pathname)) {
    return NextResponse.next()
  }

  const queryToken = searchParams.get("token")

  if (queryToken === expectedToken) {
    const url = request.nextUrl.clone()
    url.searchParams.delete("token")
    const response = NextResponse.redirect(url)
    response.cookies.set("forge_token", queryToken, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 30,
    })
    return response
  }

  const cookieToken = request.cookies.get("forge_token")?.value

  if (cookieToken === expectedToken) {
    return NextResponse.next()
  }

  const loginUrl = request.nextUrl.clone()
  loginUrl.pathname = "/login"
  loginUrl.search = ""
  return NextResponse.redirect(loginUrl)
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon\\.ico).*)"],
}
