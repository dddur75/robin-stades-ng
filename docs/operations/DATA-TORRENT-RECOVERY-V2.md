# Data Torrent Recovery V2

Ce runbook décrit l’unique chemin Recovery V2. Il ne réactive aucune autorité,
aucun run ni aucun reçu V1.

## Autorité immuable

- mission : `data-torrent-recovery-v2` ;
- base propre : `fcbf2a4fedd413251ee9da94ec2a444c6b917e63` ;
- manifeste brut :
  `ced1b867faa3ae57911d169f5c1edbd0db02a891ac46ccc080de7397076d349f` ;
- manifeste canonique :
  `e6ae2bcc2ea6a8cbd8a552321235f384b6776e935c259a0516ce1405ac2871b2` ;
- directive propriétaire :
  `ff2e45ff7c6490919aa86900669c306e1d25c710f15db27f7c70861f1246bf31` ;
- contrat d’effets brut :
  `80bae46bbf0c4af0b223476265b283628e4950f298d09f5287ad450b367da7dc` ;
- contrat d’effets canonique :
  `59c1c91071e8217b198de953cbc48a76e182234bc8e69f065bc14da1c496c7ee` ;
- admission des effets avant `2026-09-06T12:26:58Z`, afin de réserver les
  1 200 secondes terminales avant l’épuisement du budget mission ;
- expiration à `2026-09-13T23:59:59Z`.

Le `source_hash` est l’empreinte de la directive propriétaire. Il n’est ni le
SHA de départ ni l’empreinte du manifeste.

## Séquence autorisée

La seule chaîne est :

```text
E1 engineering + quatre revues indépendantes
→ SAFE V2 exact-head
→ PR-A et merge commit normal
→ SAFE V2 post-merge
→ neutralisation fast-forward de la branche fournisseur historique
→ E1 quarantaine post-merge des quatre workflows V2
→ E2 R1 Recovery Identity V2
→ E2 R2 Durable Identity Seal V2
→ E3A R3 Production Preflight V2
→ E3A R4 Four Runtime Bindings
→ E3B R5 Migrate 0015 si absente
→ E3B R6 Verify 0015
→ E4 R7 Live Once
→ E4 R8 Replay 100 dans le même processus
→ QA terminale
→ PR-C probatoire
```

Chaque merge autorisé est un merge commit à deux parents dont le premier parent
est exactement le `github.event.before` du push post-merge. Immédiatement avant
chaque commande, relire le PR une seule fois avec
`gh pr view --json headRefName,headRefOid,baseRefName,mergeable,state` et exiger
la branche source attendue, `headRefOid` byte-identique au SHA SAFE V2 observé,
`baseRefName=main`, `mergeable=MERGEABLE` et `state=OPEN`. Toute dérive, y
compris un nouveau commit après SAFE V2, est un hard stop avant l’écriture de
merge ; aucune file d’auto-merge n’est admise. Après cette comparaison, utiliser
exclusivement l’une des commandes correspondantes (PR-B seulement si le
correctif conditionnel est nécessaire) :

```text
gh pr merge "$PR_A_NUMBER" --repo dddur75/robin-stades-ng --merge --match-head-commit "$PR_A_HEAD" --subject "[DATA_TORRENT_RECOVERY_V2] PR-A" --body ""
gh pr merge "$PR_B_NUMBER" --repo dddur75/robin-stades-ng --merge --match-head-commit "$PR_B_HEAD" --subject "[DATA_TORRENT_RECOVERY_V2] PR-B" --body ""
gh pr merge "$PR_C_NUMBER" --repo dddur75/robin-stades-ng --merge --match-head-commit "$PR_C_HEAD" --subject "[DATA_TORRENT_RECOVERY_V2] PR-C" --body ""
```

`--auto`, `--squash`, `--rebase`, `--admin`, toute mise à jour non
fast-forward et le push direct sur `main` sont interdits. Le sujet exact
déclenche le scope guard Recovery V2 du
SAFE V2 post-merge ; une autre forme n’est pas autorisée.

Après ce SAFE V2 post-merge exact vert et avant la quarantaine E1, la branche
historique `codex/jalon-12-prospective-deep-data-observatory` doit encore pointer
exactement sur `START_SHA`. Une seule écriture distante est admise pour la faire
avancer en fast-forward vers le SHA exact de `main`; elle consomme le
slot `ENGINEERING_REQUIRED` déjà autorisé, n’ouvre aucun PR additionnel et ne
peut être rejouée. Utiliser exclusivement le contrôleur portable qui vérifie
les deux refs, prouve localement l’ascendance fast-forward et réserve un reçu
one-shot durable avant l’unique push ordinaire :

```text
python scripts/dispatch_data_torrent_recovery_v2_stage.py --neutralize-provider-branch --main-sha "$MAIN_SHA" --receipt .torrent/release/recovery-v2-provider-neutralization.json
```

Le contrôleur emploie exactement `git push --porcelain` sans `--force`, sans
`--force-with-lease` et sans refspec `+`. L’ascendance `START_SHA → MAIN_SHA` et
l’ancien SHA distant exact sont prouvés avant la réservation; le serveur doit
refuser toute course qui rendrait la mise à jour non fast-forward. Un SHA source
inattendu, une divergence, un rejet ou une réponse ambiguë produit un arrêt sans
retry. Cette branche ne doit jamais avancer avant le SAFE V2 post-merge vert.

