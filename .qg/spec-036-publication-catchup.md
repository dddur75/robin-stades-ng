# Mission 036 — rattrapage de publication demandé le 20 octobre 2026

Source : ordre utilisateur de ce chat après fusion de PR #121. Une branche depuis
main, une seule PR ; aucun nouvel appel fournisseur, écriture Neon ou pari.
C0 désigne Codex comme unique rédacteur ; la relecture C4 reste en lecture seule.

## Ordre et périmètre

« Rends la publication reprenable et complète : rattrapage de tous les objets
référencés par les reçus mais absents de l'inventaire publié […] par lots,
jusqu'à épuisement, avec vérification du SHA-256 de chaque objet. »
Ajouter un mode manuel dans le workflow 71 existant, exécuter le rattrapage,
recalculer les critères et terminer la PR par l'avant/après du rattachement et
la couverture réelle de chaque critère.

La demande autorise les lectures R2 des reçus publics et de leurs projections
normalisées, et les ajouts append-only sur historical-data. Le code ne lit ni
payload brut ni saison holdout 2025. Aucun workflow nouveau : seul le workflow
71 est étendu. Collecteurs, plafonds fournisseur, prospective-deep-scheduler,
robin-core, configurations de populations et données fournisseur restent intacts.

## Contrat d'exécution

- Reçus des missions 029 et 027 (compositions), déduplication des références.
- SHA-256 concordant pour chaque objet, même si son chemin est déjà publié.
- Lot maximal de 1 000 objets ; délai coopératif 9 600 s en mode rattrapage.
- Huit lecteurs ; connexions R2 10 s, lectures 30 s, deux tentatives SDK par GET.
- Après redesign E1 des erreurs de lecture observées, une seule ronde de
  reprise des `R2_READ_FAILED` est permise dans le même budget global :
  deux tentatives SDK par GET, au plus quatre tentatives réseau par objet
  sélectionné ; jamais de retry d'absence, de hash discordant ou de push.
- Job existant de collecte entièrement sauté ; job manuel sans clé fournisseur.
- Publication Git sans force, aucune écriture R2 ; conflit jamais écrasé.
- COMPLETE uniquement quand les références sont publiées et le dernier
  inventaire de reçus est stable ; sinon PARTIAL/BLOCKED avec motifs et reprise.
- Baseline analytique : fac718f3, 17 433 / 70 084 = 24,8744 %.
- Réussite analytique : ≥ 90 % rattachés ; absence/XI non nuls seulement là où
  toutes les preuves historiques nécessaires se recoupent. Aucun seuil inventé.

Méthode : docs/mission036-publication.md. Aucune fusion de la PR n'est autorisée
par cet ordre ; l'exécution sur sa branche est explicitement demandée.
