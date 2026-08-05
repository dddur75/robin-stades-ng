import type { CoverageDeskModel } from "../../lib/p0-coverage-desk";
import { t } from "../../i18n";
import { MetricCard, StatusBadge } from "../common/ui";

import styles from "./p0-coverage-desk.module.css";

function gateReason(status: string) {
  return status === "BLOCKED_BY_SOURCE"
    ? t("coverage.gates.blockedSource")
    : t("coverage.gates.blockedCoverage");
}

const rateCopy = {
  scope_completion: {
    detail: "coverage.rate.scopeCompletion.detail",
    label: "coverage.rate.scopeCompletion.label",
  },
  normalization_integrity: {
    detail: "coverage.rate.normalizationIntegrity.detail",
    label: "coverage.rate.normalizationIntegrity.label",
  },
  content_presence: {
    detail: "coverage.rate.contentPresence.detail",
    label: "coverage.rate.contentPresence.label",
  },
} as const;

const journeyCopy = {
  data: {
    detail: "coverage.journey.data.detail",
    label: "coverage.journey.data.label",
  },
  hypothesis: {
    detail: "coverage.journey.hypothesis.detail",
    label: "coverage.journey.hypothesis.label",
  },
  strategy: {
    detail: "coverage.journey.strategy.detail",
    label: "coverage.journey.strategy.label",
  },
  matches: {
    detail: "coverage.journey.matches.detail",
    label: "coverage.journey.matches.label",
  },
} as const;

const trustCopy = {
  why: {
    answer: "coverage.trust.why.answer",
    question: "coverage.trust.why.question",
  },
  source: {
    answer: "coverage.trust.source.answer",
    question: "coverage.trust.source.question",
  },
  invalidate: {
    answer: "coverage.trust.invalidate.answer",
    question: "coverage.trust.invalidate.question",
  },
  temporality: {
    answer: "coverage.trust.temporality.answer",
    question: "coverage.trust.temporality.question",
  },
  correction: {
    answer: "coverage.trust.correction.answer",
    question: "coverage.trust.correction.question",
  },
} as const;

