# Qualification317 Implementation Plan

> **For agentic workers:** superpowers:executing-plans ; C0 rédacteur unique, autres agents en lecture seule.

**Goal:** Qualifier chaque fiche à hauteur des preuves et collecter les choix personnels réellement accessibles avant match.
**Architecture:** Registre importé immuable + compagnon de qualification ; transport borné indépendant ; projection de lecture dans l'application. Collecteur de nouvelle source uniquement après preuve applicable.
**Tech Stack:** Python, React/TypeScript, Vite et tâches Windows existantes ou compagnon explicitement borné.
**Spec:** docs/superpowers/specs/2026-11-19-candidates317-qualification-design.md

## Contraintes et contre-tests
Neuf pins Forums intouchables ; aucun corpus rejoué ni API-Football. Dates historiques, identité ambiguë, autre ligue, classement et source refusée doivent rester exclus. Un compagnon corrompu ne cache pas les données documentaires ou les 24 observations préexistantes. L'absence de preuve n'active jamais une fiche.

- [x] Comparer les 317 lignes, 19 plateformes et provenance ; nommer C0/C1/C4.
- [x] Formaliser E1, tester les gardes et obtenir clés avant robots19.
- [x] Qualifier robots, vraies CGU et accès ; réserver puis journaliser chaque effet ; conserver les corps en RAM.
- [x] Tester puis construire le compagnon et ses états par fiche, lier Catalogue/Admin, préserver les preuves existantes.
- [x] Pour source admissible : test d'attribution et chronologie, canari réel, revue C1/C4 puis activation bornée séparée si justifiée.
- [ ] Contre-revue, tests du domaine et navigateur pertinents, ledger/graphe, livraison avec liste précise des accès ou défauts restants ; CI exacte jusqu'au résultat.

Recette locale accomplie ; la CI exacte reste à suivre après push. Sa clôture sera conservée dans le reçu privé et la PR pour éviter un commit documentaire déclenchant une seconde suite complète. Bilan applicatif global PARTIAL (313 preuves individuelles absentes).
