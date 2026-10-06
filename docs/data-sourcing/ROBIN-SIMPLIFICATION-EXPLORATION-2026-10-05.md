# Robin — expérience descriptive figée du 5 octobre 2026

## Statut scientifique

Cette expérience est **descriptive et exposée**. Les acquisitions ont servi à
l'exploration ; elles ne valident donc aucun edge, aucune causalité, aucune
rentabilité et aucune capacité prédictive. Les deux acquisitions ont été figées
avant ce recalcul indépendant :

| Rôle | Run d'origine | Créneau UTC | Lignes | SHA-256 JSON normalisé |
|---|---:|---|---:|---|
| Ancienne | `37276237875` | `2026-10-05T08:00:00Z` | 7 731 | `83d2f9934cca5c21a6056c300e457e3930cdd6e92fbf646dedf46901417c26dc` |
| Nouvelle | `37292740942` | `2026-10-05T10:00:00Z` | 7 654 | `2bb2b0d1169ca75b153d4069bdd38954c7d7070f630a10d10e1c9e8e06abee91` |

Chaque reçu atteste cinq captures validées, un rôle `CURRENT`, une relecture R2
`VERIFIED` et l'absence de rejeu. Les payloads structurés ont été relus depuis les
artifacts déjà téléchargés ; le calcul n'a effectué aucun appel fournisseur, aucun
replay et aucune écriture R2. L'artifact GitHub expirant n'est pas l'unique source
durable : les reçus lient les JSON à leurs rapports privés R2 immuables.

## Contrat de comparaison

L'identité exacte est `(sport_key, event_id, bookmaker_key, market_key, outcome,
point)`. Le seuil fait donc partie de l'offre totals ; H2H exige un seuil nul.
Une branche n'est comparable que si elle est présente et valide des deux côtés,
avec un instant de capture ancien strictement antérieur au nouveau. Les doublons,
identités invalides et cotes non finies ou non positives sont exclus, jamais
convertis en zéro. Une offre absente du second créneau est « non observée à
nouveau », pas « retirée par le fournisseur ».

Les lignes normalisées ne portent pas explicitement l'identité du fournisseur, la
période de règlement, ni le début et la fin d'acquisition par branche. L'expérience
retient donc l'hypothèse déclarée d'un même collecteur/fournisseur et d'un contrat
plein match identique. Cette limite interdit toute promotion scientifique.

## Résultat recalculé

- 7 648 offres exactes appariées ; 682 ont changé, soit 8,9174 %.
- 373 mouvements à la hausse, 309 à la baisse et 6 966 cotes inchangées.
- amplitude absolue moyenne 0,0144, médiane 0 et maximum 5,0.
- 6 offres apparues, 83 non observées à nouveau et 0 ligne exclue.
- Serie A : 202 changements sur 1 608 offres appariées, proportion descriptive la
  plus élevée des cinq ligues (12,5622 %).
- H2H : 504 changements sur 5 352 offres appariées ; totals : 178 sur 2 296.

Les dénominateurs, matchs distincts, sens et amplitudes par ligue, bookmaker et
marché ainsi que douze lignes sources d'échantillon sont consultables dans
`reports/experiments/robin-descriptive-20261005-0800-1000.json`.

## Reproduction et QA

Le chemin borné est `scripts/run_descriptive_experiment.py`. Il valide d'abord le
reçu et le SHA-256 de chaque JSON, recalcule avec
`src/robin/capture/descriptive_experiment.py`, puis rapproche seulement les totaux
finaux avec le moteur partagé de l'interface. Le calcul QA indépendant n'importe ni
n'appelle `real_data_dashboard`.

Les tests ciblés couvrent corruption de hash, seuils totals distincts, apparition,
non-observation, branche non comparable, doublon, prix invalide, ventilations,
rapport réel et CLI. Les questions de recherche proposées dans le rapport devront
être éprouvées sur de futures acquisitions indépendantes, avec hypothèse gelée à
l'avance.
