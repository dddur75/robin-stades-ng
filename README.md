# Robin des Stades NG — Sprint 1 : moteur de backtest Vague 1

Backtest **point-in-time** de 66 hypothèses pré-enregistrées (Session 2 du comité)
sur ~10 saisons × 9 ligues. Zéro pari réel. Zéro secret à configurer.
**Verdict par la donnée, pas par la promesse.**

---

## Installation en 6 étapes (≈ 15 min, aucune ligne de code)

1. **Créer un repo GitHub privé** nommé `robin-stades-ng`.
2. **Uploader tout le contenu de ce dossier** dans le repo (bouton *Add file → Upload files*, glisser-déposer, garder l'arborescence).
3. Onglet **Actions** → cliquer **"I understand my workflows, enable them"**.
4. Actions → **"01 - Donnees"** → *Run workflow* → attendre le vert (~4 min).
5. Actions → **"02 - Backtest vague 1"** → *Run workflow* → attendre le vert (~8 min, les tests du moteur tournent d'abord).
6. Ouvrir **`rapports/RAPPORT_VAGUE1.md`** dans le repo. C'est le verdict.

Ensuite : le workflow 01 tourne seul chaque lundi matin et relance le backtest.

---

## Ce que fait chaque agent

| Agent | Rôle | Source |
|---|---|---|
| `agent_collecte.py` | Télécharge résultats + cotes de clôture Pinnacle + cartons + arbitres | football-data.co.uk (gratuit) |
| `agent_understat.py` | xG par match, 5 grandes ligues — **best effort** : s'il casse, le backtest tourne en Tier A pur | understat.com |
| `agent_backtest.py` | Features point-in-time → 66 hypothèses → FDR → rapport | local |

## Comment lire le rapport

- **Étage 2** : jugé contre la **clôture Pinnacle dé-viggée** (ROI à mise plate 1u). C'est le seul étage qui paie.
- **Étage 2\*** : proba juste dérivée du 1X2, mais prix du marché (double chance) non archivé → edge sans ROI.
- **Étage 1** : lift vs taux de base ligue-saison-venue. **Un lift ne paie rien tant que le prix n'est pas battu** — il dit seulement où creuser (corners, cartons, MT : l'archive maison de cotes fournira les prix en prospectif).
- **FDR Benjamini-Hochberg q=0.10** sur toute la famille de tests : ce qui ne la passe pas est du **BRUIT**, point.
- **CANDIDAT_VALIDE_E2** exige : FDR ✓, Δ>0, N≥300, edge positif sur ≥⅔ des saisons.

## Garde-fous actifs (ne pas toucher)

- **Holdout scellé** : la saison 2025-26 est exclue de tout calcul (`config/ligues.yaml`). Elle ne sera ouverte qu'une fois, au verdict final.
- **Pré-enregistrement** : `agents/vague1_spec.py` ne se modifie plus après le premier run. Toute nouvelle idée = vague 2.
- **Anti-lookahead prouvé** : `tests/test_moteur.py` mute le futur et vérifie que les features ne bougent pas. Le workflow 02 refuse de backtester si un test échoue.
- Le test doctrinal `test_lift_reel_mais_edge_nul` implante un vrai effet dans des données synthétiques avec un prix efficient : le moteur trouve le lift (É1) **et** confirme l'absence d'edge (É2). C'est la preuve mécanique que battre le taux de base ≠ gagner de l'argent.

## Limitations connues v1 (assumées, documentées)

- Repos/fatigue = calendrier **championnat uniquement** (calendrier UEFA → v1.1 ; S035/S036 non évaluées).
- `ENCAISSE_60_90`, déplacements géographiques, trêves internationales, atomes joueurs (Tier B) → sprints suivants.
- Doublons/orthographe `config/derbys.yaml` à vérifier contre les noms football-data au premier run.
- Understat : scraping fragile par nature ; en cas d'échec, les 14 hypothèses xG passent en `NON_EVALUE`.

## Prochain sprint (après lecture du rapport)

Archive maison des cotes (Unibet FR + Winamax + Pinnacle via The Odds API) pour pricer les marchés exotiques, agent paper-trading J-1 + Telegram, et lancement de la **vague 2 machine** (exploration combinatoire ≤3 atomes sous FDR) sur la grammaire du registre.
