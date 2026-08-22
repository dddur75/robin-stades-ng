# Bounded Multi-League Live Canary Capability — livraison successor V2

## Statut livré

La mission de livraison et de gouvernance
`BOUNDED_MULTI_LEAGUE_LIVE_CANARY_CAPABILITY_SUCCESSOR_V2` reprend sur la base
corrigée de `main` la capacité technique
`BOUNDED_MULTI_LEAGUE_LIVE_CANARY_CAPABILITY_V1`. Le suffixe V1 des contrats,
builders, artefacts et points d'entrée décrit donc la version de la capacité
livrée ; V2 décrit exclusivement sa succession de livraison. Cette livraison
ajoute une capacité logicielle live, pas une autorisation live.

```text
CAPABILITY_AVAILABLE = TRUE
LIVE_DEFAULT_STATE = DEFAULT_DENY
REAL_OWNER_AUTHORIZATION = ABSENT
REAL_ACTIVATION = ABSENT
PROVIDER_CALLS_DURING_DELIVERY = 0
REAL_SECRET_READS_DURING_DELIVERY = 0
REAL_BATCH = NOT_EXECUTED
REAL_SNAPSHOT = NOT_CREATED
```

Le chemin live ne devient utilisable qu'avec un acte propriétaire externe,
immuable et séparément épinglé, puis une activation réduite liée au SHA exact de
`main` après fusion. Aucun de ces artefacts réels n'est versionné dans Git.

## Périmètre absolu

La capacité refuse toute valeur en dehors de cette allowlist exacte :

```text
soccer_spain_la_liga
soccer_france_ligue_one
soccer_epl
soccer_italy_serie_a
soccer_germany_bundesliga
```

La région est exactement `eu`. Un item choisit explicitement l'un des ensembles
de marchés `h2h`, `totals` ou `h2h,totals`. Il n'existe ni wildcard, ni préfixe,
ni ajout implicite après scellement.

## Autorité externe et DAG de hashes

`OwnerAuthorizationV1` enregistre l'identité du dépôt, le SHA autorisé, les
plafonds, la fenêtre temporelle, les empreintes OS des racines dépôt, capture et
contrôle temporaire, le SHA-256 du binaire Git approuvé, une adresse IP
fournisseur globale canonique, un nonce et le hash SHA-256 de l'artefact
propriétaire externe. Le runtime exige que le pin Git et le pin d'autorisation
soient aussi fournis séparément au CLI ; il refuse le binaire avant exécution si
le pin Git ne correspond pas à la valeur couverte par le hash d'autorisation. Il
vérifie ainsi l'intégrité et la provenance attendue, mais ne prétend pas fournir
une signature cryptographique : l'authenticité de l'acte propriétaire et
l'exclusivité des ACL locales restent des frontières externes.

Le scellement évite explicitement tout cycle auto-référent :

```text
OwnerAuthorization.canonical_authorization_hash
  -> ActivationEnvelope.activation_scope_sha256 (sans plan_sha256)
  -> LivePlan.canonical_plan_hash
  -> ActivationEnvelope.plan_sha256
  -> ActivationEnvelope.canonical_activation_hash
```

L'activation finale ne peut que réduire les sports, la région, les marchés, la
fenêtre et les budgets de l'autorisation. Elle cible un sport, un SHA, une région,
un ensemble exact de marchés et un plan. Chaque item de plan est ordonné,
content-hashé, borné à une requête et lié au fingerprint public de la requête.

Les modèles sont immuables, `extra=forbid` et reparsés à la frontière d'exécution.
Un objet Pydantic construit sans validation ou modifié par copie ne contourne pas
les hashes canoniques.

Le preflight Git accepte uniquement un binaire absolu dont le SHA-256 correspond
à la fois au pin CLI séparé et au champ couvert par l'OwnerAuthorization ; son
identité et ses octets sont revalidés à chaque appel. Un index v2 temporaire
assaini refuse les flags `assume-unchanged`/`skip-worktree`, les modes et chemins
hors contrat, puis met à zéro ses champs de stat. Après le contrôle du diff
staged, le binaire épinglé exécute `update-index --really-refresh` uniquement sur
cet index temporaire et deux `diff-files --quiet` autour du scan des fichiers non
suivis. Ce choix reconnaît un checkout Windows CRLF propre sous la politique
`core.autocrlf=true` tout en détectant une mutation ordinaire ; aucun filtre Git
externe n'est admis. Le dépôt et la racine temporaire doivent être locaux,
existants, hors chemin synchronisé et soumis à une ACL propriétaire exclusive
qui exclut tout mutateur concurrent pendant le preflight. Leurs empreintes OS
sont couvertes par l'autorisation et revalidées avant et après les opérations ;
la racine temporaire doit en plus être hors Git et sans recouvrement avec le
dépôt ou la racine de capture.

## Ordre d'exécution futur

L'exécuteur impose l'ordre logique demandé et ajoute deux durcissements sans
élargir l'autorité : une validation read-only de la racine avant toute écriture,
puis sa revalidation à l'étape prévue ; et une revendication durable du dispatch
avant la lecture du secret.

1. valider le mode live explicite ;
2. reparser tous les contrats et vérifier le SHA Git exact avec un environnement
   Git minimal sans secret, proxy, hooks ni verrou optionnel ;
3. vérifier le pin externe et l'OwnerAuthorization ;
4. vérifier l'ActivationEnvelope, ses TTL et sa réduction de portée ;
5. vérifier la portée sport/région/marchés ;
6. vérifier le plan, l'ordre et l'item ;
7. valider en lecture seule l'identité de la racine externe ;
8. acquérir la lease one-shot par création exclusive ;
9. réserver pessimiste­ment requête et crédits dans le ledger interprocessus ;
10. revalider la racine approuvée ;
11. construire et scanner le matériel public de requête ;
12. prévalider le transport TLS strict ;
13. armer durablement le dispatch, revalider SHA/TTL/racine/autorité et toutes les
    arêtes lease-budget-bindings ;
