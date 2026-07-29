import { formatNumber, formatPercent, t } from "../../i18n";
import { hypothesisIntelligence } from "../../lib/presentation";
import preview from "../../universal-genome-preview.json";
import {
  EvidenceNote,
  MetricCard,
  PageHeader,
  ProgressBar,
  SectionHeading,
  StatusBadge,
} from "../common/ui";
import { ExpertOnly } from "../common/view-mode";

export function LaboratoryPage() {
  const intelligence = hypothesisIntelligence;

  return (
    <>
      <PageHeader
        eyebrow={t("laboratory.eyebrow")}
        subtitle="Les découvertes automatiques, les hypothèses humaines et les observations prospectives restent séparées."
        title="Hypothèses et découvertes"
      />

      <EvidenceNote>
        Une découverte historique reste un signal exploratoire. Aucune
        performance future n’est annoncée, aucun pari réel n’est envoyé et
        aucune validation n’est automatique.
      </EvidenceNote>

      <section className="expert-section hypothesis-section" id="genome-universel">
        <SectionHeading
          subtitle="La grammaire représente les familles compatibles sans matérialiser toutes les combinaisons."
          title="Génome universel des hypothèses"
        />
        <div className="metrics-grid">
          <MetricCard
            detail={preview.symbolicStatus}
            label="Propriétés classées"
            tone="blue"
            value={formatNumber(preview.properties)}
          />
          <MetricCard
            detail="ontologie ouverte"
            label="Familles"
            tone="violet"
            value={formatNumber(preview.families)}
          />
          <MetricCard
            detail="replay identique"
            label="Nœuds exécutés"
            tone="green"
            value={formatNumber(preview.executed)}
          />
          <MetricCard
            detail="aucune promotion"
            label="Stratégies validées"
            value={formatNumber(preview.validatedStrategies)}
          />
        </div>
        <EvidenceNote>{preview.warning}</EvidenceNote>
      </section>

      <section className="expert-section hypothesis-section" id="decouvertes-robin">
        <SectionHeading
          subtitle="Règles générées par Python et contrôlées contre les preuves Jalon 10."
          title="A. Découvertes de Robin"
        />
        <div className="metrics-grid">
          <MetricCard
            detail="règles exécutées"
            label="Registre machine"
            tone="blue"
            value={formatNumber(intelligence.registry.machineDiscovered)}
          />
          <MetricCard
            detail="contrats gelés"
            label="Observation prospective"
            tone="violet"
            value={formatNumber(intelligence.registry.prospectiveFrozen)}
          />
          <MetricCard
            detail="tolérance zéro"
            label="Doublons canoniques"
            tone="green"
            value={formatNumber(intelligence.registry.duplicates)}
          />
        </div>
        <div className="machine-discovery-grid">
          {intelligence.machineDiscoveries.map((discovery) => (
            <article className="hypothesis-card machine-discovery-card" key={discovery.id}>
              <div className="hypothesis-card-head">
                <span>{discovery.id}</span>
                <span className="origin-badge machine">{discovery.badge}</span>
              </div>
              <p className="eyebrow">Découverte historique de Robin</p>
              <h2>{discovery.title}</h2>
              <p>
                {discovery.competition} · {discovery.selection} · {discovery.market}
              </p>
              <dl className="discovery-metrics">
                <div><dt>Support historique</dt><dd>{formatNumber(discovery.historicalSupport)}</dd></div>
                <div><dt>ROI historique brut observé</dt><dd>{formatPercent(discovery.historicalRoi)}</dd></div>
                <div><dt>Walk-forward brut</dt><dd>{discovery.positiveFolds}/{discovery.eligibleFolds}</dd></div>
                <div><dt>q-value</dt><dd>{formatNumber(discovery.qValue ?? 0, 2)}</dd></div>
              </dl>
              <div className="scientific-labels">
                <span>Signal exploratoire</span>
                <span>Non validé après correction des tests multiples</span>
                <span>Gelé pour observation prospective</span>
                <span>Aucun pari réel</span>
              </div>
              <p className="historical-warning">{discovery.warning}</p>
              <StatusBadge value={discovery.prospectiveStatus} />
              <ExpertOnly>
                <div className="technical-strip">
                  <code>rule={discovery.ruleHash}</code>
                  <code>contract={discovery.contractHash}</code>
                </div>
              </ExpertOnly>
            </article>
          ))}
        </div>
      </section>

      <section className="expert-section hypothesis-section" id="hypotheses-david">
        <SectionHeading
          subtitle="Ces questions ont été proposées par David; elles ne sont pas des découvertes automatiques de Robin."
          title="B. Hypothèses proposées par David"
        />
        <div className="hypothesis-grid">
          {intelligence.ownerHypotheses.map((hypothesis) => (
            <article className="hypothesis-card" key={hypothesis.id}>
              <div className="hypothesis-card-head">
                <span>{hypothesis.id}</span>
                <span className="origin-badge owner">{hypothesis.badge}</span>
              </div>
              <h2>{hypothesis.title}</h2>
              <p>{hypothesis.mechanism}</p>
              <div className="hypothesis-data">
                <span>{t("laboratory.required")}</span>
                <div className="family-chips">
                  {hypothesis.requiredData.map((family) => (
                    <span key={family}>{family}</span>
                  ))}
                </div>
              </div>
              <ProgressBar
                label={`${t("laboratory.accumulated")} · ${formatNumber(hypothesis.observations)} / ${formatNumber(hypothesis.minimumSupport)}`}
                value={0}
              />
              <div className="blocked-reason">
                <strong>Gates manquants</strong>
                <p>{Object.keys(hypothesis.currentDataGates).join(" · ")}</p>
              </div>
              <StatusBadge value={hypothesis.status} />
            </article>
          ))}
        </div>
      </section>

      <section className="expert-section hypothesis-section" id="observation-prospective">
        <SectionHeading
          subtitle="Les métriques prospectives restent vides jusqu’aux premiers cutoffs réellement dus."
          title="C. En observation prospective"
        />
        <div className="prospective-contract-grid">
          {intelligence.prospectiveObservations.map((observation) => (
            <article className="section-card" key={observation.hypothesisId}>
              <div className="hypothesis-card-head">
                <strong>{observation.hypothesisId}</strong>
                <StatusBadge value={observation.status} />
              </div>
              <dl className="discovery-metrics">
                <div><dt>Matchs examinés</dt><dd>{observation.fixturesExamined}</dd></div>
                <div><dt>Matchs éligibles</dt><dd>{observation.eligibleMatches}</dd></div>
                <div><dt>Observations réglées</dt><dd>{observation.settledObservations}</dd></div>
                <div><dt>Support actuel</dt><dd>{observation.currentSupport}</dd></div>
              </dl>
              <p>Résultat prospectif : aucune observation réelle disponible.</p>
              <ExpertOnly><code>{observation.contractHash}</code></ExpertOnly>
            </article>
          ))}
        </div>
      </section>

      <section className="expert-section hypothesis-section" id="bloquees-rejetees">
        <SectionHeading
          subtitle="Les rejets restent visibles et ne sont jamais transformés en succès."
          title="D. Bloquées ou rejetées"
        />
        <div className="metrics-grid">
          <MetricCard
            detail="correction des tests multiples"
            label="Rejets exploratoires"
            tone="orange"
            value={formatNumber(intelligence.blockedOrRejected.multipleTestingRejected)}
          />
          <MetricCard
            detail="minimum historique non atteint"
            label="Support insuffisant"
            value={formatNumber(intelligence.blockedOrRejected.insufficientSupport)}
          />
          <MetricCard
            detail="aucune observation"
            label="Rejets prospectifs"
            value={formatNumber(intelligence.blockedOrRejected.prospectiveRejected)}
          />
          <MetricCard
            detail="aucune suppression"
            label="Archivées"
            value={formatNumber(intelligence.blockedOrRejected.archived)}
          />
        </div>
      </section>
    </>
  );
}
