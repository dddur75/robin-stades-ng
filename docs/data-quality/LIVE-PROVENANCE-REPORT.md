# Rapport de provenance live

Date de capture : 2026-07-24  
Artefact canonique : `shadow-state-30095263615`  
Commit source : `e32ecfe09987542bba750b766488ddd927b6ea0b`

## Chaîne de preuve

```text
The Odds API
  → réponse HTTP authentifiée
  → payload brut adressé par SHA-256
  → observation append-only horodatée en UTC
  → fixture / snapshot normalisé avec identifiant stable
  → artifact GitHub explicitement restauré
  → prédiction MARKET_BASELINE_ONLY
  → décision shadow immutable
  → preuve compacte publiée dans le dépôt
```

La preuve versionnée dans `data/live-proof/jalon3-activation.json` est dérivée et
compacte. Les payloads fournisseurs complets restent dans les artifacts GitHub
et ne sont pas publiés dans Git.

## Provenance observée

| Objet | Volume | Source | Identité / intégrité |
|---|---:|---|---|
| fixtures | 9 | The Odds API | `provider_fixture_id` + UUID interne stable |
| payload fixtures | 1 copie binaire | endpoint événements Ligue 1 | SHA-256 `bfc60c7f…` |
| observations fixtures | 3 | runs distincts | journal append-only |
| snapshots odds | 2 | endpoint odds Marseille–Strasbourg | UUID stables, hashes distincts |
| quotes | 180 | 22 bookmakers | marchés 1X2 et Totaux |
| prédictions | 1 | snapshot live le plus récent | `MARKET_BASELINE_ONLY`, historique non utilisé |
| décisions | 1 rejet | prédiction live | `QUALITY_BLOCKED`, mise 0 |
| sorties bloquées | 8 | absence de snapshot | aucune valeur inventée |

## Cohérence externe

La première journée observée débute le 21 août 2026 et se termine le 23 août.
Les neuf affiches, ainsi que les horaires Marseille–Strasbourg, Lens–Auxerre,
Angers–Lille et PSG–Rennes, concordent avec les publications officielles LFP :

- calendrier général :
  <https://ligue1.com/fr/articles/l1_article_5284-> ;
- programmation TV des deux premières journées :
  <https://ligue1.com/fr/articles/l1_article_5435-programmation-tv-des-2-premieres-journees-de-ligue-1-mc-donald-s-2627>.

## Contrôles

- source, endpoint, instant, hash et run d’ingestion présents : `PASS` ;
- secret ou paramètre sensible dans la preuve : `PASS`, aucun ;
- restauration inter-runners avec observation stable : `PASS` ;
- réécriture d’un objet brut : `PASS`, aucune ;
- doublon exact de snapshot : `PASS`, aucun ;
- fuite legacy dans la baseline live : `PASS`, aucune ;
- valeurs sportives manquantes : `WARN`, 8 sorties bloquées et affichées
  `EN ATTENTE DE DONNÉES PROSPECTIVES`.

`LIVE SOURCE`, `LEGACY SOURCE`, `DEMO DATA` et `NO OUTPUT` restent des catégories
contractuelles. Leur fusion visuelle ou analytique est interdite.
