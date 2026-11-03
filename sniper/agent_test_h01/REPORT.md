# H01 — test agent exploratoire, non pré-enregistré

**Total : 33 paris, 20 gagnants (60,61 %), ROI +2,48 %, profit cumulé
+0,82 unité, drawdown maximal 3,45 unités, cote moyenne 1,8261.**
Périmètre : E0, F1, D1, I1, SP1 ; 2020-21 à 2024-25 ; 25 CSV, 8 982 matchs.

| Saison | Paris | Réussite | ROI | Profit (u) | DD max (u) | Cote moy. |
|---|---:|---:|---:|---:|---:|---:|
| 2020-21 | 5 | 40,00 % | −39,00 % | −1,95 | 2,00 | 1,8200 |
| 2021-22 | 5 | 40,00 % | −30,00 % | −1,50 | 2,00 | 1,9300 |
| 2022-23 | 10 | 80,00 % | +46,70 % | +4,67 | 2,00 | 1,8620 |
| 2023-24 | 7 | 71,43 % | +9,71 % | +0,68 | 2,00 | 1,5443 |
| 2024-25 | 6 | 50,00 % | −18,00 % | −1,08 | 1,56 | 2,0133 |

Règle : trois victoires précédentes à domicile et trois défaites précédentes
à l'extérieur, dans la même ligue-saison ; B365H ∈ [1,40 ; 3,00]. Les matchs
à l'autre lieu sont sans effet ; un nul casse la série. Toutes les rencontres
alimentent les séries, même sans cote exploitable ; seules les cotes valides
déclenchent un pari. Les matchs du jour sont exclus de l'historique du jour.
Ordre des paris : date, code ligue, domicile, extérieur, saison ; les égalités
de date sont ainsi résolues conventionnellement pour le drawdown.
Gain net : cote − 1 si H, sinon −1 ; ROI = 100 × somme des gains / nombre de
paris. DD = plus forte baisse du profit depuis son sommet, capital initial 0 ;
remise à zéro pour chaque bilan saisonnier, aucune pour le bilan total.

Lecture critique (3 points) :
- Seulement 33 paris : résultat fragile, sans preuve d'avantage statistique.
- Hypothèse non pré-enregistrée : biais de sélection et tests multiples possibles ; aucune validation prospective.
- Cotes historiques B365H sans preuve d'exécution au prix indiqué ; frais, limites, révisions de données et dépendances entre matchs ignorés.

Source : [football-data.co.uk](https://www.football-data.co.uk/data.php), URLs,
effectifs et SHA-256 des CSV avec fins de ligne normalisées LF dans `results.json`.
Le téléchargement conserve les CSV déjà présents et validés ; les supprimer
permet de les retélécharger, mais une révision distante peut changer le résultat.

Rejouer depuis la racine du dépôt, avec **Python 3.11** dans le PATH
(versions directes utilisées lors de la vérification ; aucune installation du projet) :

```sh
cd sniper/agent_test_h01
python -m pip install pandas==2.2.3 requests==2.32.3 pytest==8.3.5
python -m pytest -p no:cacheprovider test_h01.py -q
python download_data.py && python backtest_h01.py
git diff --exit-code -- results.json
```

Vérification : 5 tests passent sur un jeu synthétique de 20 matchs ; recalcul
indépendant des 33 paris concordant. Questions ouvertes : aucune.
