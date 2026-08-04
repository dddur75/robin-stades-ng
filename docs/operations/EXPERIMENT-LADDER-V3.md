# Échelle expérimentale V3

## Niveaux

| Niveau | Périmètre | Délai |
|---|---|---|
| E0 | 0–100 lignes synthétiques, aucun service distant | ≤ 2 min |
| E1 | 10–50 fixtures réelles, une famille | ≤ 5 min |
| E2 | 100–500 fixtures, une compétition-saison | ≤ 10 min |
| E3 | une compétition-saison ou 5 % du corpus | ≤ 15 min/job |
| E4 | cinq ligues 2020–2025 | cible 15, max 20 min/job |
| E5 | corpus étendu | seulement après P0 utile et vérifié |

La montée en charge dépend d'une preuve, pas de la disponibilité de calcul. E4
exige un checkpoint au plus toutes les cinq minutes.

## Corpus permanents

- Golden Synthetic Pack : doublons, nulls, reports, voids, incohérences, deux
  équipes, cotes, résultats et temporalité.
- Canary Real Pack : 50 fixtures couvrant cinq ligues avec hashes gelés.
- Pilot Season Pack : une compétition-saison choisie sur la meilleure preuve.

Un correctif local passe le Golden Pack puis le Canary Pack si des données réelles
sont nécessaires. Les packs doivent être versionnés sans recopier le corpus total.
À l'installation du système, leurs exigences sont définies mais les trois manifests
sont `NOT_MATERIALIZED`; aucune montée E1+ ne peut s'appuyer sur eux avant création,
gel des hashes et revue indépendante. Ce statut évite de présenter un contrat comme
une preuve de données existantes.

## Gate

Une décision de scale conserve : périmètre gelé, hash des entrées, résultat du
niveau précédent, objections, budget, stratégie de reprise, responsable et coût.
Sans ces éléments, le verdict est `SCALE_REFUSED`.

Sont interdits : replay complet pour un parser, corpus complet pour un
dénominateur, millions de règles pour un opérateur, build complet pour un libellé,
full CI après chaque micro-correctif et troisième tentative identique.
