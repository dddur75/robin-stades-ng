"use client";

import Link from "next/link";
import {
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  formatDateTime,
  formatNumber,
  formatPercent,
  formatUnits,
} from "../../i18n";
import {
  compactNodeId,
  familyDisplayName,
  hypothesisById,
  hypothesisChildrenByParent,
  hypothesisIntelligence,
  hypothesisNodeLocator,
  hypothesisNodePages,
  prospectiveContractByHypothesisId,
  scientificStatusLabel,
  subfamilyDisplayName,
  type HypothesisTreeNode,
} from "../../lib/hypothesis-universe";
import { useViewMode } from "../common/view-mode";
import {
  HonestEmptyState,
  HypothesisBreadcrumbs,
  HypothesisSubnav,
  MetricExplainer,
  ScientificStatusBadge,
  TagChip,
  UniverseMetric,
  UniverseSectionHeading,
} from "./hypothesis-primitives";

function frenchSelection(selection: string) {
  const labels: Record<string, string> = {
    AWAY: "victoire à l’extérieur",
    DRAW: "match nul",
    HOME: "victoire à domicile",
  };
  return labels[selection] ?? selection;
}

function frenchCutoff(value: string) {
  const labels: Record<string, string> = {
    "H-2": "Deux heures avant le coup d’envoi",
    NEAR_KICKOFF: "Près du coup d’envoi",
  };
  return labels[value] ?? value;
}

function humanizeTechnicalCode(value: string) {
  const labels: Record<string, string> = {
    ABSENCE_GATE: "Preuve des absences avant le match",
    FOOTEDNESS_GATE: "Latéralité sourcée des joueurs",
    FORMATION_GATE: "Formation connue avant le match",
    LINEUP_GATE: "Composition connue avant le match",
    PLAYER_FORM_GATE: "Forme individuelle antérieure",
    STARTER_BASELINE_GATE: "Référence des titulaires habituels",
  };
  return labels[value] ?? value.replaceAll("_", " ").toLocaleLowerCase("fr-FR");
}

function formatObservationCount(value: number | null | undefined) {
  return value == null ? "Non disponible" : formatNumber(value);
}

