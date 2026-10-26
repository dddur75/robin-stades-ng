# RUSH-STATUS — Dossier fidèle (observatoire des sources)
Mis à jour : 2026-10-25 (T0)

## Routes (sondées 25/10, appel trivial réussi)
- Codex : codex-cli 0.163.0 — OK (`codex exec -s workspace-write`, ne peut pas committer : commit par le chef)
- Gemini : CLI `gemini` 0.64.0 BLOQUÉE (UNSUPPORTED_CLIENT, Google impose Antigravity). Route de remplacement `agy` + `gemini-4-argon-high` — OK
- Grok : grok 1.0.67 — OK
- Quota/plan : non exposés par les CLIs (inconnu)
- Dépôt : clone partiel de dddur75/robin-stades-ng (3,5 Go) ; worktree sparse `robin-stades-ng-wt\observatoire`, branche codex/observatoire-sources-v1 depuis origin/main 227b5ae

## Tâches
| Id | Poste | État | Preuve |
|---|---|---|---|
| T1 module + tests + schéma | Codex | ACCEPTÉ (91 tests relancés par le chef) | PR #127, 14d358a |
| T2 registre + CGU | Gemini | ACCEPTÉ sous réserve revue (42 sources, 18 petits) | 8/8 URL 200 |
| T3 tipsters + corpus + prompt | Grok | RELANCÉ sans écriture (verrou politique) -> sortie stdout | inbox/grok/*.txt |
| T4 extracteur + précision | Codex | prêt (attend schéma T1 accepté + corpus T3 accepté) | |
| T5 revue PR | Gemini | en cours | inbox/gemini/revue-PR127.md |
| T6 critères gelés | chef | FAIT — data/source_observatory/pilot_criteria.md | commit de gel |
| T7 collecte réelle / règlement / rapport | script + IA | prêt après T6 | |
