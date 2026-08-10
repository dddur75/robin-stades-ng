# Chronos Production Bootstrap V3

Ce runbook active uniquement le control-plane Chronos déjà validé. Il n’autorise
aucun appel football, aucune cote, aucun achat, aucune suppression R2 et aucun
`alembic upgrade head` en production.

## Invariants

- Le checkout visible reste intact; C0 travaille dans le worktree dédié.
- Les workflows à effet restent désactivés individuellement.
- Les workflows de production sont `workflow_dispatch` uniquement et utilisent
  l’Environment `chronos-control-plane-production`.
- `PREFLIGHT`, `MIGRATE` et `VERIFY` sont trois dispatchs distincts.
- `MIGRATE` accepte un unique artifact PREFLIGHT signé et lié aux deux SHA, au
  projet, à la branche production, à la révision 0013 et à la branche recovery.
- La seule commande de migration est
  `python -m alembic upgrade 0014_chronos_control_plane_v2`.

## Avant PREFLIGHT

1. Vérifier que la PR bootstrap a été fusionnée sur `main` et noter son SHA.
2. Vérifier par nom seulement `NEON_API_KEY` et
   `NEON_BOOTSTRAP_DATABASE_URL` dans l’Environment.
3. Vérifier le hold en direct: aucun run autre que le run administratif courant,
   aucun workflow actif DB/R2/fournisseur/schedule/cascade.
4. Dispatcher `PREFLIGHT` avec le SHA `main` exact.

PREFLIGHT réconcilie le host direct de la DSN avec un unique endpoint Neon,
identifie sa branche, crée une branche recovery sans endpoint, exige SSL et la
révision `0013_historical_evidence_index`, puis publie uniquement des JSON
sanitisés. Toute ambiguïté s’arrête avant migration.

## Avant MIGRATE

C0 génère hors Git quatre valeurs avec un générateur cryptographique: trois mots
de passe scoped et un nonce de 32 octets encodé en 64 caractères hexadécimaux.
Chaque valeur est installée par stdin avec `gh secret set --body -`; aucune valeur
ne figure dans argv, les logs, Git ou les artifacts.

Dispatcher ensuite `MIGRATE` une seule fois avec le SHA main exact et le run id
PREFLIGHT. Ne jamais relancer ce mode. En cas de perte réseau, inspecter la
révision et les objets; classer `MIGRATION_CONFIRMED`, `MIGRATION_NOT_APPLIED` ou
`MIGRATION_OUTCOME_AMBIGUOUS`.

Le migrateur est un LOGIN temporaire non-superuser avec `CREATEROLE`, limité au
schéma public et à `alembic_version`. Il crée les groupes via 0014 puis les trois
LOGIN scoped. À la fin il devient `NOLOGIN NOCREATEROLE` et reste présent pour
conserver ownership et relations de grantor.

## Installation des URLs scoped

Télécharger `chronos-bootstrap-output-v3.json`. À partir de ses seuls champs
sanitisés et des mots de passe locaux, construire hors logs:

- `CHRONOS_AUTHORITY_DATABASE_URL`;
- `CHRONOS_RUNTIME_DATABASE_URL`;
- `CHRONOS_READER_DATABASE_URL`.

Installer par stdin dans l’Environment, vérifier uniquement les noms et dates,
puis supprimer les trois secrets `CHRONOS_BOOTSTRAP_*_PASSWORD`. Conserver
`CHRONOS_CONTROL_PLANE_GENERATION_NONCE`.

Dispatcher `VERIFY`; ce mode effectue uniquement des lectures de révision,
d’identité, de membership et d’epoch.

## Canari provider-free

Dispatcher une seule fois le workflow `Chronos Provider-Free Canary V3` avec le
SHA main et le hash de génération publiés. Le payload est synthétique. Le runner
dispose seulement d’un PUT conditionnel et d’un GET exact-key; il ne possède pas
de surface LIST, HEAD ou DELETE. Le deuxième passage doit garder les compteurs
réseau inchangés.

Un 2xx unique produit `CREATED_CONFIRMED`. Un 412 réserve le GET avant lecture et
ne produit `PREEXISTING_CONFIRMED` que pour des octets identiques. Tout résultat
ambigu reste `PUT_COMMITTED_ACTUAL_PENDING`.

## Nettoyage et restauration

Après preuve complète, supprimer `NEON_BOOTSTRAP_DATABASE_URL`. Supprimer
`NEON_API_KEY` lorsque la branche recovery et l’absence de besoin API sont
confirmées. Si sa révocation côté Neon n’est pas prouvable sans ambiguïté,
enregistrer `NEON_API_KEY_REVOCATION_HUMAN_ACTION_REQUIRED` sans invalider le
bootstrap.

Restaurer individuellement seulement les workflows provider-free, sans migration
et utilisant un credential scoped ou aucun credential. Les collectes, captures,
backfills fournisseurs, entraînements dépendants et canaris fournisseurs restent
désactivés.

## Interdictions de reprise

- ne pas relancer MIGRATE;
- ne pas créer un second recovery point pour masquer un résultat ambigu;
- ne pas réintroduire `DATABASE_URL` ou `alembic upgrade head`;
- ne pas supprimer la branche recovery;
- ne pas effectuer un second PUT ou GET;
- ne jamais afficher un secret.
