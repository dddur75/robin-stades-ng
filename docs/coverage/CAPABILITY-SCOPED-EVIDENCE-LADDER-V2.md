# Capability-Scoped Evidence Ladder V2

## But

La V2 décide uniquement quelle capacité peut progresser. Elle ne lance aucun workload,
ne lit aucune donnée distante et n'accorde aucune autorisation externe.

Le contrat autoritatif est
`configs/data/capability-scoped-evidence-ladder-v2.json`. Le validateur compact est
`robin.governance.capability_evidence`.

## Portée du résultat E1A

La campagne `E1A_ABSENCE_CAUSE_CLASSIFICATION` conserve le statut
`STOPPED_LOCAL_CAMPAIGN`. Deux architectures ont reproduit :

```text
3036 absences = 2681 blessures confirmées + 206 suspensions confirmées
                + 149 ABSENCE_CAUSE_UNKNOWN
```

Ce résultat bloque `ABSENCE_CAUSE_EXACT` et seulement les capacités qui déclarent
explicitement cette dépendance. Il ne bloque pas automatiquement les équipes, joueurs,
compositions, formations, événements, statistiques, calendrier, fatigue, classements ou
discipline générique.

Une capacité sans preuve spécifique reste `NOT_EVALUATED`. Elle n'est ni prête, ni
inutilisable, ni implicitement bloquée.

## Statuts

- `NOT_EVALUATED` : aucune preuve propre à la capacité.
- `MEASURED_PARTIAL` : tranche mesurée, sans autorisation de montée en charge.
- `READY_STRICT` : preuve stricte complète selon le contrat de la capacité.
- `READY_RECONSTRUCTED` : preuve complète obtenue par reconstruction autorisée.
- `BLOCKED_BY_COVERAGE`, `BLOCKED_BY_TEMPORALITY`, `BLOCKED_BY_SOURCE` : blocages locaux.
- `BLOCKED_BY_DEPENDENCY` : un parent explicitement déclaré est bloqué.
- `STOPPED_LOCAL_CAMPAIGN` : campagne locale épuisée, sans arrêt global.

Le statut ambigu `READY` est interdit. `scale_authorized=true` est impossible tant que le
statut n'est pas qualifié `READY_STRICT` ou `READY_RECONSTRUCTED`. Un statut qualifié est
également refusé sans périmètre testé, claim de preuve ou dépendances toutes qualifiées
prêtes.

## UNKNOWN

`ABSENCE_CAUSE_UNKNOWN` est une valeur canonique. Elle n'est jamais convertie en zéro,
faux, blessure ou suspension.

Chaque future campagne choisira explicitement une politique parmi :

- `CONFIRMED_ONLY` ;
- `GENERIC_UNAVAILABILITY` ;
- `EXCLUDE_UNKNOWN` ;
- `INCLUDE_UNKNOWN_AS_UNKNOWN` ;
- `SENSITIVITY_ANALYSIS`.

Une politique d'exclusion modifie uniquement le périmètre analytique ; elle ne modifie
jamais la valeur source.

## Dépendances

Le validateur vérifie les références, détecte les cycles et impose à toute capacité ayant
`requires_exact_absence_cause=true` de déclarer `ABSENCE_CAUSE_EXACT` dans `depends_on`.
Le résolveur propage alors `BLOCKED_BY_DEPENDENCY` aux seuls enfants concernés.

Exemple :

```text
ABSENCE_CAUSE_EXACT = STOPPED_LOCAL_CAMPAIGN
  -> croisement qui exige la cause exacte = BLOCKED_BY_DEPENDENCY
  -> TEAM ou CALENDAR sans cette dépendance = NOT_EVALUATED
```

## Limites et sécurité

Le catalogue V2 contient 18 capacités, un validateur et des tests synthétiques. Il ne
contient ni orchestrateur, ni Council supplémentaire, ni journal transactionnel.

Le schéma fermé exige tous les effets externes explicitement à zéro : API-Football, R2, SQL distant,
déploiement, publication, pari et promotion. Les campagnes E1B à E4 restent hors de cette
mission.
