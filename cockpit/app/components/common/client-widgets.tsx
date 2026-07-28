"use client";

import { useEffect, useMemo, useState } from "react";

import { t } from "../../i18n";
import { operationalEvidence } from "../../lib/presentation";

const visitKey = "robin-experience-last-visit";
const countersKey = "robin-experience-last-counters";

export function SinceLastVisit() {
  const [message, setMessage] = useState(t("home.visit.first"));

  useEffect(() => {
    let nextMessage = t("home.visit.first");
    const previousVisit = window.localStorage.getItem(visitKey);
    const previousCounters = window.localStorage.getItem(countersKey);
    if (previousVisit && previousCounters) {
      try {
        const counters = JSON.parse(previousCounters) as {
          fixtures: number;
          captures: number;
          incidents: number;
        };
        const fixtureDelta = Math.max(0, operationalEvidence.fixtures - counters.fixtures);
        const captureDelta = Math.max(0, operationalEvidence.physicalEvidence - counters.captures);
        const incidentDelta = Math.max(0, operationalEvidence.errors - counters.incidents);
        nextMessage =
          fixtureDelta + captureDelta + incidentDelta === 0
            ? t("home.visit.none")
            : `${fixtureDelta} ${t("home.visit.fixtures")} · ${captureDelta} ${t("home.visit.captures")} · ${incidentDelta} ${t("home.visit.incidents")}`;
      } catch {
        nextMessage = t("home.visit.first");
      }
    }
    const timer = window.setTimeout(() => setMessage(nextMessage), 0);
    window.localStorage.setItem(visitKey, new Date().toISOString());
    window.localStorage.setItem(
      countersKey,
      JSON.stringify({
        fixtures: operationalEvidence.fixtures,
        captures: operationalEvidence.physicalEvidence,
        incidents: operationalEvidence.errors,
      }),
    );
    return () => window.clearTimeout(timer);
  }, []);

  return <p>{message}</p>;
}

function durationParts(milliseconds: number) {
  if (milliseconds <= 0) return "capture disponible";
  const totalMinutes = Math.floor(milliseconds / 60_000);
  const days = Math.floor(totalMinutes / 1_440);
  const hours = Math.floor((totalMinutes % 1_440) / 60);
  const minutes = totalMinutes % 60;
  return `${days} j ${hours} h ${minutes} min`;
}

export function Countdown({ target }: { target: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const duration = useMemo(
    () => durationParts(new Date(target).getTime() - now),
    [now, target],
  );
  return <span aria-live="polite">{duration}</span>;
}
