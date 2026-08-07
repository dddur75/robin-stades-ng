# Dashboard Owner Decision Matrix V1

Source : `docs/ux/DASHBOARD-OWNER-REVIEW-PACK-V1.md`, 28 décisions. Cette
matrice prépare la revue de David ; elle ne tranche aucun choix qui modifierait
réellement l'expérience et n'autorise ni refonte, ni déploiement.

Valeurs : priorité `P0/P1/P2`, choix propriétaire `YES/NO`, donnée réelle
`YES/NO/PARTIAL`. `OWNER_REVIEW` signifie que David décide avant toute mission
d'implémentation.

| decision_id | route | problem | user_profile | current_state | desired_state | depends_on_real_data | priority | owner_decision_required | implementation_mission |
|---|---|---|---|---|---|---|---|---|---|
| UX-001 | `/`, `/robin-live` | Deux accueils identiques | tous | doublon visible | choisir route canonique et redirection | NO | P1 | YES | OWNER_REVIEW puis IA_NAVIGATION |
| UX-002 | navigation globale, mobile | Six destinations documentées, sept affichées | tous | Expert compact en mobile | valider destinations publiques et traitement d'Expert | NO | P1 | YES | OWNER_REVIEW puis IA_NAVIGATION |
| UX-003 | `/laboratoire`, `/expert` | Position publique ou experte ambiguë | analyse, expert | Laboratoire sous Expert | décider son audience et son emplacement | NO | P1 | YES | OWNER_REVIEW puis IA_NAVIGATION |
| UX-004 | `/hypotheses`, `/laboratoire` | Responsabilités qui se chevauchent | analyse | familles et découvertes dupliquées | définir une responsabilité distincte par page | NO | P1 | YES | OWNER_REVIEW puis IA_NAVIGATION |
| UX-005 | `/hypotheses/*`, `/laboratoire` | Deux taxonomies nommées « familles » | tous | 28 et 5 familles confondues | choisir deux noms sans ambiguïté | NO | P1 | YES | OWNER_REVIEW puis LANGUAGE_TAXONOMY |
| UX-006 | `/expert/qualite-donnees` | Audience et accès non tranchés | expert | route difficile à trouver | décider visibilité et contrôle d'accès | NO | P1 | YES | OWNER_REVIEW puis ACCESS_CONTROL |
| UX-007 | `/expert` | Qualité des données introuvable | expert | aucune entrée directe | accepter ou refuser une entrée dédiée | NO | P2 | YES | OWNER_REVIEW puis IA_NAVIGATION |
| UX-008 | `/matchs/[id]` | Quatre onglets toujours vides | tous | Joueurs, Absences, Composition, Tactique visibles | masquer, regrouper ou conserver avec promesse honnête | YES | P1 | YES | OWNER_REVIEW puis MATCH_DETAIL |
| UX-009 | `/matchs/[id]` | Sémantique d'onglets incomplète | clavier, lecteur d'écran | `tab` partiel sans contrat complet | valider tablist, panels, focus et ARIA | NO | P1 | NO | ACCESSIBILITY_VALIDATION |
| UX-010 | `/hypotheses/*` | Route active peu perceptible | tous | sous-navigation ambiguë | état actif visible et annoncé | NO | P2 | NO | IA_NAVIGATION |
| UX-011 | toutes routes | Termes techniques non nivelés | essentiel, analyse, expert | jargon mélangé | classer chaque terme par niveau | NO | P1 | YES | OWNER_REVIEW puis LANGUAGE_TAXONOMY |
| UX-012 | hypothèses, laboratoire, résultats | Nature des métriques ambiguë | tous | historique, simulé et prospectif proches | afficher explicitement la nature de chaque métrique | YES | P0 | NO | DATA_TRUTH_POLICY |
| UX-013 | en-tête global | Fraîcheur du snapshot peu saillante | tous | texte présent mais discret | date, âge et portée compris immédiatement | YES | P1 | YES | OWNER_REVIEW puis DATA_FRESHNESS |
| UX-014 | CSS global, hypothèses | Typographie trop petite | mobile, accessibilité | textes de `.47rem` à `.68rem` | fixer minimum et exceptions | NO | P1 | YES | OWNER_REVIEW puis DESIGN_SYSTEM |
| UX-015 | Desk P0, tableaux | Responsive non recetté sur cibles | mobile, desktop | comportement non validé | recette 390 px, 1440 px et zoom 200 % | NO | P1 | NO | RESPONSIVE_VALIDATION |
| UX-016 | états vides globaux | Risque d'inventer zéro/disponibilité | tous | états généralement honnêtes | conserver UNKNOWN/absence sans coercition | YES | P0 | NO | DATA_TRUTH_POLICY |
| UX-017 | erreurs spécialisées | Résilience à préserver | tous | explication et « Réessayer » présents | conserver l'action et le contexte | NO | P1 | NO | RESILIENCE_POLICY |
| UX-018 | App Router global | Boundaries de marque absentes | tous | aucun global error/loading/not-found | décider d'en créer ou d'assumer l'absence | NO | P2 | YES | OWNER_REVIEW puis RESILIENCE_UI |
| UX-019 | shell et routes clés | Accessibilité humaine non recettée | clavier, lecteur d'écran | fondations partielles | tester clavier, NVDA/Edge, mouvements réduits, couleurs forcées | NO | P1 | NO | ACCESSIBILITY_VALIDATION |
| UX-020 | navigation globale | Hiérarchie finale non gelée | tous | destinations concurrentes | valider Accueil → Matchs → Hypothèses → Observatoire → Résultats | NO | P1 | YES | OWNER_REVIEW puis IA_NAVIGATION |
| UX-021 | hypothèses, résultats, matchs | Propriété, règle, stratégie, marché et cote confondables | tous | vocabulaire proche | séparation sémantique permanente | PARTIAL | P0 | NO | DATA_TRUTH_POLICY |
| UX-022 | fiches historiques | Six graphiques sans priorité de lacunes | analyse, expert | graphiques existants | auditer puis prioriser comparaison, incertitude, dépendances | YES | P2 | YES | OWNER_REVIEW puis DATAVIZ_AUDIT |
| UX-023 | chaque graphique | Grain et dénominateur incomplets | analyse, expert | contexte variable | afficher grain, période, dénominateur, UNKNOWN et provenance | YES | P0 | NO | DATAVIZ_DATA_CONTRACT |
| UX-024 | vues essentielle/analyse/expert | Charge cognitive élevée | tous | niveaux encore perméables | choisir l'information visible à chaque niveau | NO | P1 | YES | OWNER_REVIEW puis PROGRESSIVE_DISCLOSURE |
| UX-025 | toutes décisions | Gouvernance UX non structurée | owner | décisions dans une checklist | tracer statut, justification et preuve avant changement | NO | P0 | NO | OWNER_DECISION_GOVERNANCE |
| UX-026 | Desk P0 | Blocage global historique incompatible avec V2 | tous | vue E0/PR26 non actualisée | décider comment montrer les gates locales | YES | P1 | YES | OWNER_REVIEW puis CAPABILITY_STATUS_UX |
| UX-027 | observatoire, science | `READY` opérationnel confondu avec readiness scientifique | tous | namespaces visuels proches | distinguer opérationnel de `READY_STRICT/RECONSTRUCTED` | YES | P1 | YES | OWNER_REVIEW puis CAPABILITY_STATUS_UX |
| UX-028 | `/matchs/[id]` | Hypothèses globales présentées comme liées au match | tous | association non déterministe | masquer le bloc ou définir son contrat d'association | YES | P1 | YES | OWNER_REVIEW puis MATCH_HYPOTHESIS_LINK |

