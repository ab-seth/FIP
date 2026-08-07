"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

interface AccountMenuProps {
  initials: string;
  role: string;
  username: string;
}

export function AccountMenu({ initials, role, username }: AccountMenuProps) {
  const router = useRouter();
  const [isLeaving, setIsLeaving] = useState(false);

  async function signOut() {
    setIsLeaving(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <details className="account-menu">
      <summary aria-label="Open account menu" className="account-button">
        {initials}
      </summary>
      <div className="account-popover">
        <p className="account-name">{username}</p>
        <p className="account-role">{role}</p>
        <button disabled={isLeaving} onClick={signOut} type="button">
          {isLeaving ? "Signing out…" : "Sign out"}
        </button>
      </div>
    </details>
  );
}
