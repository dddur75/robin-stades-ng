import { formatNumber, t } from "../../i18n";
import {
  dataFamilyLabels,
  hypotheses,
} from "../../lib/presentation";
import {
  EvidenceNote,
  PageHeader,
  ProgressBar,
  StatusBadge,
} from "../common/ui";
import { ExpertOnly } from "../common/view-mode";

const researchStages = [
  t("laboratory.stage.idea"),
  t("laboratory.stage.collecting"),
  t("laboratory.stage.eligible"),
  t("laboratory.stage.history"),
  t("laboratory.stage.prospective"),
  t("laboratory.stage.shadow"),
];

export function LaboratoryPage() {
  return (
    <>
      <PageHeader
        eyebrow={t("laboratory.eyebrow")}
        subtitle={t("laboratory.subtitle")}
        title={t("laboratory.title")}
      />

      <EvidenceNote>
        Une hypothèse décrit une question et un mécanisme possible. Elle ne devient
        jamais un conseil de mise et peut rester en attente ou être rejetée.
      </EvidenceNote>

      <section className="hypothesis-grid">
        {hypotheses.map((hypothesis) => (
          <article className="hypothesis-card" key={hypothesis.id}>
            <div className="hypothesis-card-head">
              <span>{hypothesis.id}</span>
              <StatusBadge value={hypothesis.status} />
            </div>
            <p className="eyebrow">{t("laboratory.question")}</p>
            <h2>{hypothesis.title}</h2>
            <div className="mechanism">
              <span aria-hidden="true">◇</span>
              <div><strong>{t("laboratory.mechanism")}</strong><p>{hypothesis.mechanism}</p></div>
            </div>
            <div className="hypothesis-data">
              <span>{t("laboratory.required")}</span>
              <div className="family-chips">
                {hypothesis.requiredData.map((family) => (
                  <span key={family}>{dataFamilyLabels[family] ?? family}</span>
                ))}
              </div>
            </div>
            <ProgressBar
              label={`${t("laboratory.accumulated")} · ${formatNumber(hypothesis.observations)} / ${formatNumber(hypothesis.minimumSupport)}`}
              value={hypothesis.coverage}
            />
            <div className="research-journey" aria-label="Étapes de recherche">
              {researchStages.map((stage, index) => (
                <span className={index === 0 ? "done" : index === 1 ? "current" : ""} key={stage}>
                  <i>{index === 0 ? "✓" : index + 1}</i>
                  <small>{stage}</small>
                </span>
              ))}
            </div>
            <div className="blocked-reason">
              <strong>{t("laboratory.blocked")}</strong>
              <p>Aucune observation profonde n’est encore disponible. Le minimum requis est conservé sans être assoupli.</p>
            </div>
            <ExpertOnly>
              <div className="technical-strip">
                <code>frozen={String(hypothesis.frozen)}</code>
                <code>minimum_support={hypothesis.minimumSupport}</code>
                <code>{hypothesis.status}</code>
              </div>
            </ExpertOnly>
          </article>
        ))}
      </section>
    </>
  );
}
