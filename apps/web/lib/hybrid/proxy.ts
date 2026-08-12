import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

export async function proxyHybridMutation(request: Request, transactionId: string) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) {
    return NextResponse.json({ detail: "Valid authentication is required" }, { status: 401 });
  }

  let body: string;
  try {
    body = await request.text();
  } catch {
    return NextResponse.json(
      { detail: "The hybrid evidence request could not be read." },
      { status: 400 },
    );
  }

  try {
    const upstream = await fetch(
      `${getApiUrl()}/api/v1/transactions/${encodeURIComponent(transactionId)}/hybrid-assessments`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session}`,
          "Content-Type": "application/json",
        },
        body,
        cache: "no-store",
      },
    );
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "The hybrid evidence service is temporarily unavailable." },
      { status: 503 },
    );
  }
}
