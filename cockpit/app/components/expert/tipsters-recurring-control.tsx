"use client";
import { useEffect, useState } from "react";
import { formatDateTime } from "../../i18n";
import { InlineLink, SectionHeading } from "../common/ui";

type Campaign = { state: string; authorizationText?: string; startsAt?: string; expiresAt?: string;
  slots?: number; requestsMax?: number; intervalMinutes?: number; planSha256?: string; manifestSha256?: string; personalCollectionProven?: boolean };
type State = { status: string; distinctPicks: number; requestCount: number; technicalVerdict: string;
  qualificationVerdict?: string;
  generatedAt: string; lastObservationAt: string | null; campaign: Campaign; tipsters: unknown[]; unresolvedAttributions?: number; transportVerdict?: string; halted?: boolean };

export function TipstersRecurringControl({ compact = false }: { compact?: boolean }) {
  const [data, setData] = useState<State | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let alive = true; let pending = false;
    async function read() {
      if (pending) return; pending = true;
      try {
        const response = await fetch("/api/tipsters/recurring", {cache:"no-store",signal:AbortSignal.timeout(10_000)});
        const value = await response.json();
        if (!response.ok || value.status !== "ok") throw new Error("unavailable");
        if (alive) { setData(value); setError(""); }
      } catch { if (alive) setError("Le suivi récurrent local est indisponible. La dernière vue conserve sa date."); }
      finally { pending = false; }
    }
    void read(); const timer = setInterval(() => void read(), 15_000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  async function copy() {
    try { await navigator.clipboard.writeText(data?.campaign.authorizationText ?? ""); setNotice("Texte d’autorisation copié."); }
    catch { setNotice("Sélectionnez le texte d’autorisation affiché pour le copier."); }
  }
  return <section className="section-card">
    <SectionHeading title="Collecte récurrente des pronostics" />
    {error && <p role="alert">{error}</p>}
    {data ? <>
      {data.halted && <p role="alert">Campagne arrêtée par un contrôle de sécurité. Aucune nouvelle requête ne sera exécutée par cette campagne. Consultez le bilan JSON avant toute nouvelle autorisation.</p>}
      <p><strong>{data.distinctPicks} pronostic(s) personnel(s) qualifié(s) observé(s) avant match</strong> · {data.tipsters.length} attribution(s) · {data.requestCount} requête(s) réservée(s).</p>
      {!!data.unresolvedAttributions && <p>{data.unresolvedAttributions} sélection(s) historique(s) exclue(s) du compteur individuel : auteur collectif ou rôle personnel non prouvé. Les observations d’origine sont conservées.</p>}
      <p>Dernière lecture : {data.lastObservationAt ? formatDateTime(data.lastObservationAt, true) : "Aucune"}. Vue du {formatDateTime(data.generatedAt, true)}.</p>
      <p>Recette du canari : {(data.qualificationVerdict ?? data.technicalVerdict) === "PASS_AND_HOLD" ? "Deux créneaux validés" : (data.qualificationVerdict ?? data.technicalVerdict) === "PENDING" ? "En cours, bilan non clos" : "Partielle"}.</p>
      {data.transportVerdict === "PASS_AND_HOLD" && data.distinctPicks === 0 && <p>Les deux créneaux réseau ont fonctionné. Aucun pronostic personnel admissible n’est encore prouvé.</p>}
      <nav className="pilot-actions"><InlineLink href="/expert/collecte-recurrente">Suivre les créneaux récurrents</InlineLink>
        <InlineLink href="/expert/collecte-recurrente?view=tipsters">Consulter les pronostics et les fiches</InlineLink></nav>
      {!compact && <>
        <h3>Activation de la campagne</h3>
        <p>{data.campaign.state === "authorized" ? "Autorisation enregistrée. Les lectures effectives restent attestées par le journal des créneaux." : data.campaign.state === "awaiting_authorization" ? "Campagne prête, en attente de votre autorisation. Aucune tâche récurrente n’est activée par cette préparation." : data.campaign.state === "invalid_package" ? "Paquet invalide ou code modifié : activation refusée, nouvelle préparation nécessaire." : data.campaign.state === "expired" ? "Campagne expirée : aucune nouvelle collecte autorisée." : "Le paquet de campagne est en préparation."}</p>
        {data.campaign.personalCollectionProven === false && <p>Cette autorisation ouvre des lectures de qualification. Elle ne garantit pas la présence de pronostics personnels : les signatures d’articles et les choix collectifs restent exclus.</p>}
        {data.campaign.startsAt && <p>{formatDateTime(data.campaign.startsAt,true)} au {formatDateTime(data.campaign.expiresAt!,true)} · toutes les {data.campaign.intervalMinutes} minutes · {data.campaign.slots} créneaux · {data.campaign.requestsMax} GET maximum.</p>}
        {data.campaign.authorizationText && <>
          <blockquote>{data.campaign.authorizationText}</blockquote>
          <button className="pilot-button" type="button" onClick={() => void copy()} disabled={!!error}>Copier l’autorisation précise</button>
          <p role="status">{notice}</p>
          <details><summary>Empreintes du paquet à autoriser</summary><p style={{overflowWrap:"anywhere"}}>Plan {data.campaign.planSha256}<br />Manifeste {data.campaign.manifestSha256}</p></details>
        </>}
        <p>Aucun achat, aucune API-Football, aucune requête aux documents originaux. Les pronostics proviennent de mesures attribuées par Forecast Record. L’identité humaine n’est pas certifiée. Le pilote J12 conserve ses 51 requêtes distinctes.</p>
      </>}
    </> : !error && <p role="status">Lecture des preuves de récurrence…</p>}
  </section>;
}
