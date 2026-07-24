# Robin des Stades — État du projet

Dernière mise à jour : 2026-07-24
Dépôt : `dddur75/robin-stades-ng`
Branche de travail : `codex/foundation-v1`
Mode : `SIMULATION`
Paris réels : `PRODUCTION_LOCKED`

## État global

`PARTIAL`

Le dépôt possède un moteur de features et de backtest, une collecte historique,
une archive de cotes, un protocole de confrontation prospectif, un dashboard HTML
et 13 tests automatisés. Il ne possède pas encore le modèle de données durable,
la traçabilité complète, l'API, le stockage PostgreSQL, ni les modèles probabilistes
prévus par la cible.

## Dernière étape terminée

`VERIFIED` — Audit initial du dépôt et fondation minimale reproductible.

Preuves :

- dépôt distant vérifié : `dddur75/robin-stades-ng`, branche principale `main` ;
- branche isolée créée : `codex/foundation-v1` ;
- environnement local isolé créé avec Python 3.14 ;
- suite complète après corrections : `13 passed` ;
- données historiques : 36 423 matchs, 9 ligues, 11 saisons ;
- contrôle minimal : 0 `match_id` dupliqué, 0 score manquant ;
- non-régression : les statistiques fournisseur absentes restent manquantes ;
- GitHub Actions récentes d'archive et de confrontation : succès ;
- workflow de CI en lecture seule ajouté pour les branches et pull requests.
- classement calculé en batch par date pour empêcher la fuite entre matchs
  simultanés.

## Étape actuelle

`IN_PROGRESS` — Jalon 1, fondation reproductible.

Priorités :

1. séparer données brutes, normalisées et produits analytiques ;
2. supprimer la fuite arbitre inter-ligues par une passe globale chronologique ;
3. dédupliquer les marchés neutres avant toute inférence ;
4. introduire des contrats Pydantic et des identifiants fournisseurs stables ;
5. définir le schéma PostgreSQL et les migrations ;
6. ajouter linting, typage et tests de qualité de données ;
7. rendre les écritures de pipelines atomiques et idempotentes ;
8. versionner datasets, modèles, prédictions et stratégies.

## Inventaire factuel

### Réutilisable

- `moteur/features.py` : construction point-in-time et atomes de contexte ;
- `moteur/devig.py` : dé-vig proportionnel et Shin ;
- `moteur/stats.py` : intervalles, tests et correction FDR ;
- `moteur/classement.py` : contexte de classement avant match ;
- `agents/agent_collecte.py` : collecte historique Football-Data ;
- `agents/agent_backtest.py` : évaluation d'hypothèses pré-enregistrées ;
- `agents/agent_archive.py` : capture budgétée de snapshots de cotes ;
- `agents/agent_confrontation.py` : journalisation prospective et règlement ;
- `tests/test_moteur.py` : tests synthétiques anti-lookahead et bout-en-bout ;
- `docs/index.html` : premier dashboard statique opérationnel.

### À renforcer ou remplacer progressivement

- dépôt non packagé avant cet audit et dépendances seulement bornées au minimum ;
- données brutes non conservées avant transformation ;
- l'historique déjà produit peut contenir des zéros artificiels pour les
  statistiques mi-temps, cartons et corners ; une recollecte versionnée sera
  nécessaire après mise en place du stockage brut ;
- schéma implicite dans des DataFrames, sans contrat ni migration ;
- fichiers Parquet suivis directement par Git, sans manifeste de dataset ;
- journal prospectif mutable dans un seul Parquet ;
- workflows qui écrivent directement sur `main` et utilisent `git pull --rebase || true` ;
- couverture de test concentrée dans un fichier monolithique ;
- aucune mesure automatisée de couverture, fraîcheur ou dérive ;
- aucune base PostgreSQL, API interne, registry durable ou dashboard applicatif ;
- statut de succès des workflows distinct de la présence réelle de snapshots de cotes.

## Blocages

Aucun blocage humain actif. Le secret GitHub `ODDS_API_KEY` existe déjà.

Blocage technique surveillé : aucun fichier `odds_*.parquet` n'est encore présent
dans l'archive au 2026-07-24. Les workflows réussissent, mais cela ne prouve pas
encore la capture effective de prix.

Risque qualité critique : l'historique existant ne permet pas de distinguer un vrai
zéro d'une statistique manquante dans les champs mi-temps, cartons et corners. La
collecte est corrigée pour les prochains runs, mais le dataset courant reste à
reconstruire depuis les CSV bruts avec un manifeste.

Verrous statistiques : signaux arbitre, rapports Vague 2/Vague 2B et ROI
multi-bookmaker restent `UNVERIFIED`. Voir `docs/audits/JALON-0-AUDIT.md`.

## Action utilisateur

Aucune. Voir `USER-ACTION.md`.

## Prochains jalons

- Jalon 0 — `VERIFIED`
- Jalon 1 — `IN_PROGRESS`
- Jalon 2 — `PARTIAL` (sources présentes, conservation brute absente)
- Jalon 3 — `PARTIAL` (dashboard statique, pas de Match Center)
- Jalons 4 à 9 — `NOT_STARTED`
