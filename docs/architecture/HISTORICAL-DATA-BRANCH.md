# Registre durable `historical-data`

`shadow-data` reste le registre exclusif du prospectif live.
`historical-data` contient les manifests, checkpoints, bundles, Parquet,
preuves, datasets, features, modèles et backtests historiques.

La migration initiale a réutilisé l’arbre Git historique exact du commit
`e56e1aa7f49f561554add7e34de056d1d5229495` :

| Mesure | Avant (`shadow-data`) | Après (`historical-data`) |
|---|---:|---:|
| Fichiers | 3 180 | 3 180 |
| Octets | 16 184 894 | 16 184 894 |
| Manquants | — | 0 |
| Hashes modifiés | — | 0 |
| Appels fournisseur | — | 0 |
| Quota consommé | — | 0 |

L’ancien arbre n’est pas supprimé. Le marqueur
`historical/MIGRATED_READ_ONLY.json` interdit de le considérer comme cible
d’écriture. Toute suppression future exige une opération distincte.

Les actions restaurent et publient désormais `historical-data`. Une publication
non-fast-forward effectue au plus trois fetch/rebase/push. Le groupe
`historical-state` sérialise les traitements historiques ; le live conserve
`shadow-state`.
