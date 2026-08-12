import { redirect } from "next/navigation";

import { getBenchmarkRuns } from "@/lib/benchmarks/server";
import { getCurrentUser } from "@/lib/auth/server";
import { getCases } from "@/lib/cases/server";

import { WorkspaceShell } from "../../components/workspace-shell";
import { BenchmarkWorkspace } from "./workspace";

export default async function BenchmarkPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const [runs, cases] = await Promise.all([getBenchmarkRuns(), getCases()]);
  const activeCases = cases.filter((item) => item.status !== "classified");

  return (
    <WorkspaceShell
      activeNavigation="evaluation_benchmarks"
      eyebrow="Measured system evidence"
      reviewCount={activeCases.length}
      title="Synthetic benchmarks"
      user={user}
    >
      {runs ? (
        <BenchmarkWorkspace role={user.role} runs={runs} />
      ) : (
        <section className="benchmark-unavailable">
          <p className="eyebrow">Evidence service unavailable</p>
          <h2>The benchmark ledger could not be reached.</h2>
          <p>No run was created and no operational configuration changed.</p>
        </section>
      )}
    </WorkspaceShell>
  );
}