Chaque étape exige son prédécesseur exact. Les workflows de production restent
désactivés. Pour R1, R2, R3, R5, R6 et R7 seulement : vérifier la file globale,
passer le pré-gate local Council exact, activer le workflow exact, envoyer une
seule fois le dispatch `attempt=1`, le désactiver immédiatement, puis corréler
le run. Ces trois mutations ne sont autorisées que par
`scripts/dispatch_data_torrent_recovery_v2_stage.py` : ce contrôleur réserve
atomiquement le reçu one-shot, appelle
`validate_data_torrent_recovery_v2_authority(scale_stage=...)` puis le full-hold
avant tout `enable` ou `dispatch`, et effectue chaque mutation dans un enfant
proxy-free tuable, sans redirection ni retry. Une réponse ambiguë consomme
l’étape, tente encore la désactivation de quarantaine et interdit tout retry.
Les deux full-holds, qui incluent le job SAFE V2 `SCOPE_GUARD_PASS`, doivent être
byte-identiques ; l’attestation du prédécesseur, l’ordinal exact des dispatches
et la ref `main` sont revérifiés avant `ENABLE`. Le dispatch utilise `ref=main`,
`return_run_details=true` et la version REST GitHub `2026-03-10`; son identifiant
provient de la réponse 200, sans polling. L’enfant de mutation revalide le schéma
fermé de cette preuve, les deux holds identiques, leur empreinte, les inputs et
leur hash avant `ENABLE` et `DISPATCH`. Tout identifiant de run est un entier
décimal canonique positif d’au plus 18 chiffres.

Les lectures GitHub d’attestation, d’artefact et de ref `main` passent uniquement
par un processus privé borné à 65 secondes (travail 55, terminaison 5) et une
réponse maximale de 10 MiB. Les lectures API sont limitées à `api.github.com`.
Le téléchargement d’archive accepte au plus une redirection 302 validée vers
`*.actions.githubusercontent.com` ou `*.blob.core.windows.net`, sans transmettre
le bearer token au second hôte. Proxy, redirection automatique, redirection
supplémentaire et retry sont désactivés. Les quatre workflows V2 ne contiennent
aucun `gh api` ambiant et matérialisent exactement dix lectures `main` via ce
transport borné.

Chaque étape à effets R1, R2, R3, R5, R6 et R7 démarre son propre enfant sous
une échéance absolue posée au premier step du job. Un reçu d’échec assaini aux
plafonds conservateurs est créé avant l’enfant ; l’enfant écrit dans un candidat
séparé, sans retry. Seul un candidat sémantiquement valide et cohérent avec son
code de sortie remplace atomiquement le fallback. Les délais réservent au moins
120 secondes du timeout externe pour TERM/KILL, validation, fsync et publication.
Un timeout, un signal, un JSON tronqué ou une terminaison non confirmée conserve
le fallback `UNKNOWN_OR_UPPER_BOUND` et interdit la progression.

Le champ `terminalization_completed_at` a une frontière précise : il est
échantillonné après le retour du terminalizer distant et après la validation
sémantique de son artefact ainsi que du cache local byte-exact, mais avant la
publication du reçu local de succès. Il doit être postérieur ou égal au
`terminal_run.updated_at` et ne jamais dépasser le
`controller_terminalization_deadline_epoch`. La publication et le `fsync` du
journal local qui suivent ne créent aucune autorité ni aucun effet externe ; ils
peuvent donc achever la persistance locale après cette échéance. Si l’horloge est
déjà au-delà de l’échéance après une terminalisation autrement valide, le reçu
reste `FAIL_AND_STOP`, sans champ de succès et sans nouvelle invocation.

Tous les journaux et bundles locaux suivent une marche de parents ancrée dans la
racine du dépôt. Les candidats temporaires restent dans un parent déjà vérifié,
la publication conserve le descripteur parent POSIX ou revalide l’identité du
handle cible Windows, puis resynchronise l’ascendance. Une publication de
répertoire revalide l’ensemble exact des chemins et empreintes avant promotion.
Toute substitution de parent, jonction/reparse point, lien, renommage concurrent,
dérive d’empreinte ou échec de vidage refuse la publication ; aucun nettoyage
récursif non ancré n’est autorisé.

Le scope guard compare toujours la base immuable au HEAD exact avec renames
désactivés. Il lie l’allowlist gelée par l’empreinte
`616804d298ae0c1e48717c02a0ca023c5cf6b94d4b054b9d288d94d71c119244`
et la portée PR-A par
`40a705e765430aaba6e16530e219fe21d2c63305f657e063bc96acef92eeffb4` ;
modifier la matrice ne peut donc pas élargir la portée du même candidat.

Après le SAFE V2 post-merge et avant R1, une invocation E1 réserve exclusivement
`.torrent/release/recovery-v2-postmerge-quarantine.json`, accepte seulement les
états initiaux `active` ou `disabled_manually` des quatre nouveaux workflows,
puis tente exactement une fois chaque `DISABLE` nécessaire, dans l’ordre gelé.
Avant même de créer ce reçu, le contrôleur exige le record Council 200, les
preuves locales post-196 et post-198 corrigées, les quatre vagues de revues
intactes et tout suffixe Council positif. Le token GitHub non vide et borné est
également validé avant la réservation one-shot.
Elle borne ses lectures GitHub à 25 et ses PUT de désactivation à quatre ; aucun
`ENABLE`, dispatch ou retry n’est permis. Un post-hold live doit ensuite prouver
les huit workflows de production désactivés. Le reçu local est un journal
one-shot de provenance, jamais une preuve autoritative sans les deux full-holds
GitHub live refaits par R1. Une désactivation de nettoyage déjà engagée reste
joignable si l’horloge, le Council ou un verrou dérive après admission : sa cible
est fermée aux quatre workflows et elle ne peut qu’abaisser la capacité. Chaque
désactivation est précédée de son reçu de progression durable. Une réponse
ambiguë est enregistrée, puis chaque autre workflow initialement actif est tenté
exactement une fois tant que le journal de progression reste durable ; le résultat
agrégé est ensuite `FAIL_AND_STOP`, sans retry. Une seconde invocation est refusée
avant GET.

