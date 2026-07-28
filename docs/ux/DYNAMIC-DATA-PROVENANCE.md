# Provenance des données dynamiques — Robin Experience V1.2

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
| noms d’équipes | `fixtures.registry[].home_team_name` / `away_team_name` | payload `FIXTURE` R2 et reçu vérifié, projetés dans le registre d’identités | si le nom manque, afficher « Équipe en cours d’identification » ; ID uniquement en Expert |
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

## Preuve d’identité V1.2

Le rapport `reports/ux/team-identity-provenance.json` relie les neuf fixtures
aux 18 noms présents dans des payloads `FIXTURE` R2 existants et à leurs reçus
vérifiés. La couverture est 18/18, sans nom inventé ni appel fournisseur.

Le registre est indexé par `provider:provider_team_id`, conserve la provenance
temporelle et évite toute collision multi-fournisseur ou association par
position. Son empreinte est
`eaa6d296ba19464df74393d26ffb638145302b3a8173243571cb6d7f8ed951ff`.
Le snapshot enrichi porte l’empreinte
`217a66a4bcaed77028d407a7a14f0b4ee2be2e3f34cfcb34632d9cae9f005d7f`.

L’audit réussi a effectué 1 LIST et 36 GET R2, puis une transaction
PostgreSQL read-only de 2 requêtes et 18 lignes. Il a réalisé 0 écriture,
0 appel API-Football et consommé 0 crédit Odds.

## Invariants

Cette chaîne ne déclenche aucun appel API-Football ou The Odds API, aucune
capture, aucune écriture R2/PostgreSQL distante, aucune décision, aucune mise
et aucune publication sociale. `PRODUCTION_LOCKED`, `REAL_BETS=false` et
`NO_BET_DEFAULT=true` demeurent obligatoires.

La chaîne V1.2 est fusionnée par
`937481e914ddbac56432a85bef8466a30c43e1d0`, validée post-fusion et déployée
en privé depuis l’arbre exact du sous-répertoire `cockpit` de `main`.
