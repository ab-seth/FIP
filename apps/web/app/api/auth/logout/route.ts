import { NextResponse } from "next/server";

import { isSecureSessionCookie, SESSION_COOKIE } from "@/lib/auth/constants";

export function POST() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: isSecureSessionCookie(),
    path: "/",
    maxAge: 0,
  });
  return response;
}
