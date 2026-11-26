import {WorkbookCatalogue} from '../../components/expert/workbook-catalogue';
import {PageHeader} from '../../components/common/ui';
import {ExperienceShell} from '../../components/navigation/experience-shell';
export default function CompleteCatalogue(){return <ExperienceShell active="tipster-sources"><PageHeader eyebrow="Dossier fidèle" title="Catalogue complet des sources" subtitle="Tous les onglets du classeur, avec leur provenance et leurs états de collecte."/><WorkbookCatalogue/></ExperienceShell>;}