La neutralisation de branche fournisseur et la quarantaine post-merge ont
chacune une échéance locale absolue distincte de 300 secondes, conforme aux deux
timeouts E1 de cinq minutes du contrat. Les GET, holds, push et désactivations de
chaque opération reçoivent exactement la même échéance ; aucun chemin ne peut la
porter à 1 200 secondes.

Le gel de revue et le gel runtime sont deux projections distinctes. La première
exclut le ledger, le graphe de preuves et les vingt rapports détenus par les
reviewers : la vague initiale, la vague de correction CI, la correction locale
post-196 et la correction statique/runtime post-198, chacune composée de quatre
rapports indépendants et d’une synthèse finale. La seconde inclut les vingt
rapports mais exclut les deux surfaces
append-only, ledger et graphe de preuves.
Cette séparation évite que le hash du record Council dépende d’un graphe qui
doit lui-même contenir ce hash. Le test Council lie séparément et exactement
chaque nœud du graphe au record du ledger.
Les deux projections décodent strictement chaque fichier texte en UTF-8,
refusent BOM, NUL et retour chariot isolé, normalisent uniquement CRLF vers LF,
puis lient le SHA-256 des octets LF. Le même candidat produit ainsi la même
empreinte sur Windows et Linux sans accepter de dérive de contenu.

La seule suite complète locale exécutant des tests est conservée au record 195 :
`3744 passed, 35 skipped, 29 failed`, sans tentative réseau non approuvée. Vingt-six
échecs provenaient uniquement de la matérialisation CRLF Windows et ont disparu
après normalisation LF byte-identique à l’index Git. Les trois gardes de
compatibilité historiques restantes sont corrigées au plus petit périmètre et
validées par tests ciblés ; la suite complète n’est pas rejouée, conformément à
la politique V3.1.

La revue pré-commit postérieure au record 198 a ensuite fermé, dans une seule
correction E1 sans effet externe, neuf faux positifs Bandit B105 et huit défauts
d’opérabilité/livraison bornés : cache et handoff R3→R4→R5, admission temporelle
R4, deux délais E1, deux préconditions locales vérifiées trop tard et merge sans
CAS du head exact. Le record 200 et sa quatrième vague de revues remplacent le
record 198 comme release active sans réutiliser PR-B.

R4 est une invocation locale unique avec quatre écritures de secret dans l’ordre
gelé. `gh 2.96.0` ne sert qu’à lire la clé publique et chiffrer localement sans
stockage ; le PUT GitHub exact est effectué par un enfant privé borné. La
présence du reçu refuse une deuxième invocation avant attestation ou écriture.
Son entrée obligatoire est l’enveloppe canonique laissée par R3 :
`.torrent/release/recovery-v2-predecessor-cache/production-preflight-v2.json`.
R4 en valide le schéma fermé, le base64, l’attestation, le SHA des octets bruts,
le HEAD, le run ID et le reçu contrôleur R3 final
`TERMINAL_SUCCESS_CONFIRMED` avant de réserver son propre reçu. Il ne crée aucun
fichier preflight brut auxiliaire. Le token GitHub et le binaire `gh` gelé sont
eux aussi vérifiés avant cette réservation.
Le reçu signé R4 conserve le SHA-256 exact de ce journal contrôleur R3 ; la
preuve terminale le compare aux octets copiés du journal. Un autre chemin de
cache, même byte-identique, est interdit.
Son plafond externe de dix minutes part dès l’entrée de l’invocation. R4 ne
refait aucune attestation réseau : il réutilise uniquement l’attestation R3
immuable, déjà liée byte-exact au cache et au reçu contrôleur terminal. Après chaque
inventaire de concurrence, l’expiration du PREFLIGHT et les échéances monotone
et murale sont revalidées avec la marge complète de l’écriture. Elles le sont à
nouveau après chiffrement et dans l’enfant privé juste avant le PUT.
Après validation locale du cache, un full-hold puis le contrôle terminal de `main`, la phase
d’effets dispose d’au plus 480 secondes dans ce plafond : ce full-hold est exigé
avant la première écriture
et après la quatrième, et les cinq états Actions non terminaux (`queued`,
`in_progress`, `requested`, `waiting`, `pending`) sont inventoriés avant chacune
des quatre écritures. Le chemin réussi conserve la borne contractuelle de 55 GET :
les trois GET d’attestation sont une réserve historique non consommée par R4,
quatre contrôles `main` ont lieu dans les enfants d’écriture, puis deux
full-holds de douze GET, quatre
inventaires de cinq GET et au plus quatre lectures de clé publique par
secret. Le client est gelé sur `gh 2.96.0`, sortie de version
exacte et exécutable Windows amd64 lié par SHA-256
`cd79f16203f1fbe56937c4c96e2b6eadd10549418dcb241d91576ac77af0ac8b` ;
le PUT est isolé dans un processus privé borné à 15 secondes (travail 10,
terminaison 2), proxy et retry sont désactivés. Son reçu déclare malgré tout une borne
supérieure, pas un faux compteur exact. R8 n’a ni workflow ni runner séparé.
Avant la réservation one-shot, les quatre valeurs sont construites en mémoire et
R4 exige strictement plus de 439 secondes simultanément dans le TTL PREFLIGHT,
le plafond externe et la fenêtre d’effets. La même échéance minimale gouverne
tous les holds, inventaires et PUT ; l’expiration est revérifiée après le dernier
full-hold avant de signer le succès. À 439 secondes restantes, aucun reçu ni GET
ni PUT n’est créé ; à 440 secondes le chemin reste admissible.

