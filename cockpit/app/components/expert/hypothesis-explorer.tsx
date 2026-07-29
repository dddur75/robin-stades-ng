import { formatNumber } from "../../i18n";
import preview from "../../universal-genome-preview.json";
import { hypothesisIntelligence } from "../../lib/presentation";
import { StatusBadge } from "../common/ui";

export function HypothesisExplorer() {
  const explorer = hypothesisIntelligence.expertExplorer;

  return (
    <div className="hypothesis-explorer">
      <div className="hypothesis-explorer-summary">
        <strong>{formatNumber(explorer.total)} règles Jalon 10</strong>
        <span>Détails générés pendant le build</span>
        <span>Aucune duplication complète dans Git</span>
      </div>

      <article className="section-card">
        <div className="hypothesis-card-head">
          <strong>Génome universel V2</strong>
          <StatusBadge value="PRODUCTION_LOCKED" />
        </div>
        <h3>{preview.symbolicStatus}</h3>
        <p>{preview.warning}</p>
        <dl className="discovery-metrics">
          <div>
            <dt>Propriétés</dt>
            <dd>{formatNumber(preview.properties)}</dd>
          </div>
          <div>
            <dt>Familles</dt>
            <dd>{formatNumber(preview.families)}</dd>
          </div>
          <div>
            <dt>Relations</dt>
            <dd>{formatNumber(preview.relations)}</dd>
          </div>
          <div>
            <dt>Nœuds matérialisés</dt>
            <dd>{formatNumber(preview.materialized)}</dd>
          </div>
          <div>
            <dt>Nœuds exécutés</dt>
            <dd>{formatNumber(preview.executed)}</dd>
          </div>
          <div>
            <dt>Bloqués par les données</dt>
            <dd>{formatNumber(preview.blocked)}</dd>
          </div>
          <div>
            <dt>Calcul différé</dt>
            <dd>{formatNumber(preview.deferred)}</dd>
          </div>
          <div>
            <dt>Stratégies validées</dt>
            <dd>{formatNumber(preview.validatedStrategies)}</dd>
          </div>
        </dl>
        <details>
          <summary>Contrats et stockage</summary>
          <dl className="technical-list">
            <div>
              <dt>Registre complet</dt>
              <dd>PostgreSQL append-only</dd>
            </div>
            <div>
              <dt>Preuves lourdes</dt>
              <dd>R2</dd>
            </div>
            <div>
              <dt>Pages détaillées</dt>
              <dd>{formatNumber(preview.artifactPages)} pages d’artefact de build</dd>
            </div>
            <div>
              <dt>Git</dt>
              <dd>Code, schémas, index compact, hashes et classements</dd>
            </div>
            <div>
              <dt>Replay</dt>
              <dd>{preview.replayIdentical ? "Identique" : "À vérifier"}</dd>
            </div>
          </dl>
        </details>
      </article>
    </div>
  );
}
