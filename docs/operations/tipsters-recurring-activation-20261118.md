# Activation de la collecte récurrente Robin V3 — 18 novembre 2026

Le développement du circuit local est intégré aux fiches et au suivi admin. La recette métier reste **PARTIAL : zéro pronostic personnel qualifié**. Claim : `ENG.SOURCE_OBSERVATORY.RECURRING.20261118`.

Deux créneaux réels et 21 GET ont fonctionné; sept sélections Ligue 1 sont conservées mais exclues car collectives. L’audit complémentaire des articles brésiliens ne prouve pas un rôle personnel de pronostiqueur; une signature ne transforme pas une section «We say» en choix individuel. Aucun exemple synthétique ne compte comme collecte réelle.

## Ce qui est consultable

Sur A9_Mega, Robin lancé localement : [suivi récurrent](http://127.0.0.1:4173/expert/collecte-recurrente), [fiches récurrentes](http://127.0.0.1:4173/expert/collecte-recurrente?view=tipsters), [sources et blocages](http://127.0.0.1:4173/expert/sources-tipsters). Une page GET ne collecte rien. Les fiches affichent les premières observations, versions, dates et liens originaux quand des pronostics personnels admissibles existent.

## Autorisation A — tâche Windows bornée

Le paquet final local est `cockpit/.ci/tipsters-recurring-final-20261118`. Il ne possède pas d’autorisation et aucune tâche récurrente nouvelle n’a été installée.

> J’autorise la tâche Windows temporaire Robin-Tipsters-Recurring-V1-20261119 sur A9_Mega, du 19 novembre 2026 à 08 h au 26 novembre à 08 h, heure de Paris, toutes les deux heures, limitée à 504 GET Forecast Record, trois fiches Ligue 1 par créneau, sans achat, sans API-Football, sans requête aux sources originales et avec stockage local structuré uniquement. L’absence de pronostic personnel admissible arrête la campagne sans relance. Le pilote J12 reste distinct.

Plan SHA-256 : `0d755d8c1d0109e21787a232babedb27cf9467ee073a06455b8e210444a36689`.

Manifeste SHA-256 : `67b3d64d7f625c4eaabebe5d92cb570ba73fe7a1aae619ade522ad4b40d2e81e`.

84 créneaux maximum, fenêtre de trois minutes chacun, contrôles robots et conditions inclus dans les 504 GET. Seul `forecastrecord.com` est contacté : robots.txt, contrat API, index France et au plus trois fiches par créneau. Aucune relance ni rattrapage; réservation avant GET; arrêt sur 401/403/429, absence obligatoire d’attribution personnelle, budget ou expiration. Les horaires manqués restent manqués. Les changements d’horaire d’un match arrêtent le créneau. La clôture est locale et sans requête réseau.

Le compte Windows doit rester connecté et A9_Mega éveillé, réseau disponible. La tâche s’exécute sans privilèges élevés et fenêtre masquée; pas de réveil automatique ni de promesse de collecte si le poste est arrêté. Après accord explicite portant sur ce paquet, C0 enregistrera la référence d’autorisation puis installera la tâche et vérifiera sa définition. Rien de cela n’est déclenché par ce document.

Cette autorisation permet une **qualification prospective bornée**, pas la certification d’une collecte personnelle déjà réussie. Avec les données actuelles, un créneau sans choix personnel admissible arrêtera la campagne. Le pilote J12 du 26–29 novembre conserve ses 51 GET et sa tâche distincte.

## Ce qui débloque réellement les pronostics personnels

Il faut un accès autorisé qui relie explicitement un pronostiqueur personnel, un match, un marché et un choix, avec dates de publication/détection. Une permission générale de scraper ne suffit pas à créer cette preuve.

- Accès officiel YouTube pour les neuf chaînes bloquées : configuration locale de l’accès, droits sur les descriptions/transcriptions utiles et plafond de quota avant activation. Une clé ne doit jamais être transmise dans le chat. Aucune dépense ni extension de quota payante n’est autorisée.
- Pour les éditeurs soumis à permission ou à conditions non vérifiées : fournir leur permission écrite ou un flux/API contractuel adapté; David ne peut pas lever seul une restriction décidée par un éditeur.
- Pour les erreurs HTTP/robots et changements d’hôte : accès officiel ou levée de la restriction par le service. Aucun contournement.
- Pour les flux publics déjà lisibles : compléter la preuve du rôle de pronostiqueur et le rattachement du choix. Les articles, analyses collectives, algorithmes et vidéos sans choix explicite restent exclus.

Le fichier `reports/ux/TIPSTERS-SOURCE-AUTHORIZATIONS-20261118.json` donne les **57 sources une par une**, leur URL, le statut réellement constaté et l’action requise. Il réutilise la qualification existante sans nouveau recensement. Les neuf flux de publications lisibles ne sont pas neuf collecteurs de pronostics personnels validés.

## Livraison technique et limites

Les clés C1 (preuve), C4 (sécurité) et UX6 (interface) sont distinctes de la recette métier. La PR #133 reste brouillon et non déployée tant que les contrôles de livraison ne sont pas terminés. La CI finale est suivie sur le commit exact. Production, paris, promotion, stockage fournisseur brut dans Git et écritures R2 restent fermés.


## Relevé du premier lancement — 19 novembre 2026

À 08 h Paris, Windows a déclenché la tâche, mais le lanceur a échoué avant le collecteur : zéro requête, zéro visite et zéro pronostic collecté. Le problème de conversion de date sous culture française est reproduit puis corrigé avec `ConvertFrom-Json -DateKind String`. Les quatre cas de date/culture et les 25 tests de récurrence passent.

Le créneau de 08 h reste manqué, sans rattrapage. Le prochain créneau prévu est 10 h Paris. Le paquet effectif est désormais `cockpit/.ci/tipsters-recurring-launcher-fix-20261119`, plan `fe1a68ba8b058ee95038564a68dc8c7ae7a97282f087a5423a9814ba26d15835`. Il conserve exactement le manifeste, les plafonds, les 84 créneaux et l'approbation originale. Sa dérivation technique lie les anciennes et nouvelles empreintes, avec la clé C4 ; elle ne fabrique pas une nouvelle déclaration propriétaire. Le journal historique est conservé comme préfixe et les compteurs ne sont pas remis à zéro.

La tâche change uniquement l'argument de répertoire; J12 est inchangé. Les autres sources n'ont pas été recontactées pour ce diagnostic. Détails et claim : `reports/ux/TIPSTERS-FIRST-LAUNCH-20261119.json` (`ENG.SOURCE_OBSERVATORY.RECURRING.FIRST_LAUNCH.20261119`).


## Bilan observé après correction — 19 novembre à 10 h

Le déclenchement automatique de 10 h a terminé normalement : six GET HTTP 200 (robots, contrat API, catalogue et trois fiches). Nice–PSG, Lens–Toulouse et Strasbourg–Brest ont été lus avant les coups d'envoi fournisseur du 21 novembre. Aucun pronostic personnel admissible n'a été enregistré. Le compteur reste zéro ; les sept anciennes sélections collectives ne sont pas ajoutées.

Le collecteur a journalisé `FAIL_AND_STOP` pour `required_individual_attribution_missing`. Conformément à la condition propriétaire, la seule tâche récurrente est désormais **Disabled / Enabled=false**. Aucune relance de cette campagne n'est prévue. J12 reste Ready et sa définition est inchangée. Les six requêtes restent comptabilisées sur le plafond 504, sans réinitialisation ni hausse de budget.

Le blocage principal est la preuve source de pronostics personnels admissibles. Les autres accès officiels, permissions éditeurs et conditions à vérifier restent détaillés dans le registre des 57 sources ; aucun recensement supplémentaire n'a été lancé. La recette métier demeure PARTIAL.

Preuve : `reports/ux/TIPSTERS-SCHEDULED-RESULT-20261119.json`, claim `DATA.SOURCE_OBSERVATORY.RECURRING.RESULT.20261119`. Le correctif logiciel `130f94e` a sa CI verte : 17 jobs, 4 904 tests et 62 parcours visuels.
