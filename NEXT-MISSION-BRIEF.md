# Prochaine mission — P0 E1 Real Fixture Proof V1

## Problème restant

Le contrat P0 définit exactement 480 cellules (`5 compétitions × 6 saisons × 16 familles`), mais aucune cellule ne possède encore de census empirique autoritatif. La preuve actuelle ferme E0 seulement : grains, dimensions, taux, erreurs et gates sont déterministes ; `0/480` cellule est empiriquement fermée et `CALENDAR_FATIGUE` reste à `0/17`.

Deux exécutions identiques du workflow Deep Data Cockpit ont en outre échoué sur `provenance des identités non vérifiée`. Une troisième relance sans changement d’architecture est interdite.

## Preuves acquises

- PR #26 fusionnée et fondation vérifiée, score effectif 95/100 après CI ;
- 2 321 payloads et 2 321 reçus R2 déjà présents dans la preuve PR #26 ;
- 2 023 144 lignes normalisées, sans mismatch de replay constaté ;
- 1 067 cellules d’union observée, dont 0 cellule avec census P0 autoritatif ;
- catalogue des 16 grains et contrat P0 compact prouvant 480 cellules en mémoire ;
- contrats séparés pour `scope_completion`, `normalization_integrity` et `content_presence` ;
- classifieur d’absence fail-closed et états `EMPTY_VALID` distincts de zéro ;
- niveaux E0–E4, packs bornés et gates fonctionnels ;
- sources compactes serveur et Desk P0 validés sans fuite client.

## Priorité unique

Produire une **preuve E1 sur exactement 10 fixtures P0 réelles**, à partir des payloads/reçus déjà autorisés, afin de valider la chaîne de census et la provenance des identités sur un échantillon borné.

E1 est une preuve d’échantillon. Elle ne ferme aucune cellule P0 complète, ne débloque aucune hypothèse et n’autorise pas E2.

## Sélection déterministe

Sélectionner exactement les 10 premières fixtures chronologiquement complètes d’un même couple compétition-saison P0 qui satisfont toutes les conditions suivantes :

1. fixture, compétition, saison, équipes domicile/extérieur et kickoff sont reliés à un reçu vérifiable ;
2. les identités sont canoniques et leur provenance est explicite ;
3. aucun payload ni reçu nouveau n’est nécessaire ;
4. l’ordre est `kickoff_utc`, puis `fixture_id` comme départage déterministe.

Publier le manifeste de sélection avant tout calcul E1. Si moins de 10 fixtures satisfont ces critères, arrêter avec `PARTIAL` ; ne pas élargir silencieusement le scope.

## Livrables attendus

- contrat de preuve E1 et manifeste exact des 10 fixtures ;
- registre de provenance des identités avec hashes et reçus ;
- census E1 par fixture, famille et grain ;
- trois taux séparés avec numérateurs et dénominateurs ;
- classification reçue / vide valide / invalide / ambiguë ;
- rapport d’écarts et objections ;
- tests Golden et mutations fail-closed ;
- synthèse compacte serveur du résultat E1, sans payload brut ni liste de cellules répétitives ;
- mise à jour du Desk indiquant `E1 sample`, sans changer `0/480` ;
- PR brouillon non fusionnée et dossier de gouvernance append-only.

## Interdictions

- 0 appel fournisseur, 0 achat, 0 crédit cotes ;
- 0 replay nouveau, 0 écriture ou suppression R2, 0 requête SQL distante ;
- aucun scan général, E2, E3, E4, hypergraphe ou backtest ;
- aucun ROI, classement, stratégie, pari, promotion ou publication ;
- aucune modification du checkout d’accueil protégé ;
- aucune troisième relance de l’architecture Deep Data Cockpit inchangée.

## Branche à sélectionner

Ne démarrer qu’après revue et fusion explicite de la PR `Historical Coverage Denominator Closure V1 — grains, preuves et readiness P0`.

Depuis le commit de fusion correspondant sur `main`, créer :

```text
codex/p0-e1-real-fixture-proof-v1
```

## Gate de sortie

Verdicts possibles :

```text
P0_E1_REAL_FIXTURE_PROOF_READY_SAMPLE_ONLY
P0_E1_REAL_FIXTURE_PROOF_PARTIAL
```

Même en cas de succès, conserver :

```text
P0 empirical cells closed = 0/480
CALENDAR_FATIGUE ready = 0/17
E2 = NOT_AUTHORIZED
HYPERGRAPH = NOT_OPENED
```
