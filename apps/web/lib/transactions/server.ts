import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export async function proxyCsvUpload(request: Request, endpoint: string) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) {
    return NextResponse.json({ detail: "Valid authentication is required" }, { status: 401 });
  }

  const contentLength = request.headers.get("content-length");
  if (contentLength && /^\d+$/.test(contentLength) && Number(contentLength) > MAX_UPLOAD_BYTES) {
    return uploadTooLarge();
  }

  let content: ArrayBuffer;
  try {
    content = await request.arrayBuffer();
  } catch {
    return NextResponse.json({ detail: "The transaction file could not be read." }, { status: 400 });
  }
  if (content.byteLength > MAX_UPLOAD_BYTES) {
    return uploadTooLarge();
  }

  const filename = safeFilename(request.headers.get("X-FIP-Filename"));

  try {
    const upstream = await fetch(`${getApiUrl()}${endpoint}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${session}`,
        "Content-Type": "text/csv",
        "X-FIP-Filename": filename,
      },
      body: content,
      cache: "no-store",
    });
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "Transaction intake is temporarily unavailable." },
      { status: 503 },
    );
  }
}

function safeFilename(value: string | null) {
  const withoutPath = (value ?? "transactions.csv").replaceAll("\\", "/").split("/").at(-1);
  const withoutControls = (withoutPath ?? "transactions.csv").replace(/[\u0000-\u001F\u007F]/g, "");
  return withoutControls.slice(0, 255) || "transactions.csv";
}

function uploadTooLarge() {
  return NextResponse.json({ detail: "The CSV file cannot exceed 10 MB." }, { status: 413 });
}
