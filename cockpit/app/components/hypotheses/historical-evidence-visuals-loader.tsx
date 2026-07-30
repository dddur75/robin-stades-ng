"use client";

import {
  lazy,
  Suspense,
  useEffect,
  useState,
} from "react";

import type { HypothesisEvidenceAnalysisViewModels } from "../../lib/hypothesis-evidence-analysis-view-model";
import type { HistoricalHypothesisEvidence } from "../../lib/hypothesis-evidence.server";

const LazyHistoricalEvidenceVisuals = lazy(async () => {
  const visualsModule = await import("./historical-evidence-visuals");
  return { default: visualsModule.HistoricalEvidenceVisuals };
});

type LoadState =
  | Readonly<{ status: "loading" }>
  | Readonly<{ status: "ready"; visuals: HypothesisEvidenceAnalysisViewModels }>
  | Readonly<{ status: "unavailable" }>;

function LoadingState() {
  return (
    <section
      aria-busy="true"
      aria-live="polite"
      className="hu-section hu-surface hu-analysis-load-state"
    >
      <p className="hu-kicker">Détails bornés</p>
      <h2>Chargement des ventilations historiques…</h2>
      <p>
        La fiche agrégée reste légère ; les séries détaillées sont demandées
        uniquement dans les vues d’analyse.
      </p>
    </section>
  );
}

function UnavailableState({ onRetry }: { onRetry: () => void }) {
  return (
    <section
      aria-live="polite"
      className="hu-section hu-surface hu-analysis-load-state"
      role="status"
    >
      <p className="hu-kicker">Détails bornés</p>
      <h2>Ventilations historiques indisponibles</h2>
      <p>
        Robin conserve les totaux réconciliés ci-dessus, sans reconstruire ni
        inventer les séries manquantes.
      </p>
      <button className="secondary-link" onClick={onRetry} type="button">
        Réessayer le chargement
      </button>
    </section>
  );
}

export function HistoricalEvidenceVisualsLoader({
  evidence,
}: {
  evidence: HistoricalHypothesisEvidence;
}) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    void Promise.all([
      import("../../lib/hypothesis-evidence-assets"),
      import("../../lib/hypothesis-evidence-analysis-view-model"),
    ])
      .then(([assets, mapper]) =>
        assets.loadHypothesisEvidenceAnalysis(evidence.hypothesisId, {
          signal: controller.signal,
        }).then((analysis) =>
          mapper.mapHypothesisEvidenceAnalysisToViewModels(analysis, {
            hypothesisId: evidence.hypothesisId,
          }),
        ),
      )
      .then((visuals) => {
        if (!controller.signal.aborted) {
          setState({ status: "ready", visuals });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [attempt, evidence.hypothesisId]);

  if (state.status === "loading") return <LoadingState />;
  if (state.status === "unavailable") {
    return (
      <UnavailableState
        onRetry={() => {
          setState({ status: "loading" });
          setAttempt((value) => value + 1);
        }}
      />
    );
  }
  return (
    <Suspense fallback={<LoadingState />}>
      <LazyHistoricalEvidenceVisuals visuals={state.visuals} />
    </Suspense>
  );
}
