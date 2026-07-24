# Dictionnaire de données

Statut : `PARTIAL`

## Dataset historique actuel — `data/matches.parquet`

Grain : un match terminé par ligne.
Clé actuelle : `match_id`.
Couverture auditée : 36 423 lignes, 27 colonnes, 9 ligues, 11 saisons.

| Champ | Sens | Disponibilité temporelle |
|---|---|---|
| `match_id` | Identifiant construit du match | après normalisation |
| `league` | Code Football-Data de la compétition | avant match |
| `season` | Saison normalisée `YYYY-YY` | avant match |
| `date` | Date du match | avant match |
| `home`, `away` | Équipes domicile et extérieur | avant match |
| `fthg`, `ftag` | Buts fin de match | après match uniquement |
| `hthg`, `htag` | Buts à la mi-temps | après match uniquement |
| `referee` | Arbitre | disponibilité variable |
| `hy`, `ay`, `hr`, `ar` | Cartons | après match uniquement |
| `hc`, `ac` | Corners | après match uniquement |
| `psh`, `psd`, `psa` | Cotes 1X2 disponibles | horodatage source insuffisant |
| `psch`, `pscd`, `psca` | Cotes 1X2 dites de clôture | fiabilité à qualifier |
| `p_o25`, `p_u25` | Cotes Over/Under 2,5 | horodatage source insuffisant |
| `pc_o25`, `pc_u25` | Cotes Over/Under 2,5 dites de clôture | fiabilité à qualifier |

Qualité observée au 2026-07-24 :

- arbitre manquant : 71,86 % ;
- cotes 1X2 manquantes : 4,58 % à 4,80 % selon le snapshot ;
- cotes Over/Under 2,5 manquantes : 41,76 % à 41,88 % ;
- mi-temps, cartons et corners affichent 0 % de valeurs manquantes, mais ce taux
  n'est pas fiable : l'ancienne collecte remplaçait les valeurs absentes par zéro.

Une valeur manquante ne doit jamais être assimilée à zéro sans règle explicite et
testée. La collecte est corrigée, mais le fichier actuel devra être reconstruit
après conservation des CSV bruts et ajout d'un manifeste de provenance.

## Métriques existantes

| Métrique | Définition |
|---|---|
| probabilité dé-viggée | inverse des cotes, puis correction proportionnelle ou Shin |
| lift | différence entre taux conditionnel et référence choisie |
| edge | probabilité estimée moins probabilité implicite juste |
| ROI flat | somme des gains pour des mises unitaires divisée par le nombre de paris |
| FDR | correction Benjamini-Hochberg sur une famille de tests |

## Entités cibles absentes

Fournisseur, compétition, saison, équipe, joueur, entraîneur, stade, bookmaker,
snapshot brut, dataset versionné, modèle, prédiction immuable, explication,
stratégie versionnée, pari candidat/rejeté/simulé, bankroll, incident et alerte de
qualité seront introduits par migrations versionnées.
