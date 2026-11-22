"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { formatDateTime } from "../../i18n";
import { parseQualificationSnapshot, qualificationCount, type QualificationSnapshot } from "../../lib/tipster-qualification";

const labels = { no_eligible: "Lecture terminée, aucun candidat admissible", technical_failure: "Contrôle technique interrompu",
  missing_evidence: "Preuve nécessaire manquante" };
const dateLabels = { observation: "Observé", documentary_record: "Rapport documentaire enregistré", technical_close: "Contrôle clos" };

export function TipsterQualification() {
  const [snapshot, setSnapshot] = useState<QualificationSnapshot | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(true);
  const active = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    const timer = setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await fetch("/api/tipsters/qualification", { cache: "no-store", signal: controller.signal });
      const body = await response.json();
      const { status, ...value } = body;
      if (!response.ok || status !== "ok") throw new Error("Unavailable");
      const result = parseQualificationSnapshot(value);
      if (!controller.signal.aborted) { setSnapshot(result); setError(""); }
    } catch {
      if (active.current === controller) setError("Les qualifications récentes sont indisponibles. La dernière vue conserve sa date.");
    } finally {
      clearTimeout(timer);
      if (active.current === controller) { active.current = null; setPending(false); }
    }
  }, []);
  useEffect(() => {
    const start = window.setTimeout(() => void refresh(), 0);
    return () => { clearTimeout(start); active.current?.abort(); active.current = null; };
  }, [refresh]);

  return <section className="section-card" aria-labelledby="recent-source-qualification">
    <h2 id="recent-source-qualification">Qualifications récentes des sources</h2>
    <p>Contrôles ponctuels et ciblés. Ce suivi couvre une partie des sources du classeur ; les collectes actives restent indiquées dans le suivi récurrent.</p>
    <button className="pilot-button" type="button" onClick={() => { setPending(true); void refresh(); }} disabled={pending}>
      {pending ? "Lecture des qualifications…" : "Actualiser les qualifications"}</button>
    {error && <p role="alert">{error}</p>}
    {!snapshot && !error && <p role="status">Lecture des résultats locaux…</p>}
    {snapshot && <>
      <p>Vue préparée le {formatDateTime(snapshot.capturedAt, true)} · Paris. L’actualisation lit les preuves locales.</p>
      {snapshot.results.length === 0 ? <p>Aucun contrôle documenté dans cette vue.</p> :
        <div className="table-scroll" role="region" aria-label="Qualifications récentes des sources" tabIndex={0}>
          <table className="qualification-results"><caption>Résultats mesurés de chaque contrôle ciblé</caption>
            <thead><tr><th scope="col">Source et date</th><th scope="col">Résultat et périmètre</th>
              <th scope="col">Candidats admissibles au contrôle</th><th scope="col">Ajoutés à Robin</th><th scope="col">Suite</th></tr></thead>
            <tbody>{snapshot.results.map((row) => <tr key={row.id}>
              <th scope="row">{row.label}<small>{dateLabels[row.dateKind]}
                {" le "}{formatDateTime(row.checkedAt, true)} · Paris</small></th>
              <td><strong>{labels[row.outcome]}</strong><p>{row.summary}</p><small>{row.scope}</small>
                <details><summary>Détail du contrôle et références</summary>
                  <p>Requêtes réservées : {qualificationCount(row.metrics.requests)}. Éléments natifs : {qualificationCount(row.metrics.nativeRecords)}.
                    Éléments de football : {qualificationCount(row.metrics.footballRecords)}.</p>
                  <p>Une valeur « Non mesuré » reste inconnue. Les éléments natifs ne sont pas tous des pronostics admissibles.</p>
                  <ul>{row.claims.map((claim) => <li key={claim}><code>{claim}</code></li>)}</ul>
                </details>
              </td><td data-label="Candidats admissibles au contrôle">{qualificationCount(row.metrics.candidates)}</td>
              <td data-label="Ajoutés à Robin">{qualificationCount(row.metrics.admitted)}</td><td data-label="Suite">{row.nextStep}</td>
            </tr>)}</tbody>
          </table>
        </div>}
    </>}
  </section>;
}
