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
| T1 module + tests + schéma | Codex | en cours | inbox/codex/T1.log |
| T2 registre + CGU | Gemini (agy) | en cours | inbox/gemini/T2.log |
| T3 tipsters + corpus 40 + prompt | Grok | en cours | inbox/grok/T3.log |
| T4 extracteur + précision | Codex | prêt (attend schéma T1 accepté + corpus T3 accepté) | |
| T5 revue PR | Gemini | prêt (attend PR) | |
| T6 critères gelés (avant 30/10) | chef | prêt | |
| T7 collecte réelle / règlement / rapport | script + IA | prêt après T6 | |
