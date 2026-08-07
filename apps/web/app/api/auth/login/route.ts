import type { LoginRequest, TokenResponse } from "@fip/contracts";
import { NextResponse } from "next/server";

import { getApiUrl, isSecureSessionCookie, SESSION_COOKIE } from "@/lib/auth/constants";

const INVALID_CREDENTIALS = "Invalid account or password.";

export async function POST(request: Request) {
  let credentials: LoginRequest;

  try {
    const payload = (await request.json()) as Partial<LoginRequest>;
    if (typeof payload.username !== "string" || typeof payload.password !== "string") {
      return NextResponse.json({ detail: "Account and password are required." }, { status: 400 });
    }
    credentials = { username: payload.username.trim(), password: payload.password };
  } catch {
    return NextResponse.json({ detail: "Account and password are required." }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${getApiUrl()}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
      cache: "no-store",
    });

    if (!upstream.ok) {
      const isLocked = upstream.status === 423;
      const retryAfter = upstream.headers.get("Retry-After");
      const headers = retryAfter && /^\d+$/.test(retryAfter) ? { "Retry-After": retryAfter } : undefined;

      return NextResponse.json(
        {
          detail: isLocked
            ? "Entry temporarily paused. Try again later or use access support."
            : upstream.status === 401
              ? INVALID_CREDENTIALS
              : "Sign-in could not be completed.",
        },
        { status: upstream.status, headers },
      );
    }

    const token = (await upstream.json()) as TokenResponse;
    const response = NextResponse.json({ ok: true });
    response.cookies.set(SESSION_COOKIE, token.access_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: isSecureSessionCookie(),
      path: "/",
      maxAge: token.expires_in,
    });
    return response;
  } catch {
    return NextResponse.json(
      { detail: "The workspace is unavailable. Please try again shortly." },
      { status: 503 },
    );
  }
}
