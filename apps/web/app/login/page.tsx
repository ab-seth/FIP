import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";

import { SecureEntry } from "./secure-entry";

export const metadata: Metadata = {
  title: "FIP | Secure entry",
  description: "Secure entry to the Financial Integrity Platform",
};

export default async function LoginPage() {
  if (await getCurrentUser()) {
    redirect("/");
  }

  return <SecureEntry />;
}
