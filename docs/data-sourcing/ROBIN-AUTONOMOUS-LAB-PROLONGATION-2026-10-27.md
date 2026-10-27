# Robin — prolongation d'un mois de la collecte des cotes (2026-10-27)

## Autorité

Le 27 octobre 2026, David a donné son accord dans le fil du projet pour
prolonger d'un mois, aux mêmes plafonds, l'autorisation de la collecte
automatique des cotes. Les manifestes actifs expirent le
`2026-11-03T23:59:59Z`. La conception exige pour continuer au-delà un
successeur autorisé séparément et commis avant l'expiration ; ni le workflow ni
la comptabilité ne peuvent prolonger leur propre autorité.

## Changement

Les quatre manifestes lus par le workflow établi `321915839` restent intacts.
Chacun reçoit un successeur au suffixe `-prolongation-20261203`, identique à
l'octet près sauf `expires_at`, qui passe à `2026-12-03T23:59:59Z` :

| Manifeste d'origine | SHA-256 d'origine | SHA-256 du successeur |
|---|---|---|
| `robin-autonomous-lab-20261004.json` | `98b15383…aede00a` | `2457a895e74d96ed906372408fee65f3f2066e89ce20dbae86b0249f17395625` |
| `robin-autonomous-lab-schedule-reliability-20261004.json` | `0905b304…c15e0bc` | `9eaffaf356305083bf3598b933f1ba0ea327a6c90575c5ad800246d690a0ac1b` |
| `robin-autonomous-lab-established-scheduler-20261004.json` | `c1e33753…3be14fd` | `9e5af281dd8414e2b1b482bf9d8e62172235b992bb3965aeb7eb86c3300135e5` |
| `robin-autonomous-lab-trigger-recovery-v2-20261005.json` | `4c150973…6929e6d87` | `0ed702e9cffd5ff43f98550673547bc8c39ac3ac1b4a0f7db7abc62a8abdb14a` |

Le workflow et `scripts/run_recurring_real_data.py` pointent vers ces
successeurs. La génération de relais devient
`0ed702e9cffd5ff43f98550673547bc8c39ac3ac1b4a0f7db7abc62a8abdb14a`.

## Bornes inchangées

- Mêmes championnats, région `eu`, marchés `h2h` et `totals`, créneaux de deux
  heures.
- Mêmes plafonds : 140 requêtes et 280 crédits sur 24 heures glissantes, 4 000
  et 8 000 sur 30 jours, sans remise à zéro de la comptabilité.
- Mission, étapes, effets externes, budgets et document source
  (`source_hash`) identiques.
- Aucun achat, abonnement, pari, nouveau fournisseur ni ancien workflow
  fournisseur rallumé.

## Bascule

1. Fusion après la fin du pilote « Dossier fidèle » (2 novembre 2026) et avant
   le 3 novembre 2026 vers 20:00 UTC, avec le « oui » de David.
2. Juste après la fusion, jamais avant, David met la variable de dépôt
   `ROBIN_AUTONOMOUS_RELAY_GENERATION` à
   `0ed702e9cffd5ff43f98550673547bc8c39ac3ac1b4a0f7db7abc62a8abdb14a`. Changée
   avant la fusion, elle arrêterait l'ancienne chaîne jusqu'à la fusion. Jamais
   changée, aucune chaîne ne repart : le watchdog sort sans rien relancer.
3. La chaîne en cours s'arrête d'elle-même au contrôle de continuité, puisque
   le workflow change ; la capture refait ce contrôle juste avant la collecte,
   donc pas de double collecte. Le watchdog horaire (minute 13) relance une
   chaîne `collect` sur la nouvelle génération sans appel fournisseur. Coupure
   attendue : une à deux heures. Les clés comptables R2 ne dépendent que de la
   mission : pas de remise à zéro des plafonds glissants. Un créneau resté
   ouvert est clos hors ligne par le run suivant.
4. Contrôle : un run `robin-collect-relay-0ed702e9…` doit apparaître après la
   minute 13 suivante.

Si la fusion n'a pas lieu, la collecte s'arrête seule le 3 novembre 2026 vers
21:00 UTC, trois heures avant l'expiration, comme prévu à l'origine.
