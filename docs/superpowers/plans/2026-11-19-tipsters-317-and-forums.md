# Intégration317etactivationforums Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. C0 seul rédacteur; revues en lecture seule.

**Goal:** Enregistrer la campagne strictement autorisée et rendre les317candidats consultables sans les qualifier implicitement.
**Architecture:** Paquet d’exécution72GET inchangé, registre compagnon local hashé, API de lecture, annuaire et suivi.
**Tech Stack:** Python, React/TypeScript, Vite, Planificateur Windows.
**Spec:** docs/superpowers/specs/2026-11-19-tipsters-317-and-forums-design.md

## Contraintes
Aucun changement des9pins, du CSVgelé, de ForecastDisabled ou du piloteJ12. Aucun GET fournisseur pour importer ou vérifier l’interface. Les317candidats restent désactivés. Données locales uniquement.

## Revue
Refuser les booléens chaînes, les URLs de session et les hashes modifiés. Ne pas mélanger profils et pronostics. Préserver les24faits avant le premier créneau. Montrer attente, arrêt, indisponibilité et expiration honnêtement. Ne jamais affirmer une exécution future à partir de Ready.

## Tâches
- [x] Lier message propriétaire, plan et manifeste; enregistrer12triggers; lire état natif sans GET.
- [x] Tester puis créer source_observatory/candidate_registry.py et scripts/import-tipster-candidates.py.
- [x] Ajouter API locale et vue catalogue/fiches; lier Sources/Tipsters/Admin.
- [x] Raccorder suivi natif des forums et historique; tests ciblés et recette navigateur.
- [ ] Réunir C1/C4/C3/UX6/A3, ledger et graphe; commit et CI PR133 jusqu’au résultat.
