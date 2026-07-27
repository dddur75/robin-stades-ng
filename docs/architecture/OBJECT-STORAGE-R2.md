# Object Storage R2

## Sémantique de `double_write`

Dans les rapports historiques antérieurs au Jalon 9.1, `double_write=true`
prouve uniquement que le snapshot source est identique avant et après la
migration : aucun fichier supprimé, ajouté ou modifié pendant le lot. Ce champ
ne prouve ni une réplication automatique après chaque collecte, ni une
restauration depuis R2.

Les preuves sont désormais séparées :

- `source_preserved` : conservation locale pendant l'opération ;
- `replication_enabled` : intégration du miroir au flux normal ;
- `verified_objects` et `lag_objects` : état effectif du miroir ;
- `RESTORE_VERIFIED` : restauration isolée réellement relue et rejouée.

## Flux avant le Jalon 9.1

```text
collecte
→ compactage
→ historical-data
→ PostgreSQL
→ artefact GitHub
→ R2 uniquement lors d'un workflow manuel de migration
```

R2 n'intervenait donc pas dans la persistance historique normale.

## Flux après le Jalon 9.1

```text
collecte / calcul historique
→ compactage vérifié
→ historical-data, source principale
→ delta nouveau ou modifié
→ R2, miroir privé vérifié par SHA-256 et taille
→ accusé r2-object-index + r2-replication-latest
→ PostgreSQL
→ artefact GitHub
```

Une panne R2 ne supprime ni ne retarde la publication Git. Le rapport passe à
`LAGGING` ou `CIRCUIT_OPEN`; l'index durable permet de rejouer uniquement le
delta. Les workflows R2 manuels utilisent une persistance légère des fichiers
`storage/r2-*.json`, sans recompacter les 24 000 sources à chaque checkpoint.

## Migration reprenable

`r2-migration-scope.json` fige le périmètre, les tailles, hashes et l'ordre
déterministe. `r2-migration-checkpoint.json` conserve le curseur et les
compteurs cumulés. `r2-object-index.json` distingue les objets `verified` et
`failed`, ainsi que leur dernière action `uploaded` ou `replayed`.

Le workflow `30 - Migration object storage` accepte une taille de lot,
`resume=true`, un nombre de lots à enchaîner et un `start_after` explicite. Une
reprise commence au premier objet non acquitté. Un objet éventuellement écrit
juste avant une interruption est relu et classé `replayed`; aucune duplication
ni suppression n'est requise.

L'audit intégral utilise `r2-audit-checkpoint.json`, distinct du checkpoint
d'upload. En mode audit, chaque objet doit déjà exister : le workflow exécute
uniquement `HeadObject` et `GetObject`, sans `PutObject`. Toute absence,
métadonnée SHA-256 divergente, taille ou contenu divergent fait échouer le lot.

Les rapports de migration, checkpoints et index sont exclus du périmètre qu'ils
décrivent. La suppression n'est pas exposée par `ObjectStorageAdapter`.

## Réplication continue

Après chaque persistance historique normale, le miroir compare le snapshot
courant à `r2-object-index.json` et sélectionne uniquement les clés absentes ou
dont le hash ou la taille a changé. Chaque objet est :

1. contrôlé par `HeadObject` ;
2. envoyé seulement si nécessaire ;
3. relu par `GetObject` ;
4. validé par taille et SHA-256 ;
5. acquitté dans l'index durable.

Les erreurs temporaires `429`, `5xx`, `SlowDown` et `RequestTimeout` disposent
de deux retries bornés. Trois échecs consécutifs ouvrent le circuit breaker.
Git et PostgreSQL restent disponibles; le lag est explicite et rejouable.

## Restauration

Le workflow `31 - Test restauration R2` crée un répertoire temporaire vide et
sélectionne JSON, Parquet, CSV, manifeste et checkpoint. Les objets sont
téléchargés sans écraser `data/historical`, puis leurs hashes et tailles sont
comparés. Le Parquet est ouvert, un bundle est rejoué sans fournisseur et les
doublons métier sont contrôlés.

Le statut `RESTORE_VERIFIED` exige zéro perte, zéro mismatch, zéro doublon,
zéro mutation source et `provider_calls=0`.

