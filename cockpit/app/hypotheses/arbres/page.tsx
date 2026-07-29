import type { Metadata } from "next";

import { HypothesisTreeExplorer } from "../../components/hypotheses/hypothesis-tree-explorer";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export const metadata: Metadata = {
  title: "Arbres d’hypothèses",
  description:
    "Développez les branches de l’univers Robin, inspectez leurs conditions et comparez leurs preuves.",
};

type TreeSearchParams = Record<
  string,
  string | string[] | undefined
>;

function firstSearchValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

function enabledSearchValue(value: string | string[] | undefined) {
  return ["1", "true", "oui"].includes(
    firstSearchValue(value).toLocaleLowerCase("fr-FR"),
  );
}

export default async function HypothesisTreesPage({
  searchParams,
}: {
  searchParams: Promise<TreeSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  return (
    <ExperienceShell active="hypotheses">
      <HypothesisTreeExplorer
        initialCutoff={firstSearchValue(resolvedSearchParams.cutoff)}
        initialDepth={firstSearchValue(
          resolvedSearchParams.profondeur ?? resolvedSearchParams.depth,
        )}
        initialFamily={firstSearchValue(
          resolvedSearchParams.famille ?? resolvedSearchParams.family,
        )}
        initialHideBlocked={enabledSearchValue(
          resolvedSearchParams["sans-bloquees"],
        )}
        initialLayout={firstSearchValue(
          resolvedSearchParams.vue ?? resolvedSearchParams.layout,
        )}
        initialMarket={firstSearchValue(
          resolvedSearchParams.marche ?? resolvedSearchParams.market,
        )}
        initialOnlyLongTail={enabledSearchValue(
          resolvedSearchParams["longue-traine"] ??
            resolvedSearchParams.longTail,
        )}
        initialQuery={firstSearchValue(resolvedSearchParams.q)}
        initialStatus={firstSearchValue(
          resolvedSearchParams.statut ??
            resolvedSearchParams.disposition ??
            resolvedSearchParams.status,
        )}
      />
    </ExperienceShell>
  );
}
