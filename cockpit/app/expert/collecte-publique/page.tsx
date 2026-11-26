import { PublicTipsters } from "../../components/expert/public-tipsters";
import { PageHeader } from "../../components/common/ui";
import { ExperienceShell } from "../../components/navigation/experience-shell";
export default function PublicCollectionRoute() {
 return <ExperienceShell active="tipsters"><PageHeader eyebrow="Dossier fidèle" title="Collecte des pronostics personnels" subtitle="Fiches et preuves locales avant match." /><PublicTipsters /></ExperienceShell>;
}
