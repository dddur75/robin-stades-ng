# Cumul CLV papier 2026-27

Mission : traiter les cotes déjà collectées de la saison, jusqu'au 19 octobre
2026 inclus, jour UTC de coup d'envoi. Une branche issue de `main`, une PR ;
aucun pari réel, appel fournisseur, accès Neon, changement de collecte ou fusion.
Les workflows, budgets, verrous, configurations existantes et données sources
restent inchangés. Le nouveau script adapte localement la projection publique
`match="Domicile — Extérieur"` ; une séparation ambiguë est refusée. Le moteur `src/robin/clv.py` reste
strictement identique à `main` et son chargeur `load()` est réutilisé.

## Refaire le calcul

Après extraction des rapports existants dans un répertoire local :

```sh
PYTHONPATH=src python scripts/clv_cumul.py --through 2026-10-19 /chemin/stock
```

La commande produit `reports/clv/2026-27/`. Elle accepte plusieurs fichiers et
répertoires ; les répertoires recherchent récursivement `robin-real-data.json`
et `odds-snapshots.jsonl`. Les fichiers explicites peuvent porter un autre nom.
Les entrées JSONL sont les objets `OddsSnapshot` du `JsonlSnapshotStore`.
Les autres JSON/JSONL, données de démonstration et payloads bruts ne sont pas
recherchés automatiquement. Ne pas pointer sur `data/shadow-demo`.
Dépendances : environnement du dépôt, dont SciPy pour l'IC Student du moteur.
Sans `--through`, la borne est hier en Europe/Paris ; les matchs restent groupés
par jour UTC. `--start` vaut le 1er juillet 2026 par défaut ; `--output` change
le répertoire de sortie. Utiliser un répertoire vide pour une autre période.

La livraison épingle les entrées et leurs SHA-256 dans `SOURCES.json` ;
`ARTIFACTS.json` donne les identifiants GitHub des archives et vérifie le hash
normalisé contre chaque reçu public. Pour reconstituer le stock, télécharger
ces artefacts depuis `dddur75/robin-stades-ng` et conserver chaque fichier sous
`<artifact_id>/robin-real-data.json`. Par exemple, depuis une machine ayant accès
aux téléchargements GitHub :

```sh
gh api repos/dddur75/robin-stades-ng/actions/artifacts/12223986152/zip > /tmp/clv-input.zip
unzip /tmp/clv-input.zip -d /chemin/stock/12223986152
```

Ce script ne télécharge rien et ne contacte aucun fournisseur. La reproduction
exige de conserver le stock local : les artefacts GitHub ont une rétention limitée.
Les archives et les rapports normalisés restent hors Git ; seuls les résultats
CLV, inventaires, hashes et limites sont livrés.

## Acceptation et limites

Deux CSV par journée ayant des matchs dans le stock, y compris des CSV à en-tête
si aucun book FR n'est exploitable. `CUMUL.md` contient tous les groupes et les
10 meilleurs CLV moyens avec n ≥ 30. Chaque groupe donne n, moyenne, IC95,
n et moyenne late, et nombre/dénominateur/part de MISSING_HORIZON.
La bande INCONNUE conserve les lignes sans clôture. Les répétitions ne gonflent
pas n ; les contradictions excluent tout le match dans `EXCLUSIONS.csv`.
Le stock restant est traité sans interpolation ni correction de source.
Les statistiques portent la claim `DATA.CLV202627.CUMUL.V1` ; couverture détaillée
dans `reports/clv/2026-27/COVERAGE.md`. L'exhaustivité des données durables R2
n'est pas établie ici. Les intervalles restent descriptifs et ne valident aucun edge.

## Résumé de mission

- Fait : script local, chargeur des projections publiques et tests de régression.
- Fait : exports quotidiens et cumul du stock récupérable, entrées hachées.
- Reste : revue indépendante et décision de fusion par Qualité.
- Risque : rétention GitHub, stock R2 non inventorié, horaires contradictoires exclus.
