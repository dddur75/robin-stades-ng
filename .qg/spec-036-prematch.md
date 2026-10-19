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

## Reprise

Sources et calculs livrés ; vérification ciblée 433 tests verts. Suite complète
en cours avec les temporaires sur stockage local. Restent : consigner son bilan,
ouvrir l'unique PR et y terminer par le tableau de couverture.
