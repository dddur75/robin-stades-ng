# ADR-0001 — Fondation incrémentale

Date : 2026-07-24
Statut : accepté

## Contexte

Le dépôt contient déjà des calculs point-in-time, des expériences statistiques,
des pipelines et un dashboard statique. Il manque les frontières de stockage, les
contrats de données et l'état transactionnel attendus d'une plateforme durable.

## Décision

Faire évoluer le projet en couches :

1. `providers` conserve les réponses brutes immuables avec manifeste ;
2. `normalization` traduit les schémas fournisseurs vers des entités internes ;
3. PostgreSQL conserve identités, versions et décisions transactionnelles ;
4. Parquet conserve snapshots et datasets analytiques versionnés ;
5. les modules actuels de `moteur` sont enveloppés puis migrés sans réécriture
   destructive ;
6. prédictions, candidats, rejets et règlements deviennent append-only ;
7. l'interface lit des vues contractuelles, jamais les fichiers bruts directement.

## Conséquences

- les preuves actuelles restent disponibles ;
- une source peut être remplacée derrière un adaptateur ;
- les migrations sont plus lentes qu'une réécriture totale, mais vérifiables ;
- les résultats historiques doivent être requalifiés selon la provenance et
  l'horodatage disponibles ;
- aucun résultat n'est promu en production pendant la migration.
