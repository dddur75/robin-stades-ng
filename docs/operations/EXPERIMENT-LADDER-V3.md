# Échelle expérimentale V3.1 minimale

## Rôle

Le Council contrôle la progression scientifique; il ne planifie et n'exécute
aucun workload. GitHub Actions, R2, Git et l'orchestrateur Codex conservent leurs
rôles. Une décision du Council n'est jamais une autorisation de service externe.

## Étapes de gouvernance

| Étape | Preuve attendue | Délai indicatif |
|---|---|---|
| E1 | preuve réelle E1 bornée | ≤ 5 min |
| E2 | 100 fixtures réelles | ≤ 10 min |
| E3A | une compétition-saison complète | ≤ 15 min/job |
| E3B | une saison sur cinq ligues | ≤ 15 min/job |
| E4 | P0 complet | cible 15, max 20 min/job |

L'ordre de contrôle est strict :

```text
E1 → E2 → E3A → E3B → E4
```

Les sous-lots opérationnels E1A et E1B peuvent alimenter la preuve E1, mais ne
créent pas un moteur d'exécution ni un état supplémentaire dans le Council
minimal. Le manifeste de mission gèle les étapes réellement autorisées et le
plafond. Disponibilité de calcul et réussite scientifique restent deux faits
distincts.

## Autorisation de mission

Une mission repose sur un manifeste immuable contenant exactement :

```text
mission_id
authorized_stages
maximum_stage
external_effects
compute_budget
time_budget
source_hash
expires_at
```

Le manifeste ne crée pas d'autorité externe. `external_effects` doit respecter
la matrice d'activation et les verrous du dépôt; tout effet absent, inconnu ou
interdit reste `DEFAULT_DENY`.

## Décision d'étape

Les seules décisions sont :

```text
PASS_AND_SCALE
PASS_AND_HOLD
FAIL_AND_REDESIGN
FAIL_AND_STOP
BLOCKED_EXTERNAL_ACTION
```

`PASS_AND_SCALE` ouvre seulement l'étape immédiatement suivante. Il est valide
si et seulement si :

- l'étape courante est prouvée et ses critères sont satisfaits;
- l'étape suivante est dans `authorized_stages` et ne dépasse pas
  `maximum_stage`;
- budgets de calcul et de temps ainsi qu'expiration sont respectés;
- aucun veto critique n'est ouvert;
- aucun effet externe interdit n'est demandé.

Au plafond ou sans preuve suffisante, la décision est `PASS_AND_HOLD`. Un saut de
niveau est refusé. Une source obligatoire absente produit `FAIL_AND_STOP`. Un
effet externe interdit produit `BLOCKED_EXTERNAL_ACTION`.

## Règle des deux échecs

La similarité est déterminée par taxonomie, signature de cause et périmètre :

1. premier échec similaire : conserver le niveau et appliquer le plus petit
   correctif;
2. deuxième échec similaire : `FAIL_AND_REDESIGN`, puis retour à E1 avec une
   architecture modifiée;
3. troisième tentative inchangée : interdite avant exécution et
   `FAIL_AND_STOP`.

Le Golden Synthetic Pack et le Canary Real Pack restent des preuves de domaine
réutilisables lorsqu'ils sont nécessaires. Leur préparation et leur exécution ne
font pas partie du Council.

## Journal minimal

Le journal append-only accepte uniquement :

```text
MISSION_AUTHORIZED
STAGE_STARTED
STAGE_FINISHED
DECISION
FAILURE
VETO
REDESIGN
```

Chaque record utilise un JSON canonique, un hash SHA-256 déterministe et le hash
du record précédent. Cette chaîne rend une réécriture détectable; elle ne promet
ni transaction distribuée, ni coordination de contrôleurs concurrents, ni
récupération après crash.

## Hors périmètre V3.1

Les sujets suivants sont archivés `FUTURE_DESIGN_NOT_IMPLEMENTED` :

- planification ou exécution des workloads;
- transactions distribuées et protocole transactionnel de crash;
- rotation d'autorité complexe et contrôleurs concurrents;
- réparation d'authority race et quarantaine post-commit;
- reconstruction complexe de grants et bindings multiples de preuves;
- remplacement de GitHub Actions, R2, Git ou Codex.

## Tests proportionnés

La simplification utilise seulement les tests ciblés de transition, plafond,
effet externe, source absente, veto, retry et déterminisme du journal. Une seule
suite complète est exécutée avant fusion. Aucun replay complet n'est requis pour
valider cette politique.
