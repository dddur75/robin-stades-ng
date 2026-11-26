# Public Tipsters Technical Implementation Plan

> **For agentic workers:** superpowers:executing-plans ; C0 rédacteur unique, C1/C2/C4 lecture seule.

**Goal:** Terminer les raccords possibles et collecter des pronostics personnels avant match.
**Architecture:** Compagnons propres et bornés ; projections réutilisées ; campagnes existantes figées.
**Tech Stack:** Python, React/TypeScript, Windows Task Scheduler.
**Spec:** docs/superpowers/specs/2026-11-19-public-tipsters-technical-design.md

- [x] Observer checkout, reçus, horloge, magasins CA et routes historiques ; préserver le travail local.
- [x] Tester les probes TLS bornés après clés C4 ; vérifier chaîne et nom avec Mozilla épinglé, sans prétendre une causalité sur l'ancienne IP inconnue.
- [x] Qualifier les routes : OLBG personnel prouvé, NotBetting route de choix non établie, Kicktipp J11 résolue mais choix masqués avant match.
- [x] Tester les parsers sur contre-exemples synthétiques ; observer le chemin réel OLBG puis tester sur le même corps RAM.
- [x] Contre-revue C1/C4 : ancien seed provisoire écarté ; nouveau seed18:34 admis ; E2 distinct36GET autorisé et tâche enregistrée.
- [x] Raccorder fiches/admin ; canari natif18:48UTC réussi3GET/2choix,60faits distincts/13pseudonymes/5fiches actives ;21tests UI et4parcours A9 dont les13profils navigables.
- [ ] Revue indépendante, ledger/graphe, PR133, CI exacte jusqu'au résultat ; livrer le bilan réel.
