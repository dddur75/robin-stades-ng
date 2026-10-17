Phase 2 — préparation, à appliquer après la recette de la phase 1

Constat vérifié par API GitHub le 16 octobre : workflow 321915843 `disabled_manually`, date de modification 2026-08-09T16:51:39Z. Le run 31322534010 est annulé sans job. Cela établit une désactivation du déclenchement ; aucun journal ne permet d'en attribuer l'auteur ou le motif. Le seul test de clé de la mission a réussi, donc ne pas refaire ce test.

Changements nécessaires dans une PR « 027 — phase 2 — … », au plus 400 lignes de code :

1. Introduire un profil de capture propre aux compositions, 60 unités d'appels par journée UTC et par run, réserve fournisseur 5000. Inclure tous les appels auxiliaires de fraîcheur, les échecs et les réservations non résolues. Ne pas changer la politique partagée ni le budget des cotes.
2. Filtrer SQL en amont : fixtures `season='2026'` et cinq competitions autorisées ; windows/attempts/receipts via les identifiants de ces fixtures ; budget API-Football courant via date et profil, sans charger les payloads d'une autre saison. Ne pas utiliser l'actuel `_restore()` sans filtre.
3. Le chemin R2 des captures est structuré par compétition/saison mais les recovery intents sont des clés opaques `intent-<hash>.json` contenant le payload compressé. Un simple filtrage de `iter_captures()` après `inventory_namespace()` lirait déjà 2025. Prévoir un index de récupération par saison ou une réconciliation bornée aux hashes attestés de 2026 ; refuser une incertitude de périmètre plutôt que d'ignorer le recovery. Cette partie doit être testée avec un store qui échoue à toute lecture hors 2026.
4. Confirmer par requête SQL explicitement bornée à 2026 que les cinq ligues ont des fixtures courantes et des fenêtres compatibles. Sans registre actuel, préparer uniquement le rafraîchissement 2026 nécessaire, comptabilisé dans les mêmes 60 appels/jour. Les autres cadences restent inchangées.
5. Le moteur existant groupe LINEUP et FORMATION par fixture, utilise une vérification de fraîcheur et un payload lineup. Les fenêtres H-2 et NEAR_KICKOFF restent la référence. Le cron actuel est horaire minute 29 ; vérifier ses délais réels avant kickoff. Tout ajustement éventuel reste limité à la capture des compositions, sans modifier les autres cadences. Limiter le lot aux unités restantes avant admission, au lieu d'échouer sur un gros lot. Favoriser les fenêtres proches du coup d'envoi si le lot dépasse le budget ; préserver la date de réception et les contrôles avant kickoff.
6. L'actuel `run_capture()` impose un `/status` et le compte dans l'estimation. La mission n'autorise qu'un contrôle de clé initial : prévoir une réutilisation bornée de la preuve et des en-têtes de quota récents, ou tracer ce prérequis comme blocage explicite. Ne pas multiplier `/status` au rythme horaire.
7. Tests ciblés : aucune lecture 2025 (SQL et R2), au plus 60 appels malgré retries/crash/rerun, absence de duplication des familles par fixture, refus après kickoff, protection de réserve. Vérifier que le chemin des cotes n'est pas changé.
8. Faire relire avant intégration : le cron GitHub utilise `main`, donc activer l'ancien main déclencherait le budget 800 et les lectures sans filtre. AGENTS.md dit « L'auteur ne valide jamais seul son travail » ; la spec désigne Claude pour la relecture et David pour la validation. Conserver le workflow désactivé jusqu'à l'intégration du correctif relu.
9. Activer uniquement `prospective-lineup-capture.yml`, puis un dispatch borné si des fenêtres sont dues. Publier un reçu durable agrégé montrant >=10 fixtures complètes, `received_at < kickoff_at`, les 5 ligues, et la comptabilité quotidienne <=60 ; aucune simulation ne prouve ce critère.

Ce document ne constitue ni un changement de workflow ni une activation. Aucun appel fournisseur de phase 2 n'a été fait.

## Résumé de livraison — 2026-10-17
- Cause : capture et registre désactivés manuellement le 9 août ; dernier run de capture annulé sans job, auteur et motif non établis.
- Fait : profil compositions 2026 pour cinq ligues, calendriers inclus dans 60 réservations UTC, reprise R2 par saison, SQL filtré avant chargement ; fenêtres et cadence horaire conservées.
- Reste : relecture/fusion Qualité, puis réactivation du seul workflow de compositions et reçu réel de dix matchs ; aucune activation ni collecte fournisseur depuis cette session.
- Risques : sans preuve de quota du workflow 71 datant de moins de 110 minutes le même jour UTC, arrêt PARTIAL sans appel ; contrôle de schéma aligné sur la révision 0015 exigée par l'adaptateur existant.