function MachineHypothesisDetail({
  hypothesisId,
}: {
  hypothesisId: string;
}) {
  const { mode } = useViewMode();
  const record = hypothesisById(hypothesisId);
  if (!record || record.kind !== "machine") return null;
  const hypothesis = record.hypothesis;
  const contract = prospectiveContractByHypothesisId(hypothesisId);
  const observation = hypothesisIntelligence.prospectiveObservations.find(
    (item) => item.hypothesisId === hypothesisId,
  );
  const isValidated = hypothesis.status === "VALIDATED";
  const settledObservationCount =
    observation?.settledObservations ??
    (observation?.prospectiveProfitUnits == null ? 0 : 1);
  const simpleRule = contract
    ? `Observer les ${frenchSelection(contract.primary_price.selection)} en ${hypothesis.competition} lorsque la cote proche du coup d’envoi se situe entre ${new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2 }).format(contract.primary_price.minimum_odds)} et ${new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2 }).format(contract.primary_price.maximum_odds)} et que la marge du marché est inférieure ou égale à ${formatPercent(contract.primary_price.maximum_margin)}.`
    : hypothesis.title;

  return (
    <>
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { href: "/hypotheses", label: "Hypothèses" },
          { href: "/hypotheses/classements", label: "Classements" },
          { label: hypothesis.id },
        ]}
      />
      <HypothesisSubnav />
      <header className="hu-detail-hero">
        <div>
          <div className="hu-tag-list">
            <TagChip kind="family">{hypothesis.competition}</TagChip>
            <TagChip kind="value">
              {frenchSelection(hypothesis.selection)}
            </TagChip>
            <TagChip kind="science" tagId={`origin:${hypothesis.origin}`}>
              {hypothesis.badge}
            </TagChip>
            <ScientificStatusBadge status={hypothesis.status} />
          </div>
          <p className="hu-kicker">Hypothèse {hypothesis.id}</p>
          <h1>{hypothesis.title}</h1>
          <p>{simpleRule}</p>
        </div>
        <aside>
          <span aria-hidden="true">R</span>
          <strong>Découverte automatiquement par Robin</strong>
          <p>
            Cette règle vient du registre machine. Elle n’a pas été proposée
            après observation de son résultat prospectif.
          </p>
        </aside>
      </header>

      {mode === "discovery" ? (
        <section
          aria-label="Lecture Découverte"
          className="hu-section hu-surface hu-mode-summary"
          data-view-mode="discovery"
        >
          <p className="hu-kicker">Vue Découverte</p>
          <h2>L’essentiel en clair</h2>
          <p>
            Robin a repéré cette piste dans des matchs déjà joués. Elle est
            maintenant séparée du passé et observée sur les prochaines
            rencontres, sans pari réel.
          </p>
          <p>
            {isValidated
              ? "Le contrat indique que cette stratégie a franchi les contrôles scientifiques prévus."
              : "Cette piste reste exploratoire : un résultat passé intéressant ne constitue pas encore une preuve."}
          </p>
        </section>
      ) : (
        <>
          <section
            aria-label="Indicateurs d’analyse"
            className="hu-key-metrics hu-detail-metrics"
            data-view-mode="analysis"
          >
            <UniverseMetric
              detail="simulation historique"
              label="Matchs observés"
              tone="blue"
              value={hypothesis.historicalSupport}
            />
            <UniverseMetric
              detail="brut, avant validation"
              label="Résultat historique"
              tone="gold"
              value={formatPercent(hypothesis.historicalRoi)}
            />
            <UniverseMetric
              detail="capital de simulation"
              label="Profit simulé"
              tone="teal"
              value={formatUnits(hypothesis.historicalProfitUnits)}
            />
            <UniverseMetric
              detail="valeur ajustée sur l’ensemble des tests"
              label="Risque de faux positif après correction"
              tone="coral"
              value={
                hypothesis.qValue == null
                  ? "Non disponible"
                  : formatNumber(hypothesis.qValue, 2)
              }
            />
          </section>

          <section className="hu-two-column hu-detail-grid">
            <article className="hu-section hu-surface">
              <UniverseSectionHeading
                eyebrow="Simulation historique"
                title="Ce que le passé montre"
              />
              <div className="hu-confidence-chart">
                <div>
                  <span
                    style={{
                      left: `${Math.max(0, Math.min(100, ((hypothesis.confidenceInterval[0] + 0.1) / 0.5) * 100))}%`,
                      right: `${Math.max(0, Math.min(100, 100 - ((hypothesis.confidenceInterval[1] + 0.1) / 0.5) * 100))}%`,
                    }}
                  />
                  {hypothesis.historicalRoi == null ? null : (
                    <i
                      style={{
                        left: `${Math.max(0, Math.min(100, ((hypothesis.historicalRoi + 0.1) / 0.5) * 100))}%`,
                      }}
                    />
                  )}
                </div>
                <p>
                  Intervalle observé :{" "}
                  {formatPercent(hypothesis.confidenceInterval[0])} à{" "}
                  {formatPercent(hypothesis.confidenceInterval[1])}.
                </p>
              </div>
              <dl className="hu-detail-list">
                <div>
                  <dt>Validation chronologique glissante</dt>
                  <dd>
                    {hypothesis.positiveFolds}/{hypothesis.eligibleFolds} périodes
                    positives
                  </dd>
                </div>
                <div>
                  <dt>Baisse maximale</dt>
                  <dd>Non disponible dans ce contrat public</dd>
                </div>
                <div>
                  <dt>Stabilité</dt>
                  <dd>Non disponible dans ce contrat public</dd>
                </div>
              </dl>
              <p className="hu-evidence-warning">{hypothesis.warning}</p>
            </article>

            <article className="hu-section hu-surface">
              <UniverseSectionHeading
                eyebrow="Après gel"
                title="Observation prospective"
              />
              {contract ? (
                <dl className="hu-detail-list">
                  <div>
                    <dt>Date du gel</dt>
                    <dd>{formatDateTime(contract.frozen_at, true)}</dd>
                  </div>
                  <div>
                    <dt>Heure limite principale</dt>
                    <dd>{frenchCutoff(contract.primary_price.cutoff_name)}</dd>
                  </div>
                  <div>
                    <dt>Matchs examinés</dt>
                    <dd>{formatObservationCount(observation?.fixturesExamined)}</dd>
                  </div>
                  <div>
                    <dt>Matchs éligibles</dt>
                    <dd>{formatObservationCount(observation?.eligibleMatches)}</dd>
                  </div>
                  <div>
                    <dt>Observations réglées</dt>
                    <dd>{formatObservationCount(observation?.settledObservations)}</dd>
                  </div>
                  <div>
                    <dt>Résultat prospectif</dt>
                    <dd>
                      {observation?.prospectiveProfitUnits == null
                        ? "Aucune observation réelle disponible"
                        : formatUnits(observation.prospectiveProfitUnits)}
                    </dd>
                  </div>
                </dl>
              ) : (
                <HonestEmptyState title="Contrat prospectif non disponible">
                  Robin n’affiche aucune condition de prix sans contrat borné.
                </HonestEmptyState>
              )}
            </article>
          </section>
        </>
      )}

      <section className={isValidated ? "hu-section hu-surface hu-mode-summary" : "hu-not-validated"}>
        <span aria-hidden="true">{isValidated ? "✓" : "!"}</span>
        <div>
          <p className="hu-kicker">
            {isValidated ? "Conclusion contractuelle" : "Limite essentielle"}
          </p>
          <h2>
            {isValidated
              ? "Cette stratégie est scientifiquement validée"
              : "Pourquoi ce signal n’est pas validé"}
          </h2>
          {isValidated ? (
            <p>
              Le statut validé vient du contrat scientifique chargé par Robin,
              jamais d’une appréciation ajoutée dans l’interface.
            </p>
          ) : mode === "discovery" ? (
            <p>
              {settledObservationCount > 0
                ? `Robin dispose de ${formatNumber(settledObservationCount)} observation${settledObservationCount > 1 ? "s prospectives réglées" : " prospective réglée"}, mais cet ensemble reste insuffisant pour conclure.`
                : "Un résultat observé dans le passé peut être une coïncidence. Robin attend encore des observations futures suffisamment solides avant de conclure."}
            </p>
          ) : (
            <p>
              Le résultat historique n’a pas résisté à la correction du risque
              de faux positifs
              {hypothesis.qValue == null
                ? " ; la valeur ajustée n’est pas disponible dans le contrat public"
                : ` : la valeur ajustée sur l’ensemble des tests est ${formatNumber(hypothesis.qValue, 2)}`}
              .{" "}
              {settledObservationCount > 0
                ? `${formatNumber(settledObservationCount)} observation${settledObservationCount > 1 ? "s prospectives réglées sont disponibles" : " prospective réglée est disponible"}, sans preuve encore suffisante de stabilité hors échantillon.`
                : "Aucune observation prospective réglée ne permet encore de confirmer une stabilité hors échantillon."}
            </p>
          )}
        </div>
      </section>

      {mode === "discovery" ? null : (
        <section className="hu-section">
          <UniverseSectionHeading
            eyebrow="Comprendre les mesures"
            title="Les mots derrière les chiffres"
          />
          <div className="hu-explainer-grid">
            <MetricExplainer
              expert="Nombre d’observations éligibles après application de toutes les conditions."
              name="Support"
              simple="Le nombre de matchs réellement utilisés pour calculer le résultat."
            />
            <MetricExplainer
              expert="Étendue d’incertitude estimée autour du résultat historique brut."
              name="Intervalle"
              simple="La zone dans laquelle le résultat réel pourrait raisonnablement se situer."
            />
            <MetricExplainer
              expert="Valeur ajustée qui contrôle le taux attendu de fausses découvertes dans l’ensemble des tests ; ce n’est pas une probabilité individuelle."
              name="Risque de faux positif après correction"
              simple="Un indicateur qui tempère les résultats lorsque Robin explore beaucoup d’idées en même temps."
            />
            <MetricExplainer
              expert="Séparation temporelle stricte des périodes d’apprentissage et d’évaluation."
              name="Validation chronologique"
              simple="Robin avance dans le temps sans utiliser le futur pour expliquer le passé."
            />
          </div>
        </section>
      )}

      {mode === "expert" ? (
        <section className="hu-section hu-expert-proof">
          <UniverseSectionHeading
            eyebrow="Vue Expert"
            title="Données, contrat et provenance"
          />
          <dl className="hu-technical-grid">
            <div>
              <dt>Hash de règle</dt>
              <dd><code>{hypothesis.ruleHash}</code></dd>
            </div>
            <div>
              <dt>Hash du contrat</dt>
              <dd><code>{contract?.contract_hash ?? hypothesis.contractHash}</code></dd>
            </div>
            <div>
              <dt>Révision Git source</dt>
              <dd><code>{contract?.source_code_revision ?? "Non disponible"}</code></dd>
            </div>
            <div>
              <dt>Hash de l’arbre source</dt>
              <dd><code>{contract?.source_tree_hash ?? "Non disponible"}</code></dd>
            </div>
            <div>
              <dt>Contrat d’éligibilité</dt>
              <dd><code>{contract?.eligibility_contract ?? "Non disponible"}</code></dd>
            </div>
            <div>
              <dt>Promotion</dt>
              <dd>{contract?.promotion_locked ? "Verrouillée" : "Non documentée"}</dd>
            </div>
          </dl>
        </section>
      ) : null}
    </>
  );
}