Avant R4, dans le même processus PowerShell qui pilotera ensuite R5, R6 et R7,
générer `CHRONOS_CONTROL_PLANE_GENERATION_NONCE` avec 32 octets d’aléa
cryptographique et le conserver uniquement en mémoire dans l’environnement.
Ne jamais le placer dans un argument, fichier, Git, historique ou log. R4 écrit
sa valeur comme quatrième secret sans readback ; la même valeur en mémoire signe
le reçu local, valide MIGRATE et VERIFY, et calcule le generation hash du LIVE.
Les octets exacts de ce reçu sont transmis à R5 par l’entrée contrôleur en base64,
puis le document signé MIGRATE doit embarquer exactement le même objet. La preuve
terminale exprime cette relation par
`EXACT_RECEIPT_BOUND_BY_MIGRATE_CONTROLLER_INPUT_AND_SIGNED_OBJECT` ; elle ne
prétend pas qu’un second fichier autonome se trouve dans l’archive GitHub R5.
Perdre cette valeur après les quatre PUT est un arrêt matériel : GitHub ne permet
aucun readback et aucune nouvelle génération n’est autorisée.

## Séquence opérateur exécutable

Cette séquence est la seule reprise autorisée. Elle s’exécute depuis le worktree
writer sur `codex/data-torrent-recovery-v2`, avec `GH_TOKEN` fourni uniquement
par l’environnement et les onze verrous de sécurité déjà exportés. Chaque
commande doit retourner zéro et chaque reçu doit être validé avant la suivante.
Les observations GitHub sont bornées par le contrat : attendre le signal
terminal sans relancer un run, puis effectuer la lecture prévue; ne jamais
utiliser `gh run rerun`.

### PR-A, SAFE V2 et merge CAS

```powershell
$Repo = 'dddur75/robin-stades-ng'
$Branch = 'codex/data-torrent-recovery-v2'
$PR_A_HEAD = (git rev-parse HEAD).Trim()
git push --porcelain origin "${PR_A_HEAD}:refs/heads/$Branch"
$PR_A_URL = gh pr create --repo $Repo --base main --head $Branch --title '[DATA_TORRENT_RECOVERY_V2] PR-A' --body ''
$PR_A_NUMBER = [int](gh pr view $Branch --repo $Repo --json number --jq '.number')
gh run list --repo $Repo --workflow ci-safe-v2.yml --branch $Branch --event pull_request --limit 100 --json databaseId,headSha,status,conclusion,attempt
gh run view $PR_A_RUN_ID --repo $Repo --json databaseId,headSha,status,conclusion,attempt,jobs
gh pr view $PR_A_NUMBER --repo $Repo --json headRefName,headRefOid,baseRefName,mergeable,state
gh pr merge $PR_A_NUMBER --repo $Repo --merge --match-head-commit $PR_A_HEAD --subject '[DATA_TORRENT_RECOVERY_V2] PR-A' --body ''
```

La sélection de `$PR_A_RUN_ID` exige un unique run `pull_request`, attempt 1,
`headSha=$PR_A_HEAD`, `completed/success`, avec scope guard et gate SAFE V2 en
succès. La lecture PR immédiatement antérieure au merge doit encore rendre
`headRefName=$Branch`, `headRefOid=$PR_A_HEAD`, `baseRefName=main`,
`mergeable=MERGEABLE`, `state=OPEN`; sinon aucune commande merge n’est lancée.
Après merge, relever l’unique `$MAIN_SHA` et l’unique run push SAFE V2
`completed/success` sur ce SHA, puis exiger les mêmes jobs verts :

```powershell
$MAIN_SHA = (gh api "repos/$Repo/git/ref/heads/main" --jq '.object.sha').Trim()
gh run list --repo $Repo --workflow ci-safe-v2.yml --branch main --event push --limit 100 --json databaseId,headSha,status,conclusion,attempt
gh run view $POSTMERGE_RUN_ID --repo $Repo --json databaseId,headSha,status,conclusion,attempt,jobs
git fetch --no-tags origin refs/heads/main
if ((git rev-parse FETCH_HEAD).Trim() -ne $MAIN_SHA) { throw 'MAIN_DRIFT' }
git merge --ff-only $MAIN_SHA
python scripts/dispatch_data_torrent_recovery_v2_stage.py --neutralize-provider-branch --main-sha $MAIN_SHA --receipt .torrent/release/recovery-v2-provider-neutralization.json
python scripts/dispatch_data_torrent_recovery_v2_stage.py --postmerge-quarantine --main-sha $MAIN_SHA --receipt .torrent/release/recovery-v2-postmerge-quarantine.json
```

