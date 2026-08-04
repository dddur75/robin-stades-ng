import { allHypothesisFamilies } from "../../lib/hypothesis-universe";
import {
  hypothesisDataQualityWorkspace,
  hypothesisSemanticRoles,
} from "../../lib/hypothesis-quality";
import type { CoverageDeskModel } from "../../lib/p0-coverage-desk";
import { EvidenceNote, MetricCard, PageHeader, SectionHeading, TechnicalList } from "../common/ui";
import { P0CoverageDesk } from "./p0-coverage-desk";

const metadataRoles = [
  "DATA_QUALITY_METADATA",
  "AVAILABILITY_METADATA",
  "PROVENANCE_METADATA",
] as const;

const roleLabels: Record<(typeof metadataRoles)[number], string> = {
  DATA_QUALITY_METADATA: "Qualité",
  AVAILABILITY_METADATA: "Disponibilité",
  PROVENANCE_METADATA: "Provenance",
};

export function DataQualityDiagnostics({
  p0Coverage,
}: {
  p0Coverage: CoverageDeskModel;
}) {
  const workspace = hypothesisDataQualityWorkspace;
  const blockedFamilies = allHypothesisFamilies.filter(
    (family) => family.availability_status === "DATA_GATE_BLOCKED",
  );
  const partialFamilies = allHypothesisFamilies.filter(
    (family) => family.availability_status === "PARTIAL",
  );

  return (
    <>
      <PageHeader
        eyebrow="Espace Expert · diagnostic interne"
        title={workspace.title_fr}
        subtitle="Les valeurs manquantes, la couverture et la provenance contrôlent les pipelines. Elles ne constituent jamais une hypothèse football publique."
      />

      <EvidenceNote>
        Cet espace est volontairement séparé des classements, arbres, comparaisons
        et observations prospectives. Un indicateur absent ferme une porte de
        données au lieu de devenir un signal.
      </EvidenceNote>

      <P0CoverageDesk model={p0Coverage} />

      <section className="expert-section">
        <SectionHeading
          title="Diagnostics sémantiques du catalogue — hors preuve P0"
          subtitle="Classification historique du catalogue. Elle ne ferme aucun dénominateur P0 et n’ouvre aucune hypothèse."
        />
        <div className="metrics-grid">
          {metadataRoles.map((role, index) => (
            <MetricCard
              key={role}
              detail="hors hypothèses publiques"
              label={roleLabels[role]}
              tone={index === 0 ? "orange" : index === 1 ? "blue" : "violet"}
              value={String(hypothesisSemanticRoles.role_counts[role] ?? 0)}
            />
          ))}
          <MetricCard
            detail="données non observables avant le match"
            label="Familles bloquées"
            tone="orange"
            value={String(blockedFamilies.length)}
          />
          <MetricCard
            detail="couverture encore incomplète"
            label="Familles partielles"
            tone="blue"
            value={String(partialFamilies.length)}
          />
          <MetricCard
            detail="retirées de la longue traîne publique"
            label="Branches techniques"
            tone="green"
            value={String(workspace.legacy_public_false_hypothesis_branches_removed)}
          />
        </div>
      </section>

      <section className="expert-section">
        <SectionHeading
          title="Valeurs manquantes et disponibilité"
          subtitle="Ces champs peuvent révéler un biais de couverture, jamais une stratégie."
        />
        <div className="hypothesis-preview-grid">
          {workspace.diagnostic_properties.map((property) => (
            <article className="hypothesis-card" key={property.property_id}>
              <p className="eyebrow">{roleLabels[property.semantic_role as keyof typeof roleLabels]}</p>
              <h3>{property.display_name_fr}</h3>
              <p>
                Utilisé pour contrôler la réception, la qualité ou la traçabilité
                des données avant le coup d’envoi.
              </p>
              <code>{property.property_id}</code>
            </article>
          ))}
        </div>
      </section>

      <section className="expert-section">
        <SectionHeading
          title="Contrôles internes exclus"
          subtitle="Conservés pour éprouver la chaîne de calcul, absents de toutes les surfaces football."
        />
        <TechnicalList
          rows={workspace.internal_controls.map((control) => ({
            label:
              control.semantic_role === "NEGATIVE_CONTROL"
                ? "Contrôle négatif logique"
                : "Diagnostic de valeur manquante",
            value: (
              <>
                <code>{control.property_id}</code>
                <span> · jamais classé</span>
              </>
            ),
          }))}
        />
      </section>

      <section className="expert-section">
        <SectionHeading title="Couverture des familles" />
        <TechnicalList
          rows={[
            {
              label: "Bloquées",
              value: blockedFamilies.map((family) => family.display_name_fr).join(" · "),
            },
            {
              label: "Partielles",
              value: partialFamilies.map((family) => family.display_name_fr).join(" · "),
            },
            {
              label: "Appels fournisseur",
              value: String(workspace.provider_calls),
            },
            {
              label: "Écritures live",
              value: String(workspace.live_writes),
            },
          ]}
        />
      </section>
    </>
  );
}
