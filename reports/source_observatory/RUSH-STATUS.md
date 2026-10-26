# RUSH-STATUS — Dossier fidèle (observatoire des sources)
Mis à jour : 2026-10-26 (matin)

## Routes (sondées 25/10)
- Codex 0.163.0 OK (`codex exec -s workspace-write` ; ne commite pas, commit par le chef)
- Gemini : CLI `gemini` bloquée par Google ; route `agy` + gemini-4-argon-high OK
- Grok 1.0.67 OK en réponse texte seulement (aucun outil/écriture en headless : verrou de politique) ; une seule session à la fois
- Quotas : non exposés (inconnu)

## État
| Id | Poste | État | Preuve |
|---|---|---|---|
| T1 module + schéma | Codex | ACCEPTÉ, FUSIONNÉ (PR #127, par David) | 126 tests |
| T2 registre 42 sources | Gemini | ACCEPTÉ | 18 petits/inconnus ; 8/8 URL |
| T5 revue ronde 1 | Gemini | FAIT : REFUSE initial → corrigé par Codex | revue-gemini-PR127.md |
| T5 revue ronde 2 | Gemini | en cours | |
| T6 critères gelés | chef | FAIT (commit 65c5e3e) | pilot_criteria.md |
| T3 corpus 50 textes réels | Gemini | ACCEPTÉ (11/14 URL vérifiées, 3 non vérifiables, 0 faux) | hors Git |
| T3 annotation de référence | Grok + relecture Gemini | FAIT : 50 annotés, 11 contestés écartés du score | |
| T4 extracteur | Codex | 1re mesure NON CONFORME C3 (précision 60 %, 1 cote inventée, rappel 10 %) ; itération en cours sur jeu dev, jeu final de 25 textes caché | |
| T7 collecteur | Codex | prêt après T4 | |
