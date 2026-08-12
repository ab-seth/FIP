import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";
import { getCases } from "@/lib/cases/server";
import { getOperationalDatasets } from "@/lib/ml-datasets/server";
import { getOperationalTrainingRuns } from "@/lib/training-runs/server";

import { WorkspaceShell } from "../../components/workspace-shell";
import { TrainingOperations } from "./training-operations";

export default async function TrainingOperationsPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const [runs, datasets, cases] = await Promise.all([
    getOperationalTrainingRuns(),
    getOperationalDatasets(),
    getCases(),
  ]);
  const activeCases = cases.filter((item) => item.status !== "classified");

  return (
    <WorkspaceShell
      activeNavigation="ml_training"
      eyebrow="Candidate evidence"
      reviewCount={activeCases.length}
      title="Training operations"
      user={user}
    >
      {runs ? (
        <TrainingOperations datasets={datasets} role={user.role} runs={runs} />
      ) : (
        <section className="training-unavailable">
          <p className="eyebrow">Control plane unavailable</p>
          <h2>The training-run ledger could not be reached.</h2>
          <p>No training request was created and deterministic scoring remains unchanged.</p>
        </section>
      )}
    </WorkspaceShell>
  );
}