### Entrées hors worktree et chaîne R1–R8

Les JSON R1–R7 restent hors du dépôt. Cette fonction PowerShell écrit sans BOM
et avec LF; aucun de ces fichiers ne doit entrer dans Git :

```powershell
$RecoveryInputRoot = Join-Path ([IO.Path]::GetTempPath()) 'robin-recovery-v2-inputs'
[IO.Directory]::CreateDirectory($RecoveryInputRoot) | Out-Null
function Write-RecoveryInput([string]$Name, [hashtable]$Value) {
    $path = Join-Path $RecoveryInputRoot $Name
    $json = ($Value | ConvertTo-Json -Compress -Depth 20) + "`n"
    [IO.File]::WriteAllText($path, $json, [Text.UTF8Encoding]::new($false))
    return $path
}
```

R1, R2 puis R3 utilisent exclusivement les reçus terminaux immédiatement
précédents :

```powershell
$R1_INPUT = Write-RecoveryInput 'r1.json' @{ expected_main_sha = $MAIN_SHA }
python scripts/dispatch_data_torrent_recovery_v2_stage.py --stage RECOVERY_IDENTITY_V2 --main-sha $MAIN_SHA --inputs-json $R1_INPUT --receipt .torrent/release/recovery-v2-controller-recovery-identity-v2.json
$R1 = Get-Content -Raw .torrent/release/recovery-v2-controller-recovery-identity-v2.json | ConvertFrom-Json
if ($R1.verdict -ne 'TERMINAL_SUCCESS_CONFIRMED') { throw 'R1_NO_GO' }
$R1_RUN_ID = [string]$R1.workflow_run_id

$R2_INPUT = Write-RecoveryInput 'r2.json' @{ expected_main_sha = $MAIN_SHA; identity_run_id = $R1_RUN_ID }
python scripts/dispatch_data_torrent_recovery_v2_stage.py --stage DURABLE_IDENTITY_SEAL_V2 --main-sha $MAIN_SHA --inputs-json $R2_INPUT --receipt .torrent/release/recovery-v2-controller-durable-identity-seal-v2.json
$R2 = Get-Content -Raw .torrent/release/recovery-v2-controller-durable-identity-seal-v2.json | ConvertFrom-Json
if ($R2.verdict -ne 'TERMINAL_SUCCESS_CONFIRMED') { throw 'R2_NO_GO' }
$R2_RUN_ID = [string]$R2.workflow_run_id

$R3_INPUT = Write-RecoveryInput 'r3.json' @{ mode = 'PREFLIGHT'; expected_main_sha = $MAIN_SHA; post_merge_ci_sha = $MAIN_SHA; identity_run_id = $R1_RUN_ID; seal_run_id = $R2_RUN_ID }
python scripts/dispatch_data_torrent_recovery_v2_stage.py --stage PRODUCTION_PREFLIGHT_V2 --main-sha $MAIN_SHA --inputs-json $R3_INPUT --receipt .torrent/release/recovery-v2-controller-production-preflight-v2.json
$R3 = Get-Content -Raw .torrent/release/recovery-v2-controller-production-preflight-v2.json | ConvertFrom-Json
if ($R3.verdict -ne 'TERMINAL_SUCCESS_CONFIRMED') { throw 'R3_NO_GO' }
$R3_RUN_ID = [string]$R3.workflow_run_id
```

Créer ensuite le nonce une seule fois dans ce même processus PowerShell, sans
l’imprimer, et exécuter R4 depuis le cache R3 canonique :

```powershell
$NonceBytes = [byte[]]::new(32)
[Security.Cryptography.RandomNumberGenerator]::Fill($NonceBytes)
$env:CHRONOS_CONTROL_PLANE_GENERATION_NONCE = [Convert]::ToHexString($NonceBytes).ToLowerInvariant()
[Array]::Clear($NonceBytes, 0, $NonceBytes.Length)
python scripts/install_chronos_runtime_bindings_v2.py --preflight-artifact .torrent/release/recovery-v2-predecessor-cache/production-preflight-v2.json --expected-main-sha $MAIN_SHA --expected-preflight-run-id $R3_RUN_ID --report .torrent/release/chronos-runtime-bindings-v2.json
$R4 = Get-Content -Raw .torrent/release/chronos-runtime-bindings-v2.json | ConvertFrom-Json
if ($R4.verdict -ne 'FOUR_RUNTIME_BINDINGS_INSTALLED_V2') { throw 'R4_NO_GO' }
$R4_B64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path '.torrent/release/chronos-runtime-bindings-v2.json')))
```

R5 dispatch toujours le workflow exact une fois; si `0015` est déjà présente,
l’exécution de migration interne reste zéro. R6 vérifie ensuite l’état réel :

```powershell
$R5_INPUT = Write-RecoveryInput 'r5.json' @{ mode = 'MIGRATE'; expected_main_sha = $MAIN_SHA; post_merge_ci_sha = $MAIN_SHA; preflight_run_id = $R3_RUN_ID; runtime_bindings_receipt_b64 = $R4_B64 }
python scripts/dispatch_data_torrent_recovery_v2_stage.py --stage MIGRATE_0015 --main-sha $MAIN_SHA --inputs-json $R5_INPUT --receipt .torrent/release/recovery-v2-controller-migrate-0015.json
$R5 = Get-Content -Raw .torrent/release/recovery-v2-controller-migrate-0015.json | ConvertFrom-Json
if ($R5.verdict -ne 'TERMINAL_SUCCESS_CONFIRMED') { throw 'R5_NO_GO' }
$R5_RUN_ID = [string]$R5.workflow_run_id