## Regroupement de revue

- navigation : UX-001, 002, 003, 004, 006, 007, 010, 020 ;
- premier écran : UX-013, 024, 026, 027 ;
- données et fraîcheur : UX-012, 013, 016, 023 ;
- hypothèses : UX-004, 011, 021, 026, 028 ;
- familles et arbres : UX-005, 010 ;
- stratégies : UX-012, 021, 027 ;
- matchs : UX-008, 009, 028 ;
- graphiques : UX-022, 023 ;
- langage : UX-005, 011, 021, 027 ;
- mobile : UX-002, 014, 015 ;
- design : UX-014, 017, 018, 024, 025 ;
- accessibilité : UX-009, 014, 015, 019.

## Ordre de dépendance

```text
UX-001 -> UX-002 -> UX-020
UX-003 -> UX-004 -> UX-020
UX-006 -> UX-007
UX-008 -> UX-009
UX-012 -> UX-021 -> UX-022/UX-023
UX-026 -> UX-027
```

Les validations UX-009, 015, 019 et 023 ne sont pas des préférences. Les choix
UX-001 à 008, 011, 013, 014, 018, 020, 022, 024, 026 à 028 restent ouverts pour
David lorsque leur solution modifierait l'expérience. Aucun composant frontend
n'a été modifié.
