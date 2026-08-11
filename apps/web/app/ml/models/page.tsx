import type {
  ModelArtifactStatus,
  RegisteredModel,
  ShadowEvaluationReport,
} from "@fip/contracts";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";
import { getCases } from "@/lib/cases/server";
import {
  getModelArtifactStatus,
  getModelEvaluations,
  getRegisteredModels,
} from "@/lib/models/server";

import { WorkspaceShell } from "../../components/workspace-shell";
import { ModelOperations } from "./model-operations";

export interface ModelOperationsRecord {
  model: RegisteredModel;
  artifact: ModelArtifactStatus | null;
  evaluations: ShadowEvaluationReport[];
}

export default async function ModelOperationsPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const [models, cases] = await Promise.all([getRegisteredModels(), getCases()]);
  const activeCases = cases.filter((item) => item.status !== "classified");
  const records: ModelOperationsRecord[] | null = models
    ? await Promise.all(
        models.map(async (model) => ({
          model,
          artifact: await getModelArtifactStatus(model.id),
          evaluations: await getModelEvaluations(model.id),
        })),
      )
    : null;

  return (
    <WorkspaceShell
      activeNavigation="ml_models"
      eyebrow="Model governance"
      reviewCount={activeCases.length}
      title="Model operations"
      user={user}
    >
      {records ? (
        <ModelOperations records={records} role={user.role} />
      ) : (
        <section className="model-ops-unavailable">
          <p className="eyebrow">Registry unavailable</p>
          <h2>The model control plane could not be reached.</h2>
          <p>Rules-based scoring remains available and no model state was changed.</p>
        </section>
      )}
    </WorkspaceShell>
  );
}
