import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";
import { getCases } from "@/lib/cases/server";
import { getResearchModelEvidence } from "@/lib/research/server";

import { WorkspaceShell } from "../../components/workspace-shell";
import { ResearchEvidenceWorkspace } from "./research-evidence-workspace";

export default async function ResearchEvidencePage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const [evidence, cases] = await Promise.all([getResearchModelEvidence(), getCases()]);
  const activeCases = cases.filter((item) => item.status !== "classified");

  return (
    <WorkspaceShell
      activeNavigation="ml_research"
      eyebrow="Applied ML research"
      reviewCount={activeCases.length}
      title="Research evidence"
      user={user}
    >
      {evidence ? (
        <ResearchEvidenceWorkspace evidence={evidence} />
      ) : (
        <section className="research-unavailable">
          <p className="eyebrow">Evidence unavailable</p>
          <h2>The sealed research record could not be reached.</h2>
          <p>Operational scoring remains rules-based and no system state was changed.</p>
        </section>
      )}
    </WorkspaceShell>
  );
}
