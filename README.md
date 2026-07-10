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

---

# Sprint 2 — Archive maison des cotes + recherche machine

## Nouveautés

| Quoi | Fichier | Déclenchement |
|---|---|---|
| **Archive des cotes exotiques** (Pinnacle + Unibet FR + Winamax) | `agents/agent_archive.py` + workflow **03** | cron toutes les 2 h |
| **Vague 2 — recherche machine** (combinaisons ≤3 atomes, FDR, exotiques) | `agents/agent_vague2.py` + workflow **04** | manuel |
| **Famille 1B** (3 hypothèses pré-enregistrées post-rapport) | `agents/vague1b_spec.py` | dans le workflow 02 |

## Mise en route Sprint 2 (3 gestes)

1. **Créer les 2 workflows** : voir `workflows_a_copier/LISEZMOI.txt` (même manip que pour 01/02 : *Add file → Create new file* → `.github/workflows/03_archive.yml` puis `04_vague2.yml`, coller le contenu).
2. **Ajouter le secret** : *Settings → Secrets and variables → Actions → New repository secret* → Nom `ODDS_API_KEY`, valeur = ta clé The Odds API.
3. **Plan API** : le rythme par défaut (2 snapshots/match : J-1 + quasi-clôture ≤2,5 h) consomme ~11 000 crédits/mois en pleine saison sur 9 ligues → **plan 20K à 30 $/mois** suffit. Garde-fous dans `config/archive.yaml` (plafond mensuel + arrêt d'urgence si quota bas).

## Ce que l'archive capture

8 marchés × Pinnacle (juge) + books FR (exécution) : `h2h`, `totals`, `team_totals`, `totals_h1`, `h2h_3_way_h1`, `btts`, `double_chance`, `alternate_totals_cards`. Chaque ligne = un prix horodaté. Le dernier snapshot ≤2,5 h avant le coup d'envoi = **quasi-clôture maison** (convention assumée, documentée — la vraie clôture seconde-près n'existe nulle part gratuitement).

**Semaine 1 = audit de couverture** : tous les books ne publient pas tous les marchés. Après 7 jours, regarder `data/archive/odds_*.parquet` pour savoir qui price quoi (cartons notamment). On ne promet rien avant cet audit.

## Vague 2 — règles gravées (`config/vague2.yaml`, pré-enregistré)

Mono/duo/trio d'atomes × 17 marchés exotiques uniquement (le 1X2 est efficient, on ne le re-mine pas). N≥300, FDR BH q=0.10 sur **tous** les tests effectués, cohérence de signe sur ≥2/3 blocs chronologiques, holdout 2025-26 toujours scellé. Les survivants = stock d'hypothèses à confronter aux prix de l'archive — **un lift n'est pas un edge**.

---

# Sprint 2.1 — Vague 2B : référence ajustée

La vague 2 (v1) comparait chaque signal à la moyenne de la ligue → tout ce qui est corrélé à la **force des équipes** ressortait avec des lifts énormes que le prix connaissait déjà (24 460 « survivants » = artefact). La **vague 2B** corrige : référence = matchs **comparables** (buckets force 1X2 × tempo O2.5 × venue, sur probas de clôture dé-viggées), FAVORI_NET/OUTSIDER/VENUE deviennent des contrôles, grammaire canonique (zéro miroir, zéro complément), seuil de rapport |Δ ajusté| ≥ 3 pts. Le rapport affiche **Δ ajusté vs Δ brut** côte à côte.

**Rien à faire côté workflows** : le 04 détecte `config/vague2b.yaml` et exécute la 2B automatiquement (l'ancienne famille reste exécutable avec `--v1` pour traçabilité). Il suffit de re-uploader les fichiers du zip et de relancer le 04. Le protocole v1 (`config/vague2.yaml`) et son rapport restent dans le repo comme pièces d'archive.

---

# Sprint 3 — Agent Confrontation (le juge)

`agents/agent_confrontation.py` + workflow **05** (quotidien, 10:07 UTC). Protocole **purement prospectif** :
- **Signaux** : pour chaque match à venir présent dans l'archive, les atomes sont calculés point-in-time (mêmes fonctions que le backtest, lignes virtuelles) et les **10 candidats pré-enregistrés** (`config/candidats_prix.yaml`) sont testés. Chaque déclenchement est journalisé avec les prix capturés — Pinnacle (juge, dé-viggé) + Winamax/Unibet FR (exécution) — **à la ligne réelle** (4,5 ou 5,5 cartons, pas une ligne théorique).
- **Règlement** : après le match, issue à la ligne capturée → edge réalisé vs proba juste + ROI papier à mise plate. Aucun signal rétroactif : ce qui n'a pas été journalisé avant le coup d'envoi n'existe pas.
- **Rapport** (`rapports/RAPPORT_CONFRONTATION.md`) : signaux à venir, bilan par candidat (verdict à N≥150 réglés), **couverture de l'archive** (qui price quoi, par book et par marché — l'audit automatisé), noms d'équipes non appariés (à ajouter dans `config/alias_equipes.yaml`).

Mise en route : créer `.github/workflows/05_confrontation.yml` (contenu dans `workflows_a_copier/`). Rien d'autre. Intersaison oblige : le rapport restera quasi vide jusqu'à la reprise des championnats (début août), c'est normal.
