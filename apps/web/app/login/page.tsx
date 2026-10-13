import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";

import { SecureEntry, type SupportTopic } from "./secure-entry";

export const metadata: Metadata = {
  title: "FIP | Secure entry",
  description: "Secure entry to the Financial Integrity Platform",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ support?: string }>;
}) {
  if (await getCurrentUser()) {
    redirect("/workspace");
  }

  const { support } = await searchParams;
  const initialSupportTopic: SupportTopic | undefined =
    support === "access" ? "Role or access review" : undefined;

  return <SecureEntry initialSupportTopic={initialSupportTopic} />;
}