function OwnerSeedDetail({ hypothesisId }: { hypothesisId: string }) {
  const { mode } = useViewMode();
  const record = hypothesisById(hypothesisId);
  if (!record || record.kind !== "owner") return null;
  const seed = record.hypothesis;

  return (
    <>
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { href: "/hypotheses", label: "Hypothèses" },
          { label: seed.id },
        ]}
      />
      <HypothesisSubnav />
      <header className="hu-detail-hero hu-seed-hero">
        <div>
          <div className="hu-tag-list">
            <TagChip kind="family" tagId={`origin:${seed.origin}`}>
              Origine humaine
            </TagChip>
            <ScientificStatusBadge status={seed.status} />
          </div>
          <p className="hu-kicker">Graine de recherche {seed.id}</p>
          <h1>{seed.title}</h1>
          <p>{seed.mechanism}</p>
        </div>
        <aside>
          <span aria-hidden="true">D</span>
          <strong>Piste proposée par David</strong>
          <p>
            Cette idée déclenche un espace de recherche. Elle n’est ni un
            résultat, ni une découverte automatique, ni un conseil de mise.
          </p>
        </aside>
      </header>

      <section className="hu-seed-explanation">
        <p className="hu-kicker">Une direction, pas une règle unique</p>
        <h2>Cette graine génère un arbre complet de combinaisons.</h2>
        <p>
          Robin combine les propriétés compatibles, puis ferme chaque branche
          dont les données ne prouvent pas ce qui était connu avant le match.
          Le nombre de branches générables n’est pas exposé par le contrat
          actuel : il reste donc indiqué comme non disponible.
        </p>
      </section>

      {mode === "discovery" ? (
        <section
          aria-label="Lecture Découverte"
          className="hu-section hu-surface hu-mode-summary"
          data-view-mode="discovery"
        >
          <p className="hu-kicker">Vue Découverte</p>
          <h2>Ce que cette idée ouvre</h2>
          <p>
            Cette proposition sert de point de départ à plusieurs branches.
            Robin ne la présente ni comme un résultat ni comme une stratégie.
          </p>
          <Link className="hu-primary-action" href="/hypotheses/arbres">
            Explorer les arbres compatibles
          </Link>
        </section>
      ) : (
        <section className="hu-two-column" data-view-mode="analysis">
          <article className="hu-section hu-surface">
            <UniverseSectionHeading
              eyebrow="Entrées de la graine"
              title="Données nécessaires"
            />
            <div className="hu-gate-list">
              {seed.requiredData.map((gate) => (
                <div key={gate}>
                  <span aria-hidden="true">×</span>
                  <div>
                    <strong>{humanizeTechnicalCode(gate)}</strong>
                    <small>
                      {scientificStatusLabel(seed.currentDataGates[gate])}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          </article>
          <article className="hu-section hu-surface">
            <UniverseSectionHeading
              eyebrow="État de la recherche"
              title="Arbre associé"
            />
            <dl className="hu-detail-list">
              <div>
                <dt>Branches générables</dt>
                <dd>Non disponible dans le contrat public</dd>
              </div>
              <div>
                <dt>Branches matérialisées</dt>
                <dd>{formatNumber(seed.observations)}</dd>
              </div>
              <div>
                <dt>Support minimal visé</dt>
                <dd>{formatNumber(seed.minimumSupport)} matchs</dd>
              </div>
              <div>
                <dt>État</dt>
                <dd>{scientificStatusLabel(seed.status)}</dd>
              </div>
            </dl>
            <Link className="hu-primary-action" href="/hypotheses/arbres">
              Explorer les arbres compatibles
            </Link>
          </article>
        </section>
      )}

      {mode === "expert" ? (
        <section className="hu-section hu-expert-proof">
          <UniverseSectionHeading
            eyebrow="Vue Expert"
            title="Identité et conditions de disponibilité"
          />
          <dl className="hu-technical-grid">
            <div>
              <dt>Identifiant</dt>
              <dd><code>{seed.id}</code></dd>
            </div>
            <div>
              <dt>Origine</dt>
              <dd><code>{seed.origin}</code></dd>
            </div>
            <div>
              <dt>Gelée</dt>
              <dd>{seed.frozen ? "Oui" : "Non"}</dd>
            </div>
            <div>
              <dt>Conditions</dt>
              <dd><code>{seed.requiredData.join(" + ")}</code></dd>
            </div>
          </dl>
        </section>
      ) : null}
    </>
  );
}

function TreeNodeDetail({ nodeId }: { nodeId: string }) {
  const { mode } = useViewMode();
  const descriptor = useMemo(() => {
    const page = hypothesisNodeLocator[nodeId];
    return hypothesisNodePages.find((item) => item.page === page);
  }, [nodeId]);
  const [node, setNode] = useState<HypothesisTreeNode | null>(null);
  const [loadState, setLoadState] = useState<
    "error" | "loading" | "not-found" | "ready"
  >(descriptor ? "loading" : "not-found");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!descriptor) return;
    let cancelled = false;
    void fetch(descriptor.url)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`NODE_PAGE_${descriptor.page}_UNAVAILABLE`);
        }
        return response.json();
      })
      .then((payload: { items: HypothesisTreeNode[] }) => {
        if (cancelled) return;
        const nextNode =
          payload.items.find((item) => item.node_id === nodeId) ?? null;
        setNode(nextNode);
        setLoadState(nextNode ? "ready" : "not-found");
      })
      .catch(() => {
        if (!cancelled) setLoadState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [attempt, descriptor, nodeId]);

  const children = useMemo(
    () => hypothesisChildrenByParent[nodeId] ?? [],
    [nodeId],
  );

  if (loadState === "loading") {
    return <p className="hu-loading" role="status">Chargement de la branche…</p>;
  }
  if (loadState === "error") {
    return (
      <div className="hu-load-error" role="alert">
        <div>
          <strong>La branche n’a pas pu être chargée</strong>
          <p>
            Le fichier borné est momentanément indisponible. Aucun état
            scientifique n’est déduit de cet échec réseau.
          </p>
        </div>
        <button
          onClick={() => {
            setLoadState("loading");
            setAttempt((current) => current + 1);
          }}
          type="button"
        >
          Réessayer
        </button>
      </div>
    );
  }
  if (loadState === "not-found" || !node) {
    return (
      <HonestEmptyState title="Hypothèse introuvable">
        Aucun nœud borné ne correspond à cet identifiant. Retournez à
        l’explorateur pour choisir une branche disponible.
      </HonestEmptyState>
    );
  }

  return (
    <>
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { href: "/hypotheses", label: "Hypothèses" },
          { href: "/hypotheses/arbres", label: "Arbres" },
          { label: compactNodeId(node.node_id) },
        ]}
      />
      <HypothesisSubnav />
      <header className="hu-detail-hero">
        <div>
          <div className="hu-tag-list">
            <TagChip kind="family" tagId={`family:${node.family}`}>
              {familyDisplayName(node.family)}
            </TagChip>
            <TagChip tagId={`subfamily:${node.subfamily}`}>
              {subfamilyDisplayName(node.subfamily)}
            </TagChip>
            <ScientificStatusBadge status={node.materialization_disposition} />
          </div>
          <p className="hu-kicker">Branche {compactNodeId(node.node_id)}</p>
          <h1>{node.display_rule_fr}</h1>
          <p>
            Cette branche combine {node.parent_ids.length || 1} direction
            {node.parent_ids.length > 1 ? "s" : ""} de recherche et conserve la
            preuve de ses parents.
          </p>
        </div>
        <aside>
          <span aria-hidden="true">↳</span>
          <strong>{children.length} descendant{children.length > 1 ? "s" : ""} matérialisé{children.length > 1 ? "s" : ""}</strong>
          <p>
            {node.parent_ids.length
              ? `${node.parent_ids.length} parent${node.parent_ids.length > 1 ? "s" : ""} relié${node.parent_ids.length > 1 ? "s" : ""}.`
              : "Cette branche est une racine de l’arbre borné."}
          </p>
        </aside>
      </header>

      {mode === "discovery" ? (
        <section
          aria-label="Lecture Découverte"
          className="hu-section hu-surface hu-mode-summary"
          data-view-mode="discovery"
        >
          <p className="hu-kicker">Vue Découverte</p>
          <h2>Sa place dans l’arbre</h2>
          <p>
            Cette branche {node.parent_id ? "prolonge une idée parente" : "ouvre un arbre"}{" "}
            et possède {children.length} descendant
            {children.length > 1 ? "s" : ""} direct
            {children.length > 1 ? "s" : ""} matérialisé
            {children.length > 1 ? "s" : ""}.
          </p>
          <Link className="hu-primary-action" href={`/hypotheses/arbres/${node.node_id}`}>
            Ouvrir dans l’arbre
          </Link>
        </section>
      ) : (
        <>
          <section
            aria-label="Indicateurs d’analyse"
            className="hu-key-metrics hu-detail-metrics"
            data-view-mode="analysis"
          >
            <UniverseMetric label="Support" tone="blue" value={node.support == null ? "Non disponible" : node.support} />
            <UniverseMetric label="Parents" tone="violet" value={node.parent_ids.length} />
            <UniverseMetric label="Descendants directs" tone="teal" value={children.length} />
            <UniverseMetric label="État matériel" tone="gold" value={scientificStatusLabel(node.materialization_disposition)} />
          </section>

          <section className="hu-two-column">
            <article className="hu-section hu-surface">
              <UniverseSectionHeading title="Arbre proche" />
              <dl className="hu-detail-list">
                <div>
                  <dt>Parent principal</dt>
                  <dd>
                    {node.parent_id ? (
                      <Link href={`/hypotheses/${node.parent_id}`}>
                        {compactNodeId(node.parent_id)}
                      </Link>
                    ) : "Racine"}
                  </dd>
                </div>
                <div>
                  <dt>Autres parents</dt>
                  <dd>
                    {node.parent_ids.length
                      ? node.parent_ids.map(compactNodeId).join(" · ")
                      : "Aucun"}
                  </dd>
                </div>
                <div>
                  <dt>Enfants</dt>
                  <dd>{children.length ? children.map(compactNodeId).join(" · ") : "Aucun matérialisé"}</dd>
                </div>
              </dl>
              <Link className="hu-primary-action" href={`/hypotheses/arbres/${node.node_id}`}>
                Ouvrir dans l’arbre
              </Link>
            </article>
            <article className="hu-section hu-surface">
              <UniverseSectionHeading title="Disponibilité des données" />
              <div className="hu-tag-list">
                {node.data_gates.map((gate) => (
                  <ScientificStatusBadge key={gate} status={gate} />
                ))}
              </div>
              {node.materialization_disposition === "DATA_GATE_BLOCKED" ? (
                <p className="hu-evidence-warning">
                  Cette branche existe, mais sa preuve temporelle est insuffisante.
                  Robin la conserve sans l’exécuter.
                </p>
              ) : null}
            </article>
          </section>
        </>
      )}

      {mode === "expert" ? (
        <section className="hu-section hu-expert-proof">
          <UniverseSectionHeading eyebrow="Vue Expert" title="Règle technique" />
          <pre><code>{JSON.stringify(node.technical_rule, null, 2)}</code></pre>
          <dl className="hu-technical-grid">
            <div><dt>Hash du nœud</dt><dd><code>{node.payload_hash}</code></dd></div>
            <div><dt>Identifiant complet</dt><dd><code>{node.node_id}</code></dd></div>
          </dl>
        </section>
      ) : null}
    </>
  );
}

export function HypothesisDetailPage({
  hypothesisId,
}: {
  hypothesisId: string;
}) {
  const known = hypothesisById(hypothesisId);
  return (
    <div className="hu-page hu-detail-page">
      {known?.kind === "machine" ? (
        <MachineHypothesisDetail hypothesisId={hypothesisId} />
      ) : known?.kind === "owner" ? (
        <OwnerSeedDetail hypothesisId={hypothesisId} />
      ) : (
        <TreeNodeDetail nodeId={hypothesisId} />
      )}
    </div>
  );
}
