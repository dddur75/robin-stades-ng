"use client";

import Link from "next/link";

import snapshot from "../cockpit-data.json";
import { RobinLive } from "../page";

export default function RobinLivePage() {
  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">R</div>
          <div>
            <strong>Robin</strong>
            <span>Live V1</span>
          </div>
        </div>
        <div className="mode">
          <span className="pulse" />
          Shadow public
          <small>preuve statique · aucune mise réelle</small>
        </div>
        <nav aria-label="Navigation Robin Live">
          <Link href="/">← Retour au Cockpit</Link>
        </nav>
        <div className="sidebar-foot">
          <span>Système</span>
          <strong>{snapshot.patternResearch.productionStatus}</strong>
          <small>SOCIAL_PUBLISHING_ENABLED=false</small>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="mobile-brand"><span>R</span> Robin Live V1</div>
          <div className="system-state">
            <span className="pulse" />
            {snapshot.patternResearch.dataStatus.replaceAll("_", " ")}
          </div>
          <div className="top-actions">
            <Link href="/">Cockpit complet</Link>
          </div>
        </header>
        <div className="content">
          <div className="page-head">
            <div>
              <span className="eyebrow">Preuve publique · shadow uniquement</span>
              <h1>Robin Live V1</h1>
              <p>Résultats complets, rejets scientifiques et limites visibles.</p>
            </div>
            <div className="lock">
              <span>●</span>
              <div>
                <strong>{snapshot.patternResearch.productionStatus}</strong>
                <small>REAL_BETS=false · aucun réseau social</small>
              </div>
            </div>
          </div>
          <RobinLive />
        </div>
      </section>
    </main>
  );
}
