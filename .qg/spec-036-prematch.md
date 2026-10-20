# Mission 036 — critères avant-match, complément demandé par David

Source : demande utilisateur de ce chat, design strict validé le 20 octobre 2026.
Une branche issue de main, une seule PR, plusieurs commits. Aucun appel
fournisseur, aucune écriture Neon, aucun pari, aucun fichier interdit modifié.
La collecte de la mission 036 n'est ni relancée ni étendue. Holdout 2025 exclu.

## Résultat demandé

À partir des données déjà collectées, inventorier la couverture réelle par
ligue/saison puis produire un Parquet par saison, à clé fixture/date/domicile/
extérieur, et des critères pour chaque équipe. Toute fenêtre est strictement
antérieure au match cible, avec tests par recalcul décalé sur échantillon.

- `tc_neutre10` reste null faute de tirs cadrés horodatés.
- Ajouter `etat_score_buts10` : minutes à écart <= 1 et buts pour/contre dans
  cet état, sur les dix derniers matchs.
- `absents_cles` : part des minutes des cinq derniers matchs du top 11 saison
  absente du onze officiel cible ; saison arrêtée à la date de la cible.
- `force_xi` : note moyenne antérieure des titulaires sur dix matchs moins
  moyenne antérieure de l'équipe sur la saison.
- Le onze de la feuille officielle est admissible avant-match sur instruction
  explicite de David ; `source_compo = feuille_officielle`.
- `cong21` et repos restent nulls sans calendrier toutes compétitions prouvé.
- `cadre_suspendu` : cadre >= 600 minutes sur dix matchs, rouge direct = un
  match ; cumul de jaunes uniquement si la règle de ligue est documentée,
  sinon partie cumul nulle et motif explicite.
- `points_tardifs5` : somme des points finaux moins points au score de la 80e,
  à partir des minutes des buts, sur cinq matchs.

La couverture conserve tous les matchs de la population au dénominateur,
compte zéro et faux comme non nuls et donne les motifs des nulls. La PR doit
se terminer par le tableau complet critère × ligue × saison.

Méthode et conventions : `docs/prematch-criteria.md`.
Livrables : `reports/prematch/mission036/`.

## Résumé de construction — 20 octobre 2026

- PR unique #121, branche `codex/036-prematch-criteria`, six commits depuis main.
- Sept Parquet 2018–2024 : 70 084 matchs, clés complètes, 38 ligues, 225 cellules de couverture.
- Source figée `fac718f3` : 17 433 contextes ; 52 651 matchs restent au dénominateur sans contexte.
- État-score : 15 061 lignes équipe-match ; points tardifs : 16 113 ; suspension rouge de cadre : 9.
- Absences/XI restent nulls faute de croisement ; tirs, cumul de jaunes et calendrier toutes compétitions non prouvés.
- 577 tests ciblés verts, 28 tests nouveaux, 172 recalculs décalés ; sécurité initiale contrôlée seulement au seuil moyen/haut.
- Suite globale : 4 066 verts / 50 ignorés / 36 échecs ; provenance corrigée, 35 échecs de capture documentés.
- Reste : revue indépendante et disponibilité d'un index de rattachement / des payloads déjà collectés hors holdout.
- Zéro appel fournisseur, accès R2, écriture Neon ou pari ; fichiers interdits inchangés ; aucune fusion.

## Complément de relecture — PR #121

- Corriger sur la même branche le job Quality and domain tests : quatre alertes Bandit faibles oubliées par le contrôle local `-ll`.
- Exceptions ciblées B404/B603 pour Git local sans shell et sans protocole ; aucun seuil CI modifié.
- Documenter « Pourquoi 25 % seulement » : 174 calendriers non publiés, 29 ligues × six saisons, exactement 52 651 contextes.
- Audit indépendant des reçus et de l'inventaire ; plan ≥ 90 % à zéro appel fournisseur si les objets attestés sont disponibles.
- Vérifier le job distant après push ; conserver le tableau de couverture à la fin de la PR.