export function P0CoverageDesk({ model }: { model: CoverageDeskModel }) {
  return (
    <section
      aria-labelledby="coverage-p0-title"
      className={"expert-section " + styles.desk}
      id="coverage-p0"
    >
      <header className={styles.header}>
        <div>
          <p className="eyebrow">{t("coverage.eyebrow")}</p>
          <h2 id="coverage-p0-title">{t("coverage.title")}</h2>
          <p>{t("coverage.intro")}</p>
        </div>
        <StatusBadge value={model.statusCode} />
      </header>

      <div aria-label="État de la preuve" className={styles.proofState}>
        <article>
          <span aria-hidden="true">◇</span>
          <div>
            <strong>{t("coverage.definition.title")}</strong>
            <small>{t("coverage.definition.detail")}</small>
          </div>
        </article>
        <article>
          <span aria-hidden="true">◔</span>
          <div>
            <strong>{t("coverage.empirical.title")}</strong>
            <small>{t("coverage.empirical.detail")}</small>
          </div>
        </article>
      </div>

      <div className={"metrics-grid " + styles.metrics}>
        <MetricCard
          detail={t("coverage.metrics.total.detail", {
            competitions: model.competitionCount,
            seasons: model.seasonCount,
            families: model.familyCount,
          })}
          icon="▦"
          label={t("coverage.metrics.total.label")}
          tone="violet"
          value={String(model.totalCells)}
        />
        <MetricCard
          detail={t("coverage.metrics.closed.detail", { open: model.openCells })}
          icon="○"
          label={t("coverage.metrics.closed.label")}
          tone="orange"
          value={String(model.closedCells)}
        />
        <MetricCard
          detail={t("coverage.metrics.calendar.detail")}
          icon="◇"
          label={t("coverage.metrics.calendar.label")}
          tone="orange"
          value={model.calendarReady + "/" + model.calendarTotal}
        />
        <MetricCard
          detail={t("coverage.metrics.functional.detail")}
          icon="⊘"
          label={t("coverage.metrics.functional.label")}
          tone="orange"
          value={model.functionalGatesReady + "/" + model.functionalGatesTotal}
        />
      </div>

      <nav aria-label={t("coverage.journey.aria")} className={styles.journey}>
        <ol>
          {model.journey.map((step, index) => (
            <li className={styles[step.state.toLowerCase()]} key={step.id}>
              <span aria-hidden="true" className={styles.stepNumber}>
                {index + 1}
              </span>
              <div>
                {step.href ? (
                  <a href={step.href}>{t(journeyCopy[step.id].label)}</a>
                ) : (
                  <span aria-disabled="true">{t(journeyCopy[step.id].label)}</span>
                )}
                <small>{t(journeyCopy[step.id].detail)}</small>
              </div>
            </li>
          ))}
        </ol>
      </nav>

      <div className={styles.rateGrid}>
        {model.rates.map((rate) => (
          <article key={rate.id}>
            <p>{t(rateCopy[rate.id].label)}</p>
            <strong>{rate.displayValue}</strong>
            <small>{t(rateCopy[rate.id].detail)}</small>
            <code>{rate.status}</code>
          </article>
        ))}
      </div>

      <div className={styles.twoColumns}>
        <section aria-labelledby="coverage-levels-title" className={styles.panel}>
          <h3 id="coverage-levels-title">{t("coverage.levels.title")}</h3>
          <ol className={styles.levels}>
            {model.levels.map((level) => (
              <li key={level.id}>
                <span>{level.id}</span>
                <div>
                  <strong>{level.result}</strong>
                  <small>
                    {level.scope} · {level.controlStatus}
                  </small>
                </div>
              </li>
            ))}
          </ol>
          <p className={styles.boundary}>{t("coverage.levels.boundary")}</p>
        </section>

        <section
          aria-labelledby="calendar-gates-title"
          className={styles.panel}
          id="gates-calendar-fatigue"
        >
          <h3 id="calendar-gates-title">{t("coverage.gates.title")}</h3>
          <p>{t("coverage.gates.intro")}</p>
          <ul className={styles.gates}>
            {model.gates.map((gate) => (
              <li key={gate.id}>
                <code>{gate.id}</code>
                <span>{gateReason(gate.status)}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section aria-labelledby="coverage-p0-table-title" className={styles.panel}>
        <div className={styles.sectionIntro}>
          <div>
            <h3 id="coverage-p0-table-title">{t("coverage.family.title")}</h3>
            <p>{t("coverage.family.intro")}</p>
          </div>
          <span className={styles.scope}>P0_2020_2025</span>
        </div>
        <div
          aria-label={t("coverage.table.region")}
          className={styles.tableWrap}
          id="coverage-p0-table"
          role="region"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th scope="col">{t("coverage.table.family")}</th>
                <th scope="col">{t("coverage.table.expected")}</th>
                <th scope="col">{t("coverage.table.closed")}</th>
                <th scope="col">{t("coverage.table.received")}</th>
                <th scope="col">{t("coverage.table.source")}</th>
                <th scope="col">{t("coverage.table.temporality")}</th>
                <th scope="col">{t("coverage.table.gate")}</th>
              </tr>
            </thead>
            <tbody>
              {model.families.map((family) => (
                <tr key={family.family}>
                  <th scope="row">
                    <code>{family.family}</code>
                  </th>
                  <td data-label={t("coverage.table.expected")}>{family.expectedCells}</td>
                  <td data-label={t("coverage.table.closed")}>{family.closedCells}</td>
                  <td data-label={t("coverage.table.received")}>
                    {t("coverage.table.unmeasured")}
                  </td>
                  <td data-label={t("coverage.table.source")}>
                    {t("coverage.table.sanitized")}
                  </td>
                  <td data-label={t("coverage.table.temporality")}>
                    {family.temporalClasses.join(" · ")}
                  </td>
                  <td data-label={t("coverage.table.gate")}>
                    {t("coverage.table.blocked")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className={styles.twoColumns}>
        <section aria-labelledby="coverage-lineage-title" className={styles.panel}>
          <h3 id="coverage-lineage-title">{t("coverage.evidence.title")}</h3>
          <dl className={styles.evidence}>
            <div>
              <dt>{t("coverage.evidence.source.label")}</dt>
              <dd>{t("coverage.evidence.source.value")}</dd>
            </div>
            <div>
              <dt>{t("coverage.evidence.temporality.label")}</dt>
              <dd>{t("coverage.evidence.temporality.value")}</dd>
            </div>
            <div>
              <dt>{t("coverage.evidence.correction.label")}</dt>
              <dd>{t("coverage.evidence.correction.value")}</dd>
            </div>
            <div>
              <dt>{t("coverage.evidence.effects.label")}</dt>
              <dd>{t("coverage.evidence.effects.value", model.evidence)}</dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="coverage-trust-title" className={styles.panel}>
          <h3 id="coverage-trust-title">{t("coverage.trust.title")}</h3>
          <div className={styles.trust}>
            {model.trust.map((item) => (
              <details key={item.question}>
                <summary>{t(trustCopy[item.id].question)}</summary>
                <p>{t(trustCopy[item.id].answer)}</p>
              </details>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
