# Robin Experience V1.2 — identités d’équipes dynamiques

## Verdict

`ROBIN_EXPERIENCE_V1_2_IDENTITY_READY`

Les neuf fixtures actives publient désormais deux noms d’équipes vérifiés.
Aucun identifiant numérique n’est présenté comme nom d’équipe dans la vue
essentielle.

## Provenance

Les 18 identités proviennent exclusivement de payloads `FIXTURE` déjà présents
dans R2. Chaque nom est relié à son identifiant équipe, sa fixture, son reçu,
son SHA-256 et sa projection PostgreSQL dans
`reports/ux/team-identity-provenance.json`.

Le run d’audit réussi a effectué :

- 1 requête LIST R2 ;
- 36 lectures GET R2 : 18 reçus et 18 payloads, soit 50 002 octets ;
- 1 transaction PostgreSQL en lecture seule ;
- 2 requêtes PostgreSQL et 18 lignes lues ;
- 0 écriture R2 ou PostgreSQL ;
- 0 appel API-Football et 0 crédit Odds API.

Un premier audit a lu le même périmètre R2, puis s’est arrêté avant toute
requête PostgreSQL à cause d’un dialecte SQLAlchemy incompatible. Le cumul de
la mission est donc de 2 LIST, 72 GET et 100 004 octets R2, puis 1 transaction,
2 requêtes et 18 lignes PostgreSQL. Les deux passages sont restés en lecture
seule.

## Couverture

- fixtures attendues : 9 ;
- fixtures résolues : 9 ;
- emplacements d’identité attendus : 18 ;
- identités résolues : 18 ;
- identités non résolues : 0 ;
- couverture : 100 %.

Les noms vérifiés sont : Marseille, Strasbourg, Lens, Auxerre, Le Mans,
Stade Brestois 29, Nice, Lorient, Toulouse, Lyon, Estac Troyes, Paris FC,
Angers, Lille, Le Havre, Monaco, Paris Saint Germain et Rennes.

## Pipeline

La chaîne générale est :

```text
capture FIXTURE vérifiée
→ extraction provider:provider_team_id
→ registre d’identités temporel
→ rapport de provenance compact
→ snapshot Cockpit
→ modèle de présentation
→ interface
```

Le registre est déterministe et idempotent. Il sépare les fournisseurs,
conserve les versions successives d’un nom et leurs preuves, accepte une
nouvelle équipe sans modification frontend et ne déduit aucun nom court.
Une identité absente devient « Équipe en cours d’identification » ; son ID et
son statut restent accessibles uniquement dans le détail Expert.

L’enrichissement ne modifie ni le coup d’envoi, ni les fenêtres, ni le cutoff,
ni la date d’observation football. `sourceCapturedAt` reste
`2026-07-24T17:46:38Z`.

## Tests

La validation locale finale couvre :

- 758 tests Python ;
- 30 tests frontend, SSR, i18n et modèle de présentation ;
- les cas identité A à G : présent, absent, nouvelle équipe, changement de
  nom, collision multi-fournisseur, report de fixture et réordonnancement ;
- le test anti-dictionnaire manuel dans `cockpit/app` ;
- TypeScript strict, ESLint, Ruff, mypy strict sur 110 fichiers, Bandit,
  `pip check`, `compileall`, YAML, JSON et détection de secrets ;
- le hash du snapshot et les invariants temporels ;
- 9 scénarios Playwright, tous verts.

Aucune migration n’est ajoutée : la projection compacte existante suffit.
Le cycle des migrations reste couvert par la suite Python et la CI.

## Revue visuelle

Les 18 captures ont été régénérées :

- 8 desktop ;
- 7 smartphone à 390 × 844 ;
- 1 tablette ;
- 1 snapshot modifié synthétique ;
- 1 état vide synthétique.

Les vues Accueil, Matchs, fiche match et Observatoire ont été inspectées.
Les noms longs et composés reviennent à la ligne sans débordement. Aucun
`Équipe 81` ni autre fallback numérique n’est visible. Le clavier, les neuf
onglets mobiles et le zoom texte à 200 % restent utilisables.

## Performance

Le build production contient 500 282 octets de JavaScript et 47 349 octets de
CSS, soit 547 631 octets. L’ajout d’identité représente environ +0,31 % face
aux 545 960 octets de la V1.1 et reste très inférieur au plafond de +3 %.

## Sécurité

Les invariants restent verrouillés :

```text
STORAGE_PAUSED=true
P3/P4_PAUSED=true
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

Aucun payload brut, secret, header ou URL signée n’est ajouté à Git. Aucun nom
n’est inventé. Aucun pari, aucune publication sociale et aucune fusion ne sont
effectués.