$R6_INPUT = Write-RecoveryInput 'r6.json' @{ mode = 'VERIFY'; expected_main_sha = $MAIN_SHA; post_merge_ci_sha = $MAIN_SHA; migration_run_id = $R5_RUN_ID }
python scripts/dispatch_data_torrent_recovery_v2_stage.py --stage VERIFY_0015 --main-sha $MAIN_SHA --inputs-json $R6_INPUT --receipt .torrent/release/recovery-v2-controller-verify-0015.json
$R6 = Get-Content -Raw .torrent/release/recovery-v2-controller-verify-0015.json | ConvertFrom-Json
if ($R6.verdict -ne 'TERMINAL_SUCCESS_CONFIRMED') { throw 'R6_NO_GO' }
$R6_RUN_ID = [string]$R6.workflow_run_id
```

R7 lie le workflow, le manifeste brut et la génération; R8 est exécuté cent
fois dans le même run LIVE et ne possède aucune invocation séparée :

```powershell
$WORKFLOW_SHA = (Get-FileHash -Algorithm SHA256 .github/workflows/data-torrent-live-v2.yml).Hash.ToLowerInvariant()
$GENERATION_HASH = (python -c "import os; from robin.chronos_production import generation_hash; print(generation_hash(os.environ['CHRONOS_CONTROL_PLANE_GENERATION_NONCE']))").Trim()
$R7_INPUT = Write-RecoveryInput 'r7.json' @{ expected_main_sha = $MAIN_SHA; expected_workflow_sha256 = $WORKFLOW_SHA; expected_mission_manifest_sha256 = 'ced1b867faa3ae57911d169f5c1edbd0db02a891ac46ccc080de7397076d349f'; expected_generation_hash = $GENERATION_HASH; post_merge_ci_sha = $MAIN_SHA; identity_run_id = $R1_RUN_ID; verify_run_id = $R6_RUN_ID }
python scripts/dispatch_data_torrent_recovery_v2_stage.py --stage LIVE_ONCE --main-sha $MAIN_SHA --inputs-json $R7_INPUT --receipt .torrent/release/recovery-v2-controller-live-once.json
$R7 = Get-Content -Raw .torrent/release/recovery-v2-controller-live-once.json | ConvertFrom-Json
if ($R7.verdict -ne 'TERMINAL_SUCCESS_CONFIRMED') { throw 'R7_R8_NO_GO' }
$LIVE_RUN_ID = [string]$R7.workflow_run_id
```

### PR-C probatoire et finalizer

Fast-forward localement la branche writer au `$MAIN_SHA`, sans push distinct,
puis matérialiser les deux intents. C0 ajoute au ledger et au graphe le record
`STAGE_STARTED` canonique avant le premier commit; les validateurs Council
doivent passer sur les mêmes octets. Le premier push précède la création de la
PR et ne déclenche donc aucun cycle `pull_request` :

```powershell
git fetch --no-tags origin main
if ((git rev-parse origin/main).Trim() -ne $MAIN_SHA) { throw 'MAIN_DRIFT' }
git merge --ff-only $MAIN_SHA
python scripts/materialize_data_torrent_recovery_v2_terminal_evidence.py --reserve-only --main-sha $MAIN_SHA --live-run-id $LIVE_RUN_ID --pr-a-number $PR_A_NUMBER
git add reports/council/decision-ledger.jsonl reports/evidence/evidence-graph.json reports/council/data-torrent-recovery-v2-terminal-intents
git commit -m '[DATA_TORRENT_RECOVERY_V2] PR-C reservation'
$PR_C_C0_HEAD = (git rev-parse HEAD).Trim()
git push --porcelain origin "${PR_C_C0_HEAD}:refs/heads/$Branch"
```

Le terminal materializer s’exécute seulement après durabilité distante de cette
réservation. C1 ajoute ensuite le record `STAGE_FINISHED` et le commit evidence;
ce second push se fait encore avant la création de PR :

```powershell
python scripts/materialize_data_torrent_recovery_v2_terminal_evidence.py --main-sha $MAIN_SHA --live-run-id $LIVE_RUN_ID --pr-a-number $PR_A_NUMBER --reservation-commit-sha $PR_C_C0_HEAD
git add reports/council/decision-ledger.jsonl reports/evidence/evidence-graph.json reports/council/data-torrent-recovery-v2-terminal-evidence
git commit -m '[DATA_TORRENT_RECOVERY_V2] PR-C runtime evidence'
$PR_C_C1_HEAD = (git rev-parse HEAD).Trim()
git push --porcelain origin "${PR_C_C1_HEAD}:refs/heads/$Branch"
$PR_C_URL = gh pr create --repo $Repo --base main --head $Branch --title '[DATA_TORRENT_RECOVERY_V2] PR-C' --body ''
$PR_C_NUMBER = [int](gh pr view $Branch --repo $Repo --json number --jq '.number')
$C1_OBS = python scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py --observe-phase C1 --pr-number $PR_C_NUMBER --expected-head-sha $PR_C_C1_HEAD | ConvertFrom-Json
```

L’observation C1 doit être l’unique attempt 1 avec scope succès, gate/tests
échec attendu et run échec. Le delivery materializer consomme cette observation;
les quatre revues terminales, la synthèse et le record C2 `DECISION` sont ensuite
ajoutés sur ces octets avant le troisième et dernier push :

```powershell
python scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py --pr-a-number $PR_A_NUMBER --reservation-commit-sha $PR_C_C0_HEAD
git add reports/council/decision-ledger.jsonl reports/evidence/evidence-graph.json reports/council/data-torrent-recovery-v2-terminal-evidence reports/council/data-torrent-recovery-v2-terminal-*-review-v3.json reports/council/data-torrent-recovery-v2-terminal-report-v1.json
git commit -m '[DATA_TORRENT_RECOVERY_V2] PR-C terminal candidate'
$PR_C_HEAD = (git rev-parse HEAD).Trim()
git push --porcelain origin "${PR_C_HEAD}:refs/heads/$Branch"
$C2_OBS = python scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py --observe-phase C2 --pr-number $PR_C_NUMBER --expected-head-sha $PR_C_HEAD | ConvertFrom-Json
gh pr view $PR_C_NUMBER --repo $Repo --json headRefName,headRefOid,baseRefName,mergeable,state
gh pr merge $PR_C_NUMBER --repo $Repo --merge --match-head-commit $PR_C_HEAD --subject '[DATA_TORRENT_RECOVERY_V2] PR-C' --body ''
```

La lecture PR doit encore prouver l’égalité C2/head juste avant merge. Relever
ensuite le merge SHA et son unique run post-merge, observer POSTMERGE une fois,
puis lancer exactement une fois le finalizer :

```powershell
$FINAL_MAIN_SHA = (gh api "repos/$Repo/git/ref/heads/main" --jq '.object.sha').Trim()
$POSTMERGE_OBS = python scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py --observe-phase POSTMERGE --pr-number $PR_C_NUMBER --expected-head-sha $PR_C_HEAD | ConvertFrom-Json
$PR_C_POSTMERGE_RUN_ID = [string]$POSTMERGE_OBS.run.run_id
$FINAL = python scripts/verify_data_torrent_recovery_v2_postmerge_gate.py --pr-number $PR_C_NUMBER --postmerge-run-id $PR_C_POSTMERGE_RUN_ID | ConvertFrom-Json
if (-not ($FINAL.data_torrent_ready -and $FINAL.mission_complete -and $FINAL.global_quiescence -and $FINAL.worktree_status -eq 'CLEAN' -and $FINAL.semantic_verdict -eq 'DATA_TORRENT_READY')) { throw 'FINAL_GATE_NO_GO' }
```

Le finalizer imprime le JSON canonique complet. Seul son exit zéro et ces cinq
champs exacts autorisent la réponse propriétaire `DATA_TORRENT_READY = TRUE`.

## Chemin critique conservateur

Une exécution SAFE V2 exacte réussie est bornée à 145 minutes; le post-merge
PR-C, qui ajoute le witness, à 150 minutes. Le C1 probatoire échoue après son
préfixe attendu mais réserve 120 minutes. Avec deux matérialisations terminales,
trois observers, le delivery, C2, post-merge et finalizer, PR-C réserve 555
minutes. La borne sans file d’attente est donc 290 minutes pour PR-A, 214 pour
E1/R1–R8 et 555 pour PR-C : 1 059 minutes (17 h 39) sans PR-B, ou 1 349 minutes
(22 h 29) avec PR-B. Pour achever avant la fermeture globale, démarrer au plus
tard le `2026-09-05T19:07:58Z` sans PR-B ou le `2026-09-05T14:17:58Z` avec
PR-B. Les files GitHub ne sont pas bornées : l’exécution réelle doit commencer
bien avant ces seuils, sans que cette marge crée une autorité nouvelle.

## Budgets contractuels

Les plafonds Neon sont non fongibles : Identity GET au plus 25, Preflight GET
au plus 39 et POST au plus 1, validation d’autorité Migrate GET au plus 26.
Le total contractuel est de 90 GET, sans transfert de reliquat entre phases.

Les deux PR d’ingénierie (PR-A requis, PR-B conditionnel) ont chacun au plus
trois cycles consolidés SAFE V2 sur leur HEAD exact, soit six cycles exact-head
maximum au total. Les reliquats sont non fongibles ; rerun d’un run échoué et
réutilisation d’un run CI historique restent à zéro. PR-C est le créneau de
preuve terminale distinct et ne peut consommer le budget d’ingénierie.

Les lectures GitHub sont elles aussi non fongibles : 232 pour les huit étapes
d’exécution, 192 pour les six cycles contrôleur, 408 pour les trois créneaux
de livraison et 25 pour la quarantaine post-merge, soit une borne de mission de
857. Les téléchargements d’artefacts
ont leur ventilation séparée 8 + 6 + 12, borne 26 ; aucun reliquat d’une phase
n’augmente une autre phase et les retries automatiques restent à zéro.

Le budget R2 de mission est exactement trois PUT, trois GET et trois objets ;
LIST, DELETE, overwrite et retry restent à zéro. Le LIVE commence par le GET
exact du seal, avant toute connexion PostgreSQL ou requête fournisseur. Il crée
ensuite RAW et NORMALIZED par PUT conditionnel, exige le terminal
`CREATED_CONFIRMED` et n’effectue aucun readback R2 de ces deux objets.

Migrate 0015 utilise six connexions d’orchestration gelées (inspection pré-lock,
administration, inspection sous lock, autorité, inspection post-migration et
inspection finale) et réserve conservativement jusqu’à quatre connexions
Alembic additionnelles avant dispatch : maximum dix, aucun retry, onzième
tentative refusée avant connexion. VERIFY utilise quatre connexions en lecture.
Recovery V2 n’exécute aucun `DROP`. Son unique exécuteur bootstrap déterministe
est révoqué puis conservé dans l’état terminal prouvé `NOLOGIN`, mot de passe
`NULL`, zéro appartenance, zéro privilège direct ou effectif et zéro session.
La preuve de privilège effectif couvre les objets fonctionnels Chronos ; le rôle
est de plus inauthentifiable et ne peut donc exploiter aucun droit `PUBLIC` résiduel.
Un exécuteur préexistant est un arrêt fail-closed ; il n’est jamais supprimé.
Le graphe LIVE est généré et lié par les empreintes :

- brut : `8d6b14c1f9ab48b7a6b48a0ae1730b5abc3b93a9efc3ae0f21dd5f3fa083201c` ;
- canonique : `d89ddc3b202ba13b3eba1c7f678e142b5817afba954dd1d5e4119a587a6e0739` ;
- nominal : 51 tentatives ;
- maximum : 53 ;
- première tentative refusée : 54 ;
- retry : 0.

Le LIVE autorise cinq ligues, les marchés `h2h` et `totals`, au plus 50 lectures
officielles, exactement cinq requêtes Odds sur succès et au plus 1 000 crédits.
Aucun achat ni pari n’est autorisé.

## Preuves terminales

Le succès exige les 19 artefacts gelés par le contrat, les 22 gates QA au vert,
P0/P1/P2 et threads ouverts à zéro, cinq ligues et dix cellules prouvées par des
données réelles, zéro fuite temporelle, zéro doublon logique et tous les rejets
explicitement reason-coded.

La preuve terminale reconstruit indépendamment les contrats de requête OFFICIAL
et ODDS depuis la configuration autorisée. Chaque réponse est revalidée contre
l’allowlist d’en-têtes, l’allowlist URL officielle et l’endpoint Odds canonique.
Son instant de récupération reste dans la fenêtre locale de capture et dans la
fenêtre durable `DISPATCHED`–`CONFIRMED`, avec une tolérance inter-horloges
maximale explicite de cinq secondes. L’ordre exigé est
`latest_retrieved <= raw_index <= capture_end <= replay <= quality <= normalized <= QA <= manifest`.

Toute fenêtre manquée reste manquée et n’est jamais antidatée : le manifeste et
le quality report doivent porter `MISSED_NOT_BACKDATED`. Toute autre valeur est
refusée à la fois par la QA terminale et par PostgreSQL.

Après `CREATED_CONFIRMED` des deux PUT, le replay consomme uniquement les octets
de l’archive RAW retenus localement dans le processus LIVE ; les octets
NORMALIZED retenus localement servent à la QA terminale. Il exécute exactement
100 itérations, produit le même hash canonique et n’effectue aucune connexion
PostgreSQL, lecture officielle, requête fournisseur, opération R2, opération
Neon ou écriture de secret.

## Portée des limites V3.1

Les limites `implementation_limits` de `scale-policy-v3.json` bornent
l’implémentation du Council V3.1 minimal, dont le rôle est
`CONTROL_AND_RECORD_ONLY` et `executes_workloads=false`. Cette portée est déjà
matérialisée par `governance-final-review-v3.json` et
`v31-scope-drift-review.json`, qui mesurent le code `src/robin/governance` et les
tests Council associés. Recovery V2 ne modifie aucun fichier de ce moteur, ne
crée aucune dépendance ou service et ne transforme pas le Council en ordonnanceur
ou exécuteur. Ses entrypoints métier restent séparément bornés par le manifeste
propriétaire et le présent contrat d’effets ; cette résolution n’est ni une
dérogation ni une extension d’autorité.

## Arrêt fail-closed

Arrêter sans retry sur source obligatoire absente, autorité ou prédécesseur
discordant, ancien artefact V1, deuxième dispatch, transport ambigu, compteur
non conservateur, budget dépassé, secret exposé, objet R2 préexistant ou ambigu,
migration autre que `0015_data_torrent_opportunity`, données cinq ligues non
prouvées, replay discordant, gate QA ouvert ou achat requis.

Les verrous de production restent ceux du dépôt : stockage et P3/P4 en pause,
production et promotion verrouillées, pari réel et publication sociale
désactivés, `NO_BET_DEFAULT=true`, API-Football interdite.
Avant toute réservation one-shot, vérifier les onze valeurs exactes :
`STORAGE_PAUSED=true`, `P3_P4_PAUSED=true`, `PRODUCTION_LOCKED=true`,
`REAL_BETS=false`, `NO_BET_DEFAULT=true`, `PROMOTION_LOCKED=true`,
`SOCIAL_PUBLISHING_ENABLED=false`, `DEMO_MODE_ENABLED=false`,
`POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES=false`,
`THE_ODDS_API_HISTORICAL_CREDITS=false` et `API_FOOTBALL_CALLS_ALLOWED=0`,
ainsi qu’un token GitHub borné. Les fichiers JSON d’entrée R1–R7 sont créés hors
du worktree et ne sont jamais ajoutés à l’inventaire `.torrent/release`.
