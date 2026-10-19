# Critères avant-match — mission 036

Calcul hors ligne, sans client fournisseur, R2 ou Neon. La population cible est
la liste figée B/C de 70 084 fixtures (027 + 028 + Ligue 1). La saison 2025 est
exclue avant toute lecture de payload. Les autres saisons présentes dans les
calendriers servent uniquement d'historique. Les sources sont figées par commit
Git et par hash de blob. Une absence de publication n'est pas une absence de match.

## Convention temporelle

Une rencontre source doit avoir commencé strictement avant la cible et être
terminée. Faute d'heure de fin observée fiable, la borne conservatrice de fin
est coup d'envoi + 3 heures. Les fenêtres portent sur les 5 ou 10 dernières
rencontres connues de l'équipe, sans ignorer un match dont une famille manque.
Les fenêtres incomplètes restent nulles. Les agrégats saisonniers sont arrêtés
à la date cible, jamais extraits des fiches joueurs de fin de saison.
Les fenêtres de forme et de joueurs portent sur la même compétition, en pouvant
traverser la frontière entre saisons ; le top 11 et la moyenne saison repartent
à zéro à chaque saison. Les colonnes observées de calendrier suivent ce même
périmètre, sans prétendre couvrir les coupes ou compétitions internationales.

Les titulaires de la cible sont admis comme feuille officielle avant-match,
sur instruction de David : `source_compo = feuille_officielle`. Ceci ne prétend
pas qu'un reçu historique prouve l'heure de publication par le fournisseur.
On exige exactement 11 identités distinctes, avec rattachement fixture/équipe.
Les anciens blocs sans fixture_id ne sont jamais rapprochés par ordre de ligne.

## Définitions

- `tc_neutre10` : null, `timestamped_shots_unavailable`.
- `etat_score_buts10` : somme sur 10 matchs des minutes réglementaires à
  écart absolu <= 1, et des buts pour/contre inscrits dans cet état **avant**
  chaque but. Le struct contient `minutes`, `buts_pour`, `buts_contre`.
  Les arrêts de jeu sont rattachés à la minute 45 ou 90 : ordre des buts
  conservé, sans inventer une durée supplémentaire. Le score reconstruit doit
  égaler le score officiel à 90 minutes. Les tirs au but sont exclus.
  Ce remplacement décrit le score ; il ne prétend pas mesurer les tirs ni
  conditionner les minutes à un effectif de 11 contre 11.
- `points_tardifs5` : somme des points à 90 minutes moins ceux au score après
  les événements de minute <= 80, sur 5 matchs. Un penalty manqué n'est pas un but.
- `absents_cles` : minutes des 5 derniers matchs des membres du top 11 saison
  absents du onze cible / minutes de ce même top 11 sur ces 5 matchs. Le top 11
  dépend exclusivement des minutes antérieures de la saison ; égalités résolues
  par identifiant joueur. Toute statistique joueur nécessaire manquante annule
  le calcul. Une absence du onze peut être un choix tactique, pas une blessure.
- `force_xi` : moyenne des 11 moyennes individuelles sur les 10 derniers matchs
  de l'équipe, moins moyenne des notes individuelles de l'équipe sur la saison
  antérieure. Les absences de note ne deviennent pas des zéros ; chaque titulaire
  doit avoir au moins une note sur la fenêtre. Les notes sont non pondérées.
- `cadre_suspendu_rouge` : existence d'un joueur à >= 600 minutes dans les
  10 derniers matchs, ayant reçu un rouge direct au dernier match de la même
  compétition. Règle demandée : un match ferme ; pas d'extension inventée.
  Les rouges de banc non identifiables et historiques cartons incomplets ne
  prouvent pas un négatif. Le second jaune n'est pas traité comme rouge direct.
  Un rouge accompagné de deux jaunes au même joueur, ou d'un commentaire
  explicite de second jaune, est exclu de la partie rouge direct.
- `cadre_suspendu_cumul` : null si la règle de ligue/saison n'est pas documentée.
  `cadre_suspendu` vaut vrai si le rouge le démontre, sinon null tant que le
  cumul n'est pas démontrable. Aucun seuil universel supposé.
- `cong21` et `repos_jours` : null sans preuve de calendrier toutes compétitions.
  Le nombre de rencontres et le repos observés sont conservés dans des colonnes
  auxiliaires explicitement nommées `*_observe`, sans les promouvoir en critères.

## Livraison et contrôle

Un Parquet par saison, une ligne par fixture, clé `(fixture_id, date,
equipe_domicile, equipe_exterieur)` ; critères suffixés `_home` / `_away`.
La couverture compte les valeurs **non nulles** (y compris zéro/faux), par équipe,
critère, ligue et saison, sur toute la population figée, avec les motifs des nulls.
Elle distingue fichiers présents, fichiers vides et fixtures réellement reliées.
Les fenêtres partielles et sources manquantes restent dans les dénominateurs.

Les tests couvrent les frontières de fenêtres, les égalités de date, les rouges,
les buts à 80/90+ et les moyennes saisonnières. Une preuve décalée compare, sur
échantillon réel, le calcul complet à un recalcul ne conservant que les sources
antérieures plus la seule composition cible ; les données post-match de la
cible et toutes les données futures sont supprimées. Un test synthétique modifie
ces données futures et vérifie l'invariance des critères.

## Reproduction

Depuis la racine, avec les dépendances Python du dépôt installées :

```sh
PYTHONPATH=src python scripts/build_prematch_criteria.py \
  --repository . \
  --source-ref fac718f36d0b8e178374d5a8384c1b3cc871f135 \
  --output /tmp/mission036-prematch
PYTHONPATH=src python -m pytest -q tests/prematch
```

Les blobs référencés doivent déjà exister localement : le calcul refuse tout
protocole Git réseau et toute récupération paresseuse. `source-inventory.csv`
donne leurs chemins et hashes. On peut les récupérer explicitement depuis le
dépôt GitHub, sans fournisseur, avant de lancer le calcul. Ne pas checkout la
branche de données entière (la saison holdout doit rester exclue).

Les taux décrivent cette révision publiée, et non tout le stock R2. Le reçu B
`39298159113-1` atteste 66 772 événements complets / 70 084 ; le reçu C
`39315234613-1` atteste 7 283 statistiques joueurs complètes / 70 084. Ces reçus
ne suffisent pas à reconstruire les payloads non publiés. Aucun accès R2 n'a
été effectué et aucun secret R2 n'est configuré dans l'environnement de travail.

Les anciennes partitions Ligue 1 perdent l'identifiant de fixture dans les
familles de détail. Le code historique les relie par `raw_payload_hash` aux
métadonnées `raw/observations` (`historical.readiness.observation_dimensions`).
Ces observations ne sont pas publiées individuellement sur la branche retenue ;
les index de bundles `multi/0/multi` listent des fichiers par date de collecte,
sans partition de saison permettant d'exclure le holdout avant lecture. Aucun
payload de ces archives mixtes n'est utilisé. Une réexportation planifiée de
l'index de rattachement, partitionnée hors holdout, permettrait de reprendre ces
lignes sans nouvel appel fournisseur.

`games.substitute` n'est pas substitué à `startXI` : les échantillons AUT 2019
et BRA 2019 marquent chacun 14 joueurs comme non-remplaçants. Une composition
officielle ne peut pas être déduite de manière fiable de ce champ ancien.
