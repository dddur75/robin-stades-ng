# Robin Experience V1 — rapport de livraison

## Résumé

Robin Live est devenu une porte d’entrée française, progressive et mobile-first. La refonte remplace une navigation plate d’environ 24 vues et un composant de 2 771 lignes par huit routes cohérentes, un espace Expert explicite, une couche de présentation et des composants spécialisés. Les données scientifiques et le snapshot source restent inchangés.

## État de référence

- `main` résolu : `c512c7bc20f9272cd1b91cc3acf8605500541185`.
- Artefact Jalon 12 vérifié en lecture seule : `jalon12-pilot-30314975830`.
- Révision de l’artefact : `2469e57ec4b2ef2849f9e707f63843033ec026e6`.
- 9 fixtures, 441 fenêtres actives, 531 traces legacy inactives, 18 captures physiques, 0 observation profonde, 0 candidat, 0 décision.

## Livrables produit

### Accueil / Robin Live

Explique en moins de dix secondes le nombre de rencontres, les preuves, la prochaine capture, la bankroll fictive et la raison du NO BET. Ajoute « Depuis votre dernière visite » dans le stockage local, sans donnée personnelle.

### Matchs et fiche

Neuf cartes, recherche, filtres, tri, liste/calendrier et fiche à neuf onglets. Seuls les agrégats de cotes réellement observés sont montrés pour Marseille – Strasbourg. Les joueurs, absences, compositions et tactiques utilisent des états vides ou d’attente explicites.

### Observatoire

Indicateurs, frise des captures, matrice de couverture, progression des gates, fournisseurs, volume R2 et coûts. La matrice devient verticale sur mobile.

### Laboratoire

Huit hypothèses H11 racontées comme questions football avec mécanisme, données requises, support minimal, progression et raison de blocage.

### Résultats

Recherche historique, tests prospectifs, décisions shadow et résultats réglés sont séparés. Sans décision, la page affiche « Aucun pari simulé » et « Non applicable », pas un ROI de 0 %.

### Méthode

Présente Observer → Vérifier → Tester → Publier → Suivre, le NO BET, la bankroll fictive, la publication des pertes et les limites.

### Expert

Regroupe données/qualité, modèles, simulations, coûts et système. Les tableaux proposent recherche, tri, colonnes masquables et export CSV français.

## Langue

- Catalogue `fr-FR` actif.
- Catalogue `en-GB` à clés identiques, non public.
- 36 statuts présentés avec explication, ton, icône et gravité.
- 22 entrées de glossaire.
- Allowlist anglaise publique strictement testée.
- Dates, nombres, pourcentages, octets et heures localisés.

## Design et mobile

Palette bleu nuit, blanc cassé, vert Robin, bleu information, orange attention, rouge erreur et violet recherche. Le rendu évite tout code casino. Navigation inférieure, cartes empilées, matrices verticales, scroll local, cibles tactiles et textes longs ont été vérifiés aux six résolutions demandées.

## Accessibilité

Lien d’évitement, landmarks, titres, focus visible, libellés, `aria-pressed`, onglets, progressions, résumé des graphiques, réduction des mouvements et couleurs doublées d’un symbole. Les défauts trouvés pendant le test navigateur ont été corrigés.

## Performance

- Dépendance graphique lourde : aucune.
- Image sociale : 1,34 Mo, contre 1,80 Mo pour l’ancien fichier.
- Assets client : 875 975 → 830 890 octets non compressés (−5,1 %).
- JavaScript client : 849 102 → 783 519 octets (−7,7 %), plafond CI 850 000.
- Build local comparable : 5,40 → 4,54 secondes.
- Régression visuelle : environ 15 secondes.
- Source principale : 2 771 → 10 lignes ; 15 composants spécialisés remplacent le monolithe.
- Assets : 9 → 16, conséquence attendue du découpage en chunks par responsabilité.

## Validation

- 12 tests frontend/SSR/i18n réussis.
- 5 scénarios visuels réussis.
- 744 tests Python réussis.
- Ruff, mypy strict (107 fichiers), Bandit, pip check, compileall, YAML/JSON et détection de secrets réussis.
- Tête Alembic locale vérifiée à `0009_jalon12_observatory` ; cycle PostgreSQL complet exécuté par la CI dédiée.
- lint frontend réussi.
- build production réussi.
- navigation navigateur et six tailles réussies.
- intégrité du snapshot et invariants vérifiés par test.
- validations Python, sécurité, migrations et CI consignées au moment de la PR.

## Science et sécurité

Invariants confirmés et non modifiés :

```text
STORAGE_PAUSED
P3/P4_PAUSED
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

Aucun résultat, hash, gate, workflow, budget, règle de capture ou décision n’est modifié. Aucun fournisseur n’a été appelé. Aucune capture, écriture R2, mise, publication sociale, suppression ou connexion bookmaker n’a été effectuée.

## Publication

- Branche : `codex/robin-experience-v1-french-dashboard`.
- Commit fonctionnel : `6fca54a61a850526eb38414869a372bf8b66b644`.
- PR : [#19 — Robin Experience V1 — Dashboard français et UX progressive](https://github.com/dddur75/robin-stades-ng/pull/19).
- Site privé, version 14 : [ouvrir Robin Experience V1](https://robin-stades-shadow-cockpit.dddur.chatgpt.site).

La PR reste en brouillon et non fusionnée. La CI distante valide notamment le cycle PostgreSQL et publie l’artefact de captures.
