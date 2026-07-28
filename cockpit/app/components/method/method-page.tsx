import { glossary } from "../../i18n/glossary";
import { t } from "../../i18n";
import { GlossaryTerm } from "../common/glossary-term";
import {
  EvidenceNote,
  PageHeader,
  SectionHeading,
} from "../common/ui";

const methodSteps = [
  { key: "observe", icon: "◉", text: "Collecter seulement ce que les sources publient réellement avant le match." },
  { key: "verify", icon: "✓", text: "Contrôler l’heure, la provenance, la complétude et l’empreinte de chaque preuve." },
  { key: "test", icon: "◇", text: "Évaluer des hypothèses gelées sans choisir les résultats après coup." },
  { key: "publish", icon: "□", text: "Rendre visibles résultats, rejets, limites, pertes et absences de décision." },
  { key: "follow", icon: "↗", text: "Suivre les décisions fictives sans argent réel ni connexion bookmaker." },
] as const;

const sections = [
  {
    key: "observe",
    text: "Robin suit les rencontres, les cotes, les équipes, les joueurs, les absences, les compositions et les formations. Une donnée non observée reste explicitement absente.",
  },
  {
    key: "hypothesis",
    text: "Une hypothèse part d’une question football, décrit un mécanisme possible, fixe ses données nécessaires et son support minimal avant de voir les résultats.",
  },
  {
    key: "history",
    text: "Une régularité passée peut être une coïncidence. Robin sépare découverte, simulation historique, validation externe et test prospectif.",
  },
  {
    key: "noBet",
    text: "NO BET est la décision normale lorsqu’une preuve manque, qu’un test échoue ou que l’incertitude est trop grande.",
  },
  {
    key: "losses",
    text: "Quand la simulation commencera, chaque décision réglée sera publiée, qu’elle soit positive, négative ou annulée.",
  },
  {
    key: "bankroll",
    text: "La bankroll fictive est un compteur en unités, sans valeur monétaire. Elle sert à mesurer une méthode sans engager d’argent.",
  },
] as const;

export function MethodPage() {
  return (
    <>
      <PageHeader
        eyebrow={t("method.eyebrow")}
        subtitle={t("method.subtitle")}
        title={t("method.title")}
      />

      <section className="method-journey" aria-label="Méthode Robin">
        {methodSteps.map((step, index) => (
          <article key={step.key}>
            <span aria-hidden="true">{step.icon}</span>
            <div>
              <small>0{index + 1}</small>
              <h2>{t(`method.steps.${step.key}`)}</h2>
              <p>{step.text}</p>
            </div>
            {index < methodSteps.length - 1 ? <i aria-hidden="true">→</i> : null}
          </article>
        ))}
      </section>

      <section className="method-grid">
        {sections.map((section) => (
          <article key={section.key}>
            <h2>{t(`method.sections.${section.key}`)}</h2>
            <p>{section.text}</p>
          </article>
        ))}
        <article className="not-do-card">
          <h2>{t("method.sections.notDo")}</h2>
          <ul>
            <li>Robin ne promet pas de gain.</li>
            <li>Robin ne connecte aucun bookmaker.</li>
            <li>Robin ne mise pas d’argent réel.</li>
            <li>Robin ne transforme pas une absence de donnée en zéro.</li>
            <li>Robin ne masque pas un résultat défavorable.</li>
          </ul>
        </article>
      </section>

      <EvidenceNote>
        Les performances passées ne garantissent aucun résultat futur. Robin
        reste un projet de recherche et de transparence.
      </EvidenceNote>

      <section className="section-card method-glossary">
        <SectionHeading
          subtitle="Survolez, placez le focus ou touchez un terme souligné pour une définition rapide."
          title="Mots utiles pour lire Robin"
        />
        <p className="term-cloud">
          {glossary.map((entry) => (
            <GlossaryTerm key={entry.term} term={entry.term} />
          ))}
        </p>
      </section>
    </>
  );
}
