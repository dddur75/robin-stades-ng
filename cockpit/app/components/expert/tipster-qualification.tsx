"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { formatDateTime } from "../../i18n";
import { parseQualificationSnapshot, qualificationAnchorTarget, qualificationAdminHref, qualificationCount, qualificationResults, type QualificationSnapshot } from "../../lib/tipster-qualification";

const labels = { no_eligible: "Aucun pronostic admissible confirmé", technical_failure: "Contrôle technique interrompu",
  missing_evidence: "Preuve nécessaire manquante", qualified: "Lot qualifié" };
const dateLabels = { observation: "Observé", documentary_record: "Rapport documentaire enregistré", technical_close: "Contrôle clos" };

export function TipsterQualification({ resultIds, platformContext = false }: { resultIds?: readonly string[]; platformContext?: boolean } = {}) {
  const instanceId = useId();
  const Heading = platformContext ? "h3" : "h2";
  const headingId = platformContext ? "platform-source-qualification-" + instanceId : "recent-source-qualification";
  const [snapshot, setSnapshot] = useState<QualificationSnapshot | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(true);
  const active = useRef<AbortController | null>(null);
  const lastAnchor = useRef<string | null>(null);
  const refresh = useCallback(async () => {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    const timer = setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await fetch("/api/tipsters/qualification", { cache: "no-store", signal: controller.signal });
      const body = await response.json();
      const { status } = body;
      // The API envelope carries archive provenance outside the strict display snapshot.
      const value = { schemaVersion: body.schemaVersion, capturedAt: body.capturedAt, coverage: body.coverage,
        results: Array.isArray(body.results) ? body.results.map((row: Record<string, unknown>) => ({ ...row,
          outcome: row.outcome === "partial" ? "missing_evidence" : row.outcome,
          checkedAt: typeof row.checkedAt === "string" ? row.checkedAt.replace(/(\.\d{6})\d+(Z|\+00:00)$/, "$1$2") : row.checkedAt,
        })) : body.results };
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


  useEffect(() => {
    if (platformContext || !snapshot) return;
    const scrollToKnownRow = () => {
      const targetId = qualificationAnchorTarget(window.location.hash, snapshot.results);
      if (!targetId || lastAnchor.current === targetId) return;
      const target = document.getElementById(targetId);
      if (target) { target.scrollIntoView({ block: "center" }); lastAnchor.current = targetId; }
    };
    const onHashChange = () => { lastAnchor.current = null; scrollToKnownRow(); };
    const frame = window.requestAnimationFrame(scrollToKnownRow);
    window.addEventListener("hashchange", onHashChange);
    return () => { window.cancelAnimationFrame(frame); window.removeEventListener("hashchange", onHashChange); };
  }, [platformContext, snapshot]);

  const results = snapshot ? qualificationResults(snapshot, resultIds) : [];
  return <section className="section-card" aria-labelledby={headingId}>
    <Heading id={headingId}>{platformContext ? "Contrôles récents de la plateforme" : "Qualifications récentes des sources"}</Heading>
    {platformContext ? <p>Ces contrôles portent sur la plateforme. Ils ne constituent pas une preuve individuelle pour cette fiche ; sa qualification et ses choix restent affichés séparément.</p> :
      <p>Contrôles ponctuels et ciblés. Ce suivi couvre une partie des sources du classeur ; les collectes actives restent indiquées dans le suivi récurrent.</p>}
    <button className="pilot-button" type="button" onClick={() => { setPending(true); void refresh(); }} disabled={pending}>
      {pending ? "Lecture des qualifications…" : "Actualiser les qualifications"}</button>
    {error && <p role="alert">{error}</p>}
    {!snapshot && !error && <p role="status">Lecture des résultats locaux…</p>}
    {snapshot && <>
      <p>Vue préparée le {formatDateTime(snapshot.capturedAt, true)} · Paris. L’actualisation lit les preuves locales.</p>
      {results.length === 0 ? <p>{platformContext ? "Aucun contrôle de plateforme documenté pour ce contexte." : "Aucun contrôle documenté dans cette vue."}</p> :
        <div className="table-scroll" role="region" aria-label={platformContext ? "Contrôles récents de la plateforme" : "Qualifications récentes des sources"} tabIndex={0}>
          <table className="qualification-results"><caption>{platformContext ? "Résultats du contrôle de plateforme ; ces totaux ne qualifient pas cette fiche." : "Résultats mesurés de chaque contrôle ciblé"}</caption>
            <thead><tr><th scope="col">Source et date</th><th scope="col">Résultat et périmètre</th>
              <th scope="col">Candidats admissibles au contrôle</th><th scope="col">Ajoutés à Robin</th><th scope="col">Suite</th></tr></thead>
            <tbody>{results.map((row) => <tr key={row.id} id={platformContext ? headingId + "-" + row.id : "qualification-" + row.id}>
              <th scope="row">{row.label}<small>{dateLabels[row.dateKind]}
                {" le "}{formatDateTime(row.checkedAt, true)} · Paris</small></th>
              <td><strong>{labels[row.outcome]}</strong><p>{row.summary}</p><small>{row.scope}</small>
                {platformContext && <p><a className="inline-link" href={qualificationAdminHref(row.id)}>Voir ce contrôle dans le suivi admin</a></p>}
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
