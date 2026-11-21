import {TipsterCandidates} from "../../components/expert/tipster-candidates";
import {PageHeader} from "../../components/common/ui";
import {ExperienceShell} from "../../components/navigation/experience-shell";
export default function CandidateCatalogue(){return <ExperienceShell active="tipster-sources"><PageHeader eyebrow="Dossier fidèle" title="Catalogue Ligue 1" subtitle="Fiches historiques importées, en attente de qualification."/><TipsterCandidates /></ExperienceShell>;}