14. consommer atomiquement le permit de dispatch ;
15. lire exactement une fois `THE_ODDS_API_KEY`, puis dispatcher exactement une
    fois ;
16. horodater la première observation et obtenir octets, statut et en-têtes
    sanitizés ;
17. calculer le SHA-256 brut, écrire l'intake receipt, puis le raw content-addressed
    avant tout parse ;
18. parser, contrôler schéma/sport/marchés, normaliser et écrire le final receipt
    puis le manifest ;
19. réconcilier le quota et le budget ;
20. écrire l'attempt receipt, rejouer offline sans réseau ni secret, écrire le
    LiveExecutionReceipt terminal et rendre l'item définitivement non rejouable.

Toute lease existante, même expirée, est terminale. Une mort après réservation,
armement, consommation du permit ou dispatch conserve les tombstones et le budget
pessimiste ; elle n'ouvre jamais un retry réseau automatique.

## Transport HTTPS strict

`StrictHttpsTransport` utilise une connexion HTTPS directe injectable. Il impose
`GET`, le host exact `api.the-odds-api.com`, le port 443, la vérification du
certificat et du hostname, zéro redirect et zéro retry. L'adresse réseau est le
littéral IP global canonique couvert par l'autorisation : le transport ouvre un
socket IPv4/IPv6 directement, n'appelle aucune résolution DNS, refuse tout peer
différent, tout en conservant le SNI TLS et le header `Host` canoniques. Il
refuse les proxys hérités, `SSLKEYLOGFILE`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, les
contexts TLS avec key logging, les doublons d'en-têtes sensibles, une réponse
compressée et tout écho du secret dans le corps ou les en-têtes.

Le secret doit être un token ASCII borné. Il n'entre dans aucun contrat public,
fingerprint, log, chemin, exception, receipt ou manifest. Un deadline monotone
unique est resserré avant chaque phase de connexion TCP, handshake TLS, requête,
en-têtes et chaque lecture du corps. Aucun failover d'adresse n'est permis. Une
rotation d'adresse fournisseur exige donc un nouvel acte propriétaire et une
nouvelle activation ; elle n'est jamais découverte automatiquement.

## Stockage, preuve et replay

La racine réelle doit être explicitement approuvée, locale, hors Git et hors
chemin synchronisé connu. Les chemins UNC, drives Windows non fixes, composants
symlink/junction/reparse, hardlinks de fichiers mutables et mounts Linux hors
allowlist locale sont refusés. L'identité de la racine approuvée est revalidée aux
frontières d'I/O.

Les écritures immuables utilisent une création finale exclusive et un `fsync` ;
elles ne laissent pas de fichier temporaire raw non gouverné. Les marqueurs de
lease, d'autorité, d'armement et de permit sont conservés. Le ledger budget est
verrouillé entre processus, append-only, chaîné par hash et distingue réservation,
armement, consommation et réconciliation.

Le replay live recharge et recoupe les deux copies des receipts, le canonical
request, le fingerprint, la portée sport/marchés, la lease, les deux bindings
d'autorité, le marker d'armement, le budget, le permit consommé, la lineage, le
raw SHA, le schéma, le hash normalisé, le manifest et le compte d'observations.
Son contrat fixe `network_calls = 0`, `provider_calls = 0` et
`secret_reads_count = 0`.

## Portée de l'échelle et de la CI

Cette mission ne lance aucun workload live : son plafond `E1` borne la livraison
de capacité et ne constitue pas une permission d'exécution fournisseur. Les jobs
CI ciblés ont un timeout d'infrastructure de douze minutes afin d'inclure
l'installation et les preuves Windows. Le plafond explicite de quarante minutes
porte sur le job repository-wide `tests` du run exact-head, pas sur la durée
murale du DAG séquentiel complet ; ces jobs ne sont pas présentés comme un
workload E1 de cinq minutes.

Les limites `production_lines_max=1000` et `test_lines_max=2000` du rapport de
contrôle V3.1 ont historiquement été appliquées au control-plane Council V3.1.
Cette capacité de domaine ne revendique donc pas `WITHIN_1000_2000`. L'absence de
champ de portée dans la policy JSON reste une ambiguïté P2 consignée par C2. Si
l'intention propriétaire est de rendre ces plafonds universels, la présente
livraison doit être reclassée `FAIL_AND_REDESIGN` plutôt qu'auto-dérogée.

## Frontières résiduelles déclarées

Les racines approuvées de dépôt, contrôle temporaire et capture doivent être
contrôlées par un principal OS dont les ACL empêchent un autre processus de les
renommer, remplacer ou muter pendant les opérations. Les informations de
drive/mount et les identités de répertoire fournies par l'OS sont prises comme
attestation ; une plateforme non prise en charge échoue fermée. Le runtime
revalide les empreintes mais ne prouve pas lui-même la politique ACL : cette
hypothèse propriétaire est explicite et n'est pas présentée comme une garantie
cryptographique.

## Action propriétaire future, séparée

Après fusion seulement, un propriétaire peut décider de créer hors Git une
OwnerAuthorization liée au SHA final de `main`, aux trois empreintes locales, au
binaire Git et à l'IP fournisseur approuvée, de fournir son artefact et son pin
par deux canaux séparés, puis de créer une activation et un plan one-shot réduits.
Cette livraison n'effectue aucune de ces opérations et ne les déclenche jamais
automatiquement.
