import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";

export const metadata: Metadata = {
  title: "FIP | Plan an institutional integration",
  description: "Start an integration and governance review for the Financial Integrity Platform.",
};

const accessStages = [
  {
    index: "01",
    title: "Map the operating model",
    text: "Define the institution, investigation teams, risk programs, and outcomes FIP will support.",
  },
  {
    index: "02",
    title: "Design the integration",
    text: "Map approved data sources, alert flows, models, identity controls, and case-system handoffs.",
  },
  {
    index: "03",
    title: "Govern the rollout",
    text: "Agree on deployment boundaries, data handling, operating roles, validation gates, and human authority.",
  },
] as const;

export default async function RegisterPage() {
  if (await getCurrentUser()) {
    redirect("/workspace");
  }

  return (
    <main className="access-page">
      <header className="access-page-header">
        <Link aria-label="Return to FIP overview" className="landing-identity" href="/">
          <span>FIP</span>
          <strong>Financial Integrity Platform</strong>
        </Link>
        <Link className="access-page-login-link" href="/login">
          Already assigned? <strong>Sign in</strong>
        </Link>
      </header>

      <section className="access-request-layout">
        <div className="access-request-copy">
          <p className="landing-section-index">Institutional integration</p>
          <h1>Plan a governed FIP deployment for your organization.</h1>
          <p>
            FIP is introduced through an integration and governance review. Together, we map your
            investigation workflow, data environment, approved intelligence services, security
            controls, and the decisions that remain with your team.
          </p>
          <div className="access-request-actions">
            <Link className="landing-primary-action" href="/login?support=integration">
              Start integration review <span aria-hidden="true">→</span>
            </Link>
            <Link className="landing-secondary-action" href="/">Return to overview</Link>
          </div>
          <small>
            Your organization retains control of approved data, models, roles, and account
            activation throughout deployment.
          </small>
        </div>

        <div className="access-request-register">
          <header><span>INTEGRATION / REQUEST</span><strong>Planning sequence</strong></header>
          <ol>
            {accessStages.map((stage) => (
              <li key={stage.index}>
                <span>{stage.index}</span>
                <div><h2>{stage.title}</h2><p>{stage.text}</p></div>
              </li>
            ))}
          </ol>
          <footer>
            <span>Environment scoped</span>
            <span>Human approved</span>
            <span>Audit recorded</span>
          </footer>
        </div>
      </section>
    </main>
  );
}
