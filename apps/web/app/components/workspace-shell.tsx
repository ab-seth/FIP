import type { UserResponse } from "@fip/contracts";
import Link from "next/link";
import type { ReactNode } from "react";

import { AccountMenu } from "./account-menu";
import { DateStamp } from "./date-stamp";

type NavigationKey =
  | "case_register"
  | "case_dossiers"
  | "audit_ledger"
  | "ml_datasets"
  | "evaluation_record";

const navigation: Array<{
  key: NavigationKey;
  label: string;
  marker: string;
  href: string;
}> = [
  { key: "case_register", label: "Case register", marker: "01", href: "/" },
  { key: "case_dossiers", label: "Case dossiers", marker: "02", href: "/cases" },
  {
    key: "audit_ledger",
    label: "Audit ledger",
    marker: "03",
    href: "/evaluation#integrity-ledger",
  },
  { key: "ml_datasets", label: "ML datasets", marker: "04", href: "/ml/datasets" },
  { key: "evaluation_record", label: "Evaluation record", marker: "05", href: "/evaluation" },
];

export function WorkspaceShell({
  activeNavigation,
  children,
  eyebrow,
  reviewCount,
  title,
  user,
}: {
  activeNavigation: NavigationKey;
  children: ReactNode;
  eyebrow: string;
  reviewCount: number;
  title: string;
  user: UserResponse;
}) {
  return (
    <div className="app-frame">
      <aside className="sidebar">
        <Link aria-label="FIP case register" className="identity" href="/">
          <span className="monogram">FIP</span>
          <span className="identity-name">Financial Integrity Platform</span>
        </Link>

        <nav aria-label="Primary navigation" className="primary-navigation">
          <p className="navigation-label">Workspace</p>
          <ol>
            {navigation.map((item) => (
              <li key={item.key}>
                <Link
                  aria-current={item.key === activeNavigation ? "page" : undefined}
                  href={item.href}
                >
                  <span className="navigation-marker">{item.marker}</span>
                  <span>{item.label}</span>
                </Link>
              </li>
            ))}
          </ol>
        </nav>

        <div className="sidebar-foot">
          <span className="availability-dot" />
          <span>Systems available</span>
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
          </div>
          <div className="header-context">
            <DateStamp />
            <span
              aria-label={`${reviewCount} ${reviewCount === 1 ? "case" : "cases"} awaiting review`}
              className="review-count"
            >
              <strong>{reviewCount}</strong> awaiting review
            </span>
            <AccountMenu
              initials={accountInitials(user.username)}
              role={roleLabel(user.role)}
              username={user.username}
            />
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

function accountInitials(username: string) {
  const parts = username.split(/[._\-\s]+/).filter(Boolean);
  if (parts.length > 1) {
    return parts
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase();
  }
  return username.slice(0, 2).toUpperCase();
}

function roleLabel(role: string) {
  return role.charAt(0).toUpperCase() + role.slice(1);
}
