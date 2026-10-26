# RUSH-STATUS — Dossier fidèle (méthode DDDUR RUSH)
Mis à jour : 2026-10-26 12:40 — plafond de travail en cours : 4. Routes : voir rush/registre-capacites.json ; graphe : rush/graphe-taches.md.

## Prêts
- C33b annotation des ambigus (Grok texte) — attend C33a
- C33c remesure C3 en aveugle (Codex) — attend C33b
- T7x collecte réelle (30/10) — attend R3 accepté + CI #128
- T8 règlement + rapport — attend T7x

## En cours
- R3 corrections Codex (5 bloquants de la revue ronde 3) — journal : Codex exec, preuve à l'arrivée
- C33a textes ambigus (Gemini via agy)
- CI PR #128 : tous jobs verts sauf « Quality and domain tests » en attente

## En revue
- PR #128 (Gemini ronde 3 = REFUSE, 5 bloquants chaîne pilote + 1 majeur + 1 mineur + 1 hors pilote)

## Acceptés (preuves)
- T1 module + schéma : PR #127 fusionnée par David ; 126 puis 312 tests
- T2 registre 42 sources (18 petits/inconnus) ; 8/8 URL contrôlées
- T3 corpus 50 textes réels (11/14 URL vérifiées, 3 non vérifiables, 0 faux) + annotation de référence Grok relue par Gemini (11 contestées écartées)
- T6 critères gelés : commit 65c5e3e (sha256 2d1a9f65…)
- Gouvernance : 567 tests passés, 2 échecs préexistants sur main (test_reprise_collecte_governance_v1) ; chemins absolus PASS

## Mesures C3 (2026-10-26)
- Extracteur à règles (jeu final 39 textes) : précision 57 % (4/7), non_resolu 0/2, rappel 11 % → abandonné comme principal (2 cycles sans progrès).
- Extraction IA (Gemini + garde-fou déterministe), 53 textes notés, annotateur Grok relu par Gemini : précision 85,4 % (35/41), 0 cote inventée, schéma 100 %, rappel 67 %, non_resolu 0/1 (non mesurable). C3 = PARTIAL (C3.3 non atteint). Détail : mesure-c3-extraction-llm.json.
- Gemini ronde 4 sur 940a2eb : ACCEPTE_SOUS_RESERVE (0 bloquant chaîne pilote).

## Bloqués / limites
- C3.1 non atteint : précision 80 % (4/5) sur le jeu final caché ; C3.3 non mesurable (1 ambigu) — remesure après C33
- Grok : écriture de fichiers et fetch de pages refusés en headless → texte seul
- Plan pilote : 14/39 sources collectables (35,9 %) → couverture C1.1 ≥ 80 % rapportée sur sources collectables, limite documentée
- Veille PC et capot : réglés par David (capture)

## Reprises et erreurs
- Corpus par Grok impossible → Gemini ; checkout partiel → dépôt complet ; 4 lancements Codex en doublon arrêtés ; revue vide (nettoyage regex) refaite
