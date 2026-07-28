# Provenance des données dynamiques — Robin Experience V1.1

## Contrat de présentation

L’interface publique ne lit plus directement les structures techniques et ne
porte plus de valeurs opérationnelles codées en dur. La chaîne est :

```text
preuves vérifiées → cockpit-data.json → validation du schéma
→ buildPresentationModel(snapshot) → projection compacte → composants
```

`scripts/build_cockpit_snapshot.py` est le seul assembleur du snapshot public.
`cockpit/app/lib/presentation-model.ts` en construit ensuite le modèle typé.
`cockpit/scripts/build-presentation-data.ts` écrit deux projections compactes :

- `cockpit-presentation.json`, limitée aux données publiques nécessaires ;
- `cockpit-expert-data.json`, réservée à la Vue expert.

Le snapshot embarqué a été reconstruit à partir de l’artefact vérifié du run
`30314975830`, révision `2469e57ec4b2ef2849f9e707f63843033ec026e6`, sans
appel fournisseur, sans lecture R2 distante et sans écriture PostgreSQL.

## Matrice de provenance

| Information affichée | Clé du snapshot | Source vérifiée | Règle de présentation |
|---|---|---|---|
| rencontres, identifiants, coup d’envoi | `prospectiveObservatory.fixtures.registry` | registre et reçus du gate report | clé canonique, jamais la position dans un tableau |
| noms d’équipes | `fixtures.registry[].home_team_name` / `away_team_name` | identité présente dans le reçu vérifié | si le nom manque, afficher honnêtement l’identifiant fournisseur |
| fenêtres actives | `prospectiveObservatory.windows.registry` | politique temporelle versionnée + coup d’envoi | exclure legacy, annulées, tombstonées et terminées |
| prochaine capture | même registre de fenêtres | `opens_at`, `due_at`, `cutoff_at`, statut | recalcul à l’instant d’affichage, regroupement des échéances simultanées |
| captures et familles | `captures`, `by_family`, `fixtures.evidence` | reçus physiques et projections PostgreSQL vérifiées | états partiels et vides explicites, aucun zéro inventé |
| observations profondes | `deep_families` | tables prospectives profondes | afficher l’attente lorsque le volume est nul |
| candidats et décisions | `candidates`, `decisions` | gate report prospectif | aucune promotion implicite |
| bankroll et résultats | `patternResearch.bankroll`, `patternResearch.ledger` | ledger public + `configs/shadow_simulation_v1.json` | simulation uniquement, politique et capital initial versionnés |
| stockage R2 | `r2` | audit de replay et reçus | volumes, objets, hashes et parité uniquement |
| PostgreSQL | `postgresql` | rapport de migration et de projection | aucun corps de payload dans le snapshot |
| quotas et appels | `quota`, `calls` | journal budget compact | valeurs observées, jamais déclenchement d’appel |
| gates et hypothèses | `gates`, `hypotheses` | rapports scientifiques inchangés | traduction d’état sans modifier le verdict |
| génération et révision | `source`, `generatedAt` | métadonnées de l’artefact et du builder | date, âge, workflow et révision visibles en Expert |

## Fraîcheur et statuts

`buildPresentationModel(snapshot, { now })` dérive la fraîcheur à partir de
l’heure de génération et des fenêtres qui auraient dû être traitées :

- `FRESHNESS_CURRENT` : aucun traitement attendu ne manque ;
- `FRESHNESS_UPDATING` : une fenêtre est en cours dans la tolérance ;
- `FRESHNESS_STALE` : une fenêtre attendue ou le snapshot est trop ancien ;
- `FRESHNESS_INVALID` : la provenance ou la date est invalide.

Tous les statuts réellement présents dans le snapshot courant sont couverts
par le catalogue français. Un code essentiel inconnu devient exactement
« État en cours de vérification », est journalisé une seule fois dans la
console, et reste visible brut en Vue expert.

## Limite de la preuve actuelle

L’artefact historique utilisé contient les identifiants d’équipes mais pas
leurs noms. La V1.1 ne les invente pas : elle affiche donc « Équipe 81 »,
« Équipe 95 », etc. Le gate report enrichi publiera les noms dès qu’ils seront
présents dans les prochains reçus vérifiés.

## Invariants

Cette chaîne ne déclenche aucun appel API-Football ou The Odds API, aucune
capture, aucune écriture R2/PostgreSQL distante, aucune décision, aucune mise
et aucune publication sociale. `PRODUCTION_LOCKED`, `REAL_BETS=false` et
`NO_BET_DEFAULT=true` demeurent obligatoires.
