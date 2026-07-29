import type { Metadata } from "next";

import { HypothesisTreeExplorer } from "../../../components/hypotheses/hypothesis-tree-explorer";
import { ExperienceShell } from "../../../components/navigation/experience-shell";

export const metadata: Metadata = {
  title: "Branche d’hypothèses",
};

export default async function HypothesisTreePage({
  params,
  searchParams,
}: {
  params: Promise<{ treeId: string }>;
  searchParams: Promise<{ q?: string }>;
}) {
  const { treeId } = await params;
  const { q = "" } = await searchParams;
  return (
    <ExperienceShell active="hypotheses">
      <HypothesisTreeExplorer
        initialQuery={q}
        initialTreeId={decodeURIComponent(treeId)}
      />
    </ExperienceShell>
  );
}
