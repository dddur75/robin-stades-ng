import {
  formatNumber,
  formatPercent,
  formatUnits,
  t,
} from "../../i18n";
import {
  operationalEvidence,
  scientificInvariants,
} from "../../lib/presentation";
import {
  EmptyState,
  EvidenceNote,
  MetricCard,
  PageHeader,
  SectionHeading,
  StatusBadge,
  TechnicalList,
} from "../common/ui";
import { ExpertOnly } from "../common/view-mode";

export function ResultsPage() {
  const bankroll = scientificInvariants.bankroll;
  const results = scientificInvariants.results;
  const curve = bankroll.curve.length ? bankroll.curve : [bankroll.currentUnits];
  const curveMaximum = Math.max(...curve);
  const curveMinimum = Math.min(...curve);
  const curveMiddle = (curveMaximum + curveMinimum) / 2;
  return (
    <>
      <PageHeader
        eyebrow={t("results.eyebrow")}
        subtitle={t("results.subtitle")}
        title={t("results.title")}
      >
        <StatusBadge value={scientificInvariants.dataStatus} />
      </PageHeader>

      <section className="metrics-grid results-metrics">
        <MetricCard detail="politique scientifique versionnée" label={t("results.bankrollInitial")} tone="blue" value={formatUnits(bankroll.initialUnits)} />
        <MetricCard detail="registre shadow" label={t("results.bankrollCurrent")} tone="green" value={formatUnits(bankroll.currentUnits)} />
        <MetricCard detail="preuve du ledger" label={t("results.profit")} value={formatUnits(results.profitUnits)} />
        <MetricCard detail="calculé après règlement" label={t("results.roi")} value={formatPercent(results.roi)} />
        <MetricCard detail="preuve du ledger" label={t("results.drawdown")} value={formatUnits(bankroll.maxDrawdownUnits)} />
        <MetricCard detail="registre prospectif" label={t("results.decisions")} value={formatNumber(operationalEvidence.decisions)} />
      </section>

      <section className="result-boundaries">
        {[
          {
            number: "01",
            title: t("results.history"),
            value: `${formatNumber(scientificInvariants.laboratory.hypothesesGenerated)} hypothèses`,
            text: "Recherche rétrospective sur des données historiques. Aucun résultat n’est promu automatiquement.",
            status: "NO_PROMOTION",
          },
          {
            number: "02",
            title: t("results.prospective"),
            value: `${formatNumber(operationalEvidence.deepObservations)} observation`,
            text: "Les tests prospectifs attendent encore les données profondes pré-match.",
            status: "WAITING_FOR_OBSERVATIONS",
          },
          {
            number: "03",
            title: t("results.shadow"),
            value: `${formatNumber(operationalEvidence.decisions)} décision`,
            text: "Aucune décision simulée ne peut exister sans candidat validé.",
            status: "NO_CANDIDATE",
          },
          {
            number: "04",
            title: t("results.settled"),
            value: `${formatNumber(results.settlements)} résultat`,
            text: "Les gains comme les pertes seront affichés après un règlement vérifié.",
            status: "PENDING",
          },
        ].map((section) => (
          <article key={section.number}>
            <span>{section.number}</span>
            <h2>{section.title}</h2>
            <strong>{section.value}</strong>
            <p>{section.text}</p>
            <StatusBadge value={section.status} />
          </article>
        ))}
      </section>

      <section className="two-columns">
        <article className="section-card">
          <SectionHeading title={t("results.chart.title")} />
          <div
            aria-label={t("results.chart.summary")}
            className="bankroll-chart"
            role="img"
          >
            <div className="chart-y-axis">
              <span>{formatNumber(curveMaximum, 1)}</span>
              <span>{formatNumber(curveMiddle, 1)}</span>
              <span>{formatNumber(curveMinimum, 1)}</span>
            </div>
            <div className="chart-plot">
              <i className="grid-line top" />
              <i className="grid-line middle" />
              <i className="grid-line bottom" />
              <b />
              <span>Départ</span>
              <span>Aujourd’hui</span>
            </div>
          </div>
          <p className="chart-summary">{t("results.chart.summary")}</p>
        </article>
        <article className="section-card">
          <SectionHeading title="Répartition actuelle" />
          <div className="status-distribution">
            <div style={{ "--share": "100%" } as React.CSSProperties}>
              <span>NO BET par défaut</span>
              <strong>Actif</strong>
              <i />
            </div>
            <div style={{ "--share": "0%" } as React.CSSProperties}>
              <span>Décisions simulées</span>
              <strong>{formatNumber(scientificInvariants.ledger.decisions)}</strong>
              <i />
            </div>
            <div style={{ "--share": "0%" } as React.CSSProperties}>
              <span>Résultats réglés</span>
              <strong>{formatNumber(results.settlements)}</strong>
              <i />
            </div>
          </div>
          <EvidenceNote>
            « Actif » décrit une règle de sécurité. Ce n’est pas un taux de
            performance.
          </EvidenceNote>
        </article>
      </section>

      <section className="section-card">
        <EmptyState
          text={t("results.empty.text")}
          title={t("results.empty.title")}
        />
      </section>

      <ExpertOnly>
        <section className="section-card">
          <SectionHeading title="Détails du registre simulé" />
          <TechnicalList rows={[
            { label: "Décisions", value: scientificInvariants.ledger.decisions },
            { label: "Règlements", value: scientificInvariants.ledger.settlements },
            { label: "Unités engagées", value: results.settledStakeUnits },
            { label: "État production", value: <StatusBadge value={scientificInvariants.productionStatus} showTechnical /> },
            { label: "Paris réels", value: <code>{String(scientificInvariants.realBets)}</code> },
          ]} />
        </section>
      </ExpertOnly>
    </>
  );
}
