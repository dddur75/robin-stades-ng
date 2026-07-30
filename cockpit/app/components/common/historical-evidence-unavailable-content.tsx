import Link from "next/link";

import { ExpertOnly } from "./view-mode";

export function HistoricalEvidenceUnavailableContent({
  className,
  code,
  retryHref,
}: {
  className: string;
  code: string;
  retryHref: string;
}) {
  return (
    <section
      aria-labelledby="historical-evidence-unavailable-title"
      className={className}
      role="alert"
    >
      <div>
        <span aria-hidden="true">!</span>
        <h1 id="historical-evidence-unavailable-title">
          Preuve historique indisponible
        </h1>
        <p>
          Cette preuve historique ne peut pas être chargée pour le moment.
          Robin ferme cette vue plutôt que d’afficher une donnée incomplète ou
          incohérente. Aucun score, aucune cote et aucun lien ne sont inventés.
        </p>
        <ExpertOnly>
          <code>{code}</code>
        </ExpertOnly>
        <Link href={retryHref}>Réessayer depuis cette page</Link>
      </div>
    </section>
  );
}
