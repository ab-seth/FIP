import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

export async function proxyBenchmarkCreation(request: Request) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return authenticationRequired();
  return forward("/api/v1/evaluation/benchmarks", session, "POST", await request.text());
}

export async function proxyBenchmarkRetry(runId: string) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return authenticationRequired();
  return forward(
    `/api/v1/evaluation/benchmarks/${encodeURIComponent(runId)}/retry`,
    session,
    "POST",
    "{}",
  );
}

export async function proxyBenchmarkReport(runId: string) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return authenticationRequired();
  return forward(
    `/api/v1/evaluation/benchmarks/${encodeURIComponent(runId)}/report`,
    session,
    "GET",
  );
}

async function forward(
  endpoint: string,
  session: string,
  method: "GET" | "POST",
  body?: string,
) {
  try {
    const upstream = await fetch(`${getApiUrl()}${endpoint}`, {
      method,
      headers: {
        Authorization: `Bearer ${session}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body,
      cache: "no-store",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Disposition": upstream.headers.get("Content-Disposition") ?? "inline",
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "The benchmark service is temporarily unavailable." },
      { status: 503 },
    );
  }
}

function authenticationRequired() {
  return NextResponse.json({ detail: "Valid authentication is required" }, { status: 401 });
}
