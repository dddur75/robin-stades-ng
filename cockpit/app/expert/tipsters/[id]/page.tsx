import { PublicTipsters } from "../../../components/expert/public-tipsters";
import { TipstersPilot } from "../../../components/expert/tipsters-pilot";
import { TipsterConnectors } from "../../../components/expert/tipster-connectors";
import { PageHeader } from "../../../components/common/ui";
import { ExperienceShell } from "../../../components/navigation/experience-shell";

export default async function TipsterRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (/^public:[a-f0-9]{64}$/.test(id)) return <ExperienceShell active="tipsters"><PageHeader eyebrow="Dossier fidèle" title="Fiche tipster" subtitle="Choix attribués à un pseudonyme public." /><PublicTipsters tipsterId={id} /></ExperienceShell>;
  if (/^forecaster:[a-f0-9]{64}$/.test(id)) return <ExperienceShell active="tipsters">
    <TipstersPilot endpoint="/api/tipsters/recurring" tipsterId={id} />
  </ExperienceShell>;
  if (/^author:[a-f0-9]{64}$/.test(id)) return <ExperienceShell active="tipsters">
    <PageHeader eyebrow="Dossier fidèle · Attribution de source" title="Fiche d’attribution"
      subtitle="Publications observées et identité à vérifier." />
    <TipsterConnectors authorId={id} />
  </ExperienceShell>;
  return <ExperienceShell active="tipsters"><TipstersPilot tipsterId={id} /></ExperienceShell>;
}
