# Hypothesis Research Cockpit V2 — recette privée

## Résultat

Statut local : `READY_FOR_REVIEW`.

Publication : `NOT_DEPLOYED_BY_DESIGN`.

La recette porte sur la page privée de compréhension de couverture, pas sur les écrans scientifiques conditionnels qui restent fermés.

## Matrice exécutée

| Contrôle | Résultat | Preuve |
|---|---|---|
| modèle compact et fail-closed | PASS, 5/5 | `tests/p0-coverage-desk.test.ts` |
| SSR et absence de sources compactes dans les assets client | PASS, 2/2 | `tests/p0-coverage-desk-ssr.test.mjs` |
| catalogues FR/EN | PASS, 8/8 | `tests/i18n.test.mjs` |
| TypeScript | PASS | `tsc --noEmit -p tsconfig.app.json` |
| ESLint complet | PASS | application et tests, hors sorties générées |
| build Vinext de production | PASS | cinq environnements et route privée compilés |
| Playwright Desk | PASS, 3/3 | vérité, matrice responsive, clavier/ancres/zoom |
| Playwright global | PARTIAL | 19 PASS ; arrêt sur paquet historique optionnel absent ; 6 scénarios série non exécutés |
| tailles | PASS | 360, 375, 390, 430, 768, 1440 et 1920 px |
| zoom texte 200 % | PASS | 1440 px, contenu utilisable et document borné |
| mouvement réduit | PASS | contexte Playwright `reducedMotion: reduce` et CSS dédié |
| console / erreurs de page | PASS | aucune erreur sur le parcours Desk |
| requête navigateur externe | PASS | aucune origine autre que le serveur local |
| hydratation | PASS | `html[data-robin-hydrated="true"]` |
| liens conditionnels | PASS | Données et Hypothèse atteignables au clavier ; Stratégie et Matchs désactivés |
| état vide / inconnu | PASS | 0 cellule fermée, trois taux `UNKNOWN`, rendu « Non mesuré » |
| français | PASS | `html[lang="fr-FR"]`, accents et apostrophes UTF-8 |

Les suites unitaires Cockpit passent à 32 PASS / 4 SKIP pour les tests Node et 96/96 pour les tests TypeScript. Les 4 skips et l’arrêt Playwright global ont la même cause déclarée : les preuves historiques publiées ne sont pas présentes dans ce worktree. Le test en échec attend les courbes historiques d’une surface préexistante et reçoit son état borné « Ventilations historiques indisponibles » ; il ne traverse ni le modèle, ni la route, ni les styles du Desk P0. Aucune relance identique ni reconstruction artificielle n’a été effectuée.

La CI distante du commit exact restera la preuve autoritative du périmètre versionné.

## Captures

Les captures reproductibles sont générées localement sous `cockpit/.ci/visual-regression/captures/` et restent ignorées par Git :

- `p0-coverage-desk-360.png` ;
- `p0-coverage-desk-375.png` ;
- `p0-coverage-desk-390.png` ;
- `p0-coverage-desk-430.png` ;
- `p0-coverage-desk-768.png` ;
- `p0-coverage-desk-1440.png` ;
- `p0-coverage-desk-1920.png` ;
- `p0-coverage-desk-1440-text-zoom-200.png`.

Inspection humaine effectuée sur 390 px, 1440 px et zoom 200 %. Deux défauts ont été corrigés avant gel : métriques comprimées sous 430 px et libellés de métriques superposés au zoom. La table large reste volontairement défilante et focalisable sur mobile.

## Confidentialité et séparation serveur/client

- les contrats et rapports compacts sont composés uniquement par `p0-coverage-desk.server.ts` ;
- le modèle client est agrégé à 16 familles ;
- les identifiants de contrat/catalogue, cellules, endpoints et hashes de preuve sont absents de tous les fichiers JavaScript client ;
- aucune valeur non prouvée n’est convertie en zéro ;
- une mutation de dimensions, famille, grain, compte, taux ou effet externe fait échouer la construction du modèle.

Les chemins absolus injectés par Vinext dans le CSS de polices du rendu local sont des sorties générées et ignorées. Ils ne figurent ni dans les sources, ni dans les artefacts versionnés, ni dans les bundles client contrôlés ; aucun déploiement n’est réalisé dans ce lot.

## Accessibilité

- hiérarchie de titres et sections nommées ;
- navigation conditionnelle nommée ;
- table avec en-têtes de colonnes et lignes ;
- région défilante focalisable avec focus visible ;
- états bloqués portés par texte et `aria-disabled` ;
- accordéons natifs `details/summary` ;
- aucune information reposant uniquement sur la couleur ;
- comportement `prefers-reduced-motion` et `forced-colors` défini.

Limite déclarée : aucune session manuelle NVDA + Edge n’a été exécutée dans ce lot. Elle reste une gate de recette humaine avant toute publication, sans bloquer la revue privée du contrat.

## Critères de rejet

Le verdict doit redevenir `PARTIAL` si un taux inconnu est affiché comme 0 %, si une cellule est annoncée fermée sans preuve E3/E4 et ventilation compacte par famille, si une source brute entre dans un asset client, si Stratégie ou Matchs deviennent cliquables, si une requête externe apparaît, ou si un écran de performance est ajouté avant les gates scientifiques.

La refonte visuelle et la publication restent soumises à la revue owner décrite dans [DASHBOARD-UX-OWNER-REVIEW-PENDING.md](../../DASHBOARD-UX-OWNER-REVIEW-PENDING.md).
