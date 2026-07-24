# Audit du jalon 0

Date : 2026-07-24
Dépôt : `dddur75/robin-stades-ng`
Base auditée : `main` à `370b034`
Branche de correction : `codex/foundation-v1`

## Verdict

Le dépôt est une preuve de concept analytique utile, mais il n'est pas prêt pour
des décisions de pari ni pour une exploitation de production.

Le jalon 0 est `VERIFIED` en tant qu'audit et fondation initiale. Le produit reste
globalement `PARTIAL` et les paris réels sont `PRODUCTION_LOCKED`.

## Preuves exécutées

- dépôt et branche principale confirmés avec Git et GitHub ;
- 36 423 matchs, 27 colonnes, 9 ligues, 11 saisons ;
- dates du 2015-07-31 au 2026-05-24 ;
- 0 doublon de `match_id` et 0 score final manquant dans le Parquet courant ;
- `python -m compileall -q agents moteur tests` : succès ;
- `python -m pytest -q` : 13 tests réussis après corrections ;
- `python -m pip check` : aucune dépendance cassée ;
- workflows GitHub Actions récents d'archive et de confrontation : succès ;
- archive prospective réelle : 86 événements dans le ledger, mais zéro fichier
  `odds_*.parquet` et zéro crédit comptabilisé en juillet.

## Patrimoine réutilisable

- calculs de dé-vig proportionnel et Shin ;
- résolution déterministe des marchés ;
- construction de forme glissante avec décalage temporel ;
- classement et contexte d'enjeu point-in-time, après correction des matchs
  simultanés ;
- hypothèses pré-enregistrées et correction FDR ;
- protocole prospectif de journalisation/règlement ;
- logique de fenêtres de capture des cotes ;
- générateur synthétique et tests anti-lookahead ;
- dashboard HTML statique.

Ces composants seront encapsulés et migrés. Ils ne justifient pas une réécriture
destructive.

## Constats critiques

### 1. Valeurs manquantes transformées en zéros

L'ancienne collecte transformait les statistiques mi-temps, cartons et corners
manquantes en zéro. Certaines ligues-saisons apparaissent ainsi artificiellement
avec 100 % de matchs sans carton.

Impact : les marchés cartons et plusieurs features peuvent utiliser une absence de
donnée comme un fait sportif.

Correction réalisée : les nouveaux imports préservent les valeurs nulles, avec un
test de non-régression. Le Parquet historique n'est pas réparé : il devra être
reconstruit depuis des objets bruts versionnés.

### 2. Fuite entre matchs simultanés

L'heure fournisseur était supprimée et le classement mis à jour ligne par ligne.
Un match de la même ligue et de la même date pouvait donc voir le résultat d'un
match simultané.

Correction réalisée : tous les matchs d'une même date partagent désormais un état
pré-date, puis leurs résultats sont appliqués en batch. Un test vérifie
l'invariance à l'ordre des lignes.

### 3. Fuite arbitre inter-ligues

L'historique arbitre est global alors que la passe est réalisée saison complète
par saison complète. Des résultats ultérieurs d'une ligue peuvent être visibles
dans une autre ligue jouée plus tôt.

Statut : `BLOCKED` pour toute validation des signaux arbitre tant qu'une passe
globale strictement chronologique et son test multi-ligues ne sont pas livrés.

### 4. Double comptage dans Vague 2B

Les marchés neutres peuvent être comptés une fois par côté. Exemples audités :

- CP-01 : N publié 466, seulement 233 matchs uniques ;
- CP-04 : 6 452 lignes, 3 226 matchs uniques ;
- CP-05 : 1 222 lignes, 989 matchs uniques.

Impact : tailles d'échantillon, z-scores, p-values et FDR ne sont pas fiables.

Statut : rapports Vague 2/Vague 2B `UNVERIFIED`.

### 5. Pas de véritable validation hors échantillon

Les références Vague 2B utilisent les mêmes issues que les observations évaluées.
Les blocs chronologiques contrôlent le signe mais ne forment pas un walk-forward.
Les observations répétées par équipe/match ne respectent pas l'hypothèse
d'indépendance du z-test.

Statut : aucun modèle ou stratégie `PRODUCTION_READY`.

### 6. Règlement multi-bookmaker ambigu

Chaque bookmaker peut fournir une ligne différente, mais le journal ne conserve
qu'une ligne commune pour le règlement. Les pushes et les règles propres aux
marchés/cartons ne sont pas modélisés.

Impact : le ROI papier par bookmaker peut être faux.

Statut : règlement prospectif `PARTIAL`, aucun ROI exploitable.

## Constats élevés

- `match_id` ordinal instable en cas d'insertion ou de réordonnancement amont ;
- rapprochement d'équipes par similarité de noms sans identifiant fournisseur ;
- absence d'horodatage de collecte, hash brut, version de schéma et manifeste ;
- cotes Pinnacle historiques récentes explicitement signalées comme obsolètes
  par Football-Data depuis le 2025-07-23 ;
- arbitre manquant sur 71,86 % des lignes ;
- cotes 1X2 manquantes sur environ 4,6 % à 4,8 % ;
- cotes Over/Under 2,5 manquantes sur environ 41,8 % ;
- workflow vert confondu avec une capture de données effective ;
- dépendances à bornes minimales, sans lockfile ;
- workflows de données qui commitent directement et masquent les échecs de rebase.

## Corrections livrées dans la branche

- documents de pilotage obligatoires ;
- `pyproject.toml` et `.gitignore` ;
- environnement local isolé et workflow CI en lecture seule ;
- préservation des valeurs manquantes ;
- classement batché par date ;
- deux tests de non-régression supplémentaires ;
- décision d'architecture incrémentale ;
- audit initial des sources, coûts, données, modèles et stratégies.

## Ordre de correction recommandé

1. passe temporelle globale et tests multi-ligues ;
2. identifiants stables, stockage brut immuable et manifestes ;
3. déduplication par match et inférence robuste ;
4. vrai protocole rolling-origin/cross-fit ;
5. journal de prix et règlement par bookmaker/ligne/règle ;
6. PostgreSQL, migrations et contrats de données ;
7. qualité, observabilité et dashboard de santé.
