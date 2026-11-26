import {TipsterCandidates} from "../../../components/expert/tipster-candidates";
import { PublicTipsters } from "../../../components/expert/public-tipsters";
import { TipstersPilot } from "../../../components/expert/tipsters-pilot";
import { TipsterConnectors } from "../../../components/expert/tipster-connectors";
import { PageHeader } from "../../../components/common/ui";
import { ExperienceShell } from "../../../components/navigation/experience-shell";

export default async function TipsterRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const forum=/^forum:[a-f0-9]{64}$/.test(id);
  if (/^kicktipp:contest-season-name:[a-f0-9]{64}$/.test(id)) return <ExperienceShell active="tipsters"><PageHeader eyebrow="Dossier fidèle" title="Participant Kicktipp" subtitle="Pronostics attribués au nom publié dans ce concours et cette saison."/><TipsterCandidates tipsterId={id} /></ExperienceShell>;
  if (/^catalogue:[a-f0-9]{64}$/.test(id)) return <ExperienceShell active="tipsters"><PageHeader eyebrow="Dossier fidèle" title="Fiche tipster" subtitle="Qualification et provenance des observations."/><TipsterCandidates tipsterId={id} /></ExperienceShell>;
  if (/^public:[a-f0-9]{64}$/.test(id)||/^olbg:[1-9][0-9]{0,11}$/.test(id)||forum) return <ExperienceShell active="tipsters"><PageHeader eyebrow="Dossier fidèle" title="Fiche tipster" subtitle="Choix attribués à un pseudonyme public." /><PublicTipsters tipsterId={forum?id.slice(6):id} /></ExperienceShell>;
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
