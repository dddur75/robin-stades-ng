import {TipsterCandidates} from "../../components/expert/tipster-candidates";
import { TipsterSources } from "../../components/expert/tipster-sources";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export default function TipsterSourcesRoute() {
  return <ExperienceShell active="tipster-sources"><TipsterCandidates compact /><TipsterSources /></ExperienceShell>;
}
