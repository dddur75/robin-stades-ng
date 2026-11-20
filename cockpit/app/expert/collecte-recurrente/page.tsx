import { TipstersPilot } from "../../components/expert/tipsters-pilot";
import { TipstersRecurringControl } from "../../components/expert/tipsters-recurring-control";
import { ExperienceShell } from "../../components/navigation/experience-shell";
import { PublicTipsters } from '../../components/expert/public-tipsters';
import { PageHeader } from '../../components/common/ui';

export default async function RecurringRoute({ searchParams }: {searchParams: Promise<{view?: string}>}) {
  const {view} = await searchParams;
  return <ExperienceShell active="collection-admin">
    <PageHeader eyebrow="Dossier fidèle · Ligue 1" title="Collecte récurrente" subtitle="Campagnes publiques sur A9_Mega : programmation, lectures attestées et pronostics collectés." />
    <PublicTipsters compact />
    <section aria-labelledby="forecast-history">
      <h2 id="forecast-history">Historique Forecast Record</h2>
      <p>Cette campagne possède son propre journal et son propre plafond. Le pilote J12 reste distinct.</p>
      <TipstersPilot embedded endpoint="/api/tipsters/recurring" admin={view !== "tipsters"}>
        <TipstersRecurringControl />
      </TipstersPilot>
    </section>
  </ExperienceShell>;
}
