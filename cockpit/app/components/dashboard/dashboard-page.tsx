import { Countdown, SinceLastVisit } from "../common/client-widgets";
import {
  EvidenceNote,
  InlineLink,
  MetricCard,
  PageHeader,
  ProgressBar,
  SectionHeading,
  StatusBadge,
  TechnicalList,
} from "../common/ui";
import { ExpertOnly } from "../common/view-mode";
import { MatchCard } from "../matches/match-card";
import {
  formatDateTime,
  formatNumber,
  formatUnits,
  t,
} from "../../i18n";
import {
  dataFamilyLabels,
  hypotheses,
  matches,
  nextCaptures,
  operationalEvidence,
} from "../../lib/presentation";

const progressSteps = [
  { label: "Rencontres enregistrées", done: true },
  { label: "Fenêtres planifiées", done: true },
  { label: "Données profondes", done: false },
  { label: "Hypothèses testables", done: false },
  { label: "Décisions simulées", done: false },
];

export function DashboardPage() {
  const next = nextCaptures[0];
  return (
    <>
      <section className="hero">
        <PageHeader
          eyebrow={t("home.eyebrow")}
          title={t("home.title", { count: operationalEvidence.fixtures })}
          subtitle={t("home.subtitle")}
        >
          <div className="hero-statuses">
            <StatusBadge value={operationalEvidence.status} />
            <StatusBadge value="PRODUCTION_LOCKED" />
          </div>
        </PageHeader>
        <div className="hero-pitch" aria-hidden="true">
          <i />
          <i />
          <i />
          <span className="ball-dot" />
        </div>
      </section>

      <section className="metrics-grid metrics-home" aria-label="Indicateurs principaux">
        <MetricCard
          detail="prochaine journée de Ligue 1"
          icon="◉"
          label={t("home.metrics.matches")}
          tone="blue"
          value={formatNumber(operationalEvidence.fixtures)}
        />
        <MetricCard
          detail={t("home.metrics.verified")}
          icon="◫"
          label={t("home.metrics.windows")}
          tone="green"
          value={formatNumber(operationalEvidence.activeWindows)}
        />
        <MetricCard
          detail={t("home.metrics.verified")}
          icon="✓"
          label={t("home.metrics.captures")}
          tone="green"
          value={formatNumber(operationalEvidence.physicalEvidence)}
        />
        <MetricCard
          detail={t("home.metrics.waiting")}
          icon="◇"
          label={t("home.metrics.deep")}
          tone="violet"
          value={formatNumber(operationalEvidence.deepObservations)}
        />
        <MetricCard
          detail="aucune promotion automatique"
          icon="○"
          label={t("home.metrics.candidates")}
          tone="orange"
          value={formatNumber(operationalEvidence.candidates)}
        />
        <MetricCard
          detail="simulation sans argent"
          icon="∿"
          label={t("home.metrics.bankroll")}
          value={formatUnits(1_000)}
        />
      </section>

      <section className="dashboard-grid">
        <article className="feature-card next-capture-card">
          <SectionHeading
            title={t("home.next.title")}
            subtitle={t("home.next.subtitle")}
            action={<StatusBadge value={next.status} />}
          />
          <div className="countdown">
            <span>{t("home.next.in")}</span>
            <strong><Countdown target={next.dueAt} /></strong>
            <time dateTime={next.dueAt}>{formatDateTime(next.dueAt, true)}</time>
          </div>
          <dl className="capture-details">
            <div><dt>{t("home.next.match")}</dt><dd>{next.match}</dd></div>
            <div><dt>{t("home.next.data")}</dt><dd>{dataFamilyLabels[next.family]}</dd></div>
            <div><dt>{t("home.next.workflow")}</dt><dd>{t("home.next.workflowValue")}</dd></div>
            <div><dt>{t("home.next.cost")}</dt><dd>{t("home.next.costValue")}</dd></div>
          </dl>
          <InlineLink href="/observatoire">{t("nav.observatory")}</InlineLink>
        </article>

        <article className="feature-card visit-card">
          <span className="feature-icon" aria-hidden="true">↻</span>
          <SectionHeading title={t("home.visit.title")} />
          <SinceLastVisit />
          <small>Cette préférence reste sur votre appareil et ne contient aucune donnée personnelle.</small>
        </article>

        <article className="feature-card understand-card">
          <p className="eyebrow">{t("home.understand.title")}</p>
          <h2>{t("home.understand.question")}</h2>
          <p>{t("home.understand.answer")}</p>
          <InlineLink href="/methode">{t("action.learnMore")}</InlineLink>
        </article>
      </section>

      <section className="section-block">
        <SectionHeading
          title={t("home.progress.title")}
          subtitle={t("home.progress.subtitle")}
        />
        <div className="journey" aria-label="Progression actuelle">
          {progressSteps.map((step, index) => (
            <div className={step.done ? "done" : ""} key={step.label}>
              <span>{step.done ? "✓" : index + 1}</span>
              <strong>{step.label}</strong>
              <small>{step.done ? "Vérifié" : "En attente"}</small>
            </div>
          ))}
        </div>
        <ExpertOnly>
          <EvidenceNote>
            Les 531 fenêtres de la politique initiale sont conservées comme preuves
            inactives. Les 441 fenêtres actives correspondent à la politique révisée
            non chevauchante.
          </EvidenceNote>
        </ExpertOnly>
      </section>

      <section className="section-block">
        <SectionHeading
          action={<InlineLink href="/matchs">{t("action.seeAll")}</InlineLink>}
          subtitle={t("home.matches.subtitle")}
          title={t("home.matches.title")}
        />
        <div className="match-preview-grid">
          {matches.slice(0, 3).map((match) => (
            <MatchCard key={match.id} match={match} />
          ))}
        </div>
      </section>

      <section className="section-block">
        <SectionHeading
          action={<InlineLink href="/laboratoire">{t("action.seeAll")}</InlineLink>}
          subtitle={t("home.hypotheses.subtitle")}
          title={t("home.hypotheses.title")}
        />
        <div className="hypothesis-preview-grid">
          {hypotheses.slice(0, 3).map((hypothesis) => (
            <article className="hypothesis-mini" key={hypothesis.id}>
              <div>
                <span>{hypothesis.id}</span>
                <StatusBadge value={hypothesis.status} />
              </div>
              <h3>{hypothesis.title}</h3>
              <p>{hypothesis.mechanism}</p>
              <ProgressBar
                label={`${hypothesis.observations} / ${hypothesis.minimumSupport} observations`}
                value={hypothesis.coverage}
              />
            </article>
          ))}
        </div>
      </section>

      <section className="guarantees">
        <SectionHeading title={t("home.guarantees.title")} />
        <div>
          {[
            ["⌁", t("home.guarantees.noRealBet")],
            ["≈", t("home.guarantees.noPromise")],
            ["↓", t("home.guarantees.losses")],
            ["◷", t("home.guarantees.temporal")],
          ].map(([icon, label]) => (
            <article key={label}>
              <span aria-hidden="true">{icon}</span>
              <strong>{label}</strong>
            </article>
          ))}
        </div>
        <ExpertOnly>
          <TechnicalList
            rows={[
              { label: "Artefact source", value: <code>{operationalEvidence.sourceRun}</code> },
              { label: "Révision source", value: <code>{operationalEvidence.sourceRevision}</code> },
              { label: "Preuves du registre", value: `${operationalEvidence.ledger.events} événements` },
              { label: "Tête de chaîne", value: <code>{operationalEvidence.ledger.headHash}</code> },
            ]}
          />
        </ExpertOnly>
      </section>
    </>
  );
}
