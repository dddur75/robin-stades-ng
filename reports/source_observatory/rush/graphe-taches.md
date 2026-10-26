# Graphe de tâches — contrats courts (2026-10-26 12:40)
États : planned / ready / running / review / accepted / blocked / reconcile.

| Id | Dépend de | Sortie | Critères d'acceptation | Rédacteur | Route | État |
|---|---|---|---|---|---|---|
| CI128 | push v2 | CI de la PR #128 au vert | tous les jobs verts sauf préexistants documentés | chef | gh | running (Quality and domain tests en attente) |
| R3 | PR #128 | revue-ronde3 + corrections | 0 bloquant sur la chaîne collecte→horodatages→règlement | Codex (corrige) / Gemini (relit) | Codex + agy | running (Codex corrige, 5 bloquants) |
| C33a | — | ≥15 textes ambigus réels | URL ouvertes, hors corpus existant | Gemini (Grok bloqué : fetch refusé) | agy | running |
| C33b | C33a | annotation de référence des ambigus | relue par un autre fournisseur | Grok (annote) / Gemini (relit) | grok texte + agy | planned |
| C33c | C33b | remesure en aveugle de C3 | critères gelés inchangés, jeu final caché | Codex | codex | planned |
| T7x | R3 accepté, CI128 | collecte réelle pré-match 30/10→coup d'envoi | robots.txt/CGU respectés, hash seulement, couverture rapportée | script (collector) | local | planned |
| T8 | T7x | règlement + rapport « Dossier fidèle » | règles documentées ; sinon en_attente ; 4 temps ; C1–C6 | Codex (code) / Gemini (relit) | codex + agy | planned |

Règle : « accepted » = critères vérifiés par le chef après revue croisée par un autre fournisseur.
Deux cycles sans progrès sur une tâche → changement de méthode (déjà appliqué : Grok headless → Gemini pour la collecte ; checkout partiel → dépôt complet).
