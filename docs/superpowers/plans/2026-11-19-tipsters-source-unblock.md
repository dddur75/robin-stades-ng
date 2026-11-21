# Déblocage sources tipsters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. C0 est seul rédacteur; les agents de revue ne modifient rien.

**Goal:** Qualifier des pronostics personnels réellement observés avant match et décrire précisément chaque accès manquant.

**Architecture:** Qualification E1 bornée avec cache en mémoire, adaptateurs spécifiques aux posts/articles, preuves structurées et projection locale. Les campagnes arrêtées restent séparées.

**Tech Stack:** Python, transport public épinglé existant, tests synthétiques ciblés, cockpit TypeScript.

**Spec:** docs/superpowers/specs/2026-11-19-tipsters-source-unblock-design.md

## Global Constraints

36 GET maximum, six par source, six recherches publiques maximum. Aucun achat, API-Football, contournement, média téléchargé ou corps brut archivé. J12 et la campagne arrêtée sont préservés. Ne pas modifier les parseurs gelés.

## Review Focus

- Auteur d’un post opposé à auteur global ou citation : attribution locale seule.
- URL avec session, domaine privé ou redirect : aucune fuite ni suivi implicite.
- Date de publication absente : ne pas inventer; observation strictement avant kickoff.
- Article/listing ou résultats : ne pas compter comme choix individuel.
- Absence de clé ou de droits sur le contenu oral YouTube : métadonnées seules restent insuffisantes.

## Task1 — Qualification publique minimale

- [x] Réserver chaque GET dans la mission, inspecter robots/conditions et les liens précis.
- [x] Trouver un message/article futur sur SCO1919, MightyTips ou Gruppetto; ne pas parcourir un corpus.
- [x] Conserver des faits/structures minimaux en mémoire pour les tests, et des reçus durables sans prose fournisseur.

## Task2 — Adaptateurs et projection

- [x] Écrire des cas synthétiques pour auteur local, citations exclues, sélection, fixture et antériorité.
- [x] Construire le plus petit adaptateur spécifique dans src/robin/source_observatory, sans toucher aux fichiers gelés.
- [x] Valider le parseur hors réseau sur les corps déjà acquis en mémoire; qualifier une observation courante si prouvée.
- [x] Raccorder les faits qualifiés aux fiches et à l’admin; états bloqués explicites.

## Task3 — Accès réellement nécessaires

- [x] Corriger les URL canoniques prouvées et vérifier les conditions applicables; conserver les interdictions réelles, sans assouplissement lexical générique non prouvé.
- [x] Préparer la voie officielle YouTube et un essai limité sans contenu oral supposé ni secret en chat.
- [x] Produire la matrice nominative des accès/permissions, la preuve des sources débloquées et le plan concret d’activation restant.

## Task4 — Recette et livraison

- [x] Tests du domaine proportionnés, lint/typage/sécurité, revues C1/C4 et recette UI.
- [x] Enregistrer chaque métrique réelle dans le graphe et chaque décision dans le ledger.
- [ ] Commit et PR133 avec contexte préalable; suivre la CI du commit exact. Rendre PARTIAL si une preuve ou autorité reste absente.

## Recette au commit candidat

35tests nouveaux PASS; domaine701PASS avec un écart CRLF antérieur sur CSV gelé, empreinte LF conforme.15tests interface Chrome PASS et parcours A9 réel24faits/8pseudonymes, ficheBrandon9/1, mobile et journal inchangé. TraceARIA disponible; lecteur écran physique non recetté, zoomCSS seulement. ClésC1/C3/UX6/A3 accordées au lot local privé; aucunREADYglobal. CI exacte à suivre après pushautoriséPR133.

Ruling: anciennequalification22GET close; missionjuridique distincte2GET approuvéeC0/C1/C4 pour projection complète, sans contenu ni réinitialisation du budget. SourcesAPIorales et55sourcesrestantes demeurent PARTIAL.