## Client et sécurité

Le client utilise l'endpoint global
`https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com` avec `region_name="auto"`.
Seuls `404`, `NoSuchKey` et `NotFound` signifient objet absent. `401`, `403`,
les erreurs réseau et les mismatches restent bloquants.

`historical-data` demeure la source principale pendant toute la transition.
R2 est un miroir privé. `PRODUCTION_LOCKED`, `REAL_BETS=false` et
`NO_BET_DEFAULT=true` restent invariants.

## Mesures de référence

Le périmètre figé le 26 juillet 2026 contient 25 422 fichiers et
710 072 047 octets. Le benchmark d'écriture cumulatif de 250 fichiers a produit
225 uploads, 25 replays, 250 vérifications distantes et 725 opérations R2 en
246,660 s. Son replay a produit 0 upload, 250 replays, 250 vérifications et
500 opérations en 172,533 s. Les deux runs ont zéro retry, mismatch, objet
manquant, mutation ou suppression.

La projection restante monolithique est d'environ 400,6 minutes de traitement
objet; elle excède donc le timeout de 120 minutes. Six segments de 5 000 objets
au plus sont retenus, avec une projection centrale totale d'environ
419,6 minutes et une projection haute d'environ 519,7 minutes. L'audit intégral
est projeté à environ 296,2 minutes au centre et 365,5 minutes en hypothèse
haute.

La restauration réelle a validé sept fichiers multi-formats et le replay de
3 128 fichiers de bundle, sans fournisseur, perte, doublon ni mismatch. La
réplication continue a d'abord exposé un lag de 50 objets, puis l'a résorbé :
804 objets attendus et vérifiés, `lag_objects=0`, `status=SYNCED`.

La migration complète a été exécutée en six runs bornés. Son checkpoint
`COMPLETE` totalise 24 627 uploads, 471 replays et 324 objets préalablement
acquittés par l'index, pour 25 422 objets vérifiés. Les compteurs d'intégrité
sont tous nuls : mismatch de hash ou taille, objet manquant, mutation de
source et suppression.

L'audit utilise le snapshot courant comme contenu attendu. Si un fichier
mutable est légitimement régénéré après son upload, sa métadonnée R2 ne
correspond plus : l'audit s'arrête sans écrire, la réplication continue publie
le delta, puis le checkpoint d'audit reprend exactement sur cet objet. Cette
séquence constitue le traitement attendu d'un lag réel, et non une tolérance
du mismatch.

La preuve réelle a suivi cette séquence. Après cinq segments de 5 000 objets,
le sixième a signalé une readiness modifiée. Le run `30238268175` a répliqué
23 deltas, atteint 816/816 objets vérifiés et `lag_objects=0`. Le run
`30239697041` a repris à l'index 25 399 et fermé l'audit à 25 422/25 422 :
23 `HeadObject`, 23 `GetObject`, aucun `PutObject`, aucun mismatch, objet
manquant, retry, mutation ou suppression.

Le champ `current_source_lag=21` du rapport d'audit désigne les clés apparues
après le gel du scope et non un retard du miroir. Elles sont hors du
dénominateur historique 25 422 mais incluses dans le snapshot physique courant
de la réplication. La preuve opérationnelle de retard est
`r2-replication-latest.json` : 816 objets attendus, 816 vérifiés,
`lag_objects=0`.

## Capacité et coût

Le scope de 710 072 047 octets représente environ 0,710 Go décimal. La
[tarification officielle Cloudflare R2](https://developers.cloudflare.com/r2/pricing/)
inclut 10 Go-mois, un million d'opérations de classe A et dix millions
d'opérations de classe B par mois. La migration et son audit restent très
inférieurs à ces seuils; le coût incrémental attendu est donc nul si le compte
n'a pas déjà consommé son quota gratuit mensuel.

À titre conservateur hors quota gratuit, 0,710 Go-mois, environ 25 500
opérations de classe A et environ 103 000 de classe B représentent moins de
0,20 USD aux tarifs Standard publiés. Les opérations de réplication continue
s'ajoutent seulement pour les deltas.
