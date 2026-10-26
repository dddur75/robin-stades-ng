# Réponse à Gemini — ronde 2

Les cinq constats bloquants puis les trois majeurs sont confirmés et corrigés localement, sans commit.

| Constat | Correction et preuve synthétique (`test_round2_regressions.py`) |
|---|---|
| 1 — Déduplication | Clé incluant ligne et période ; une évaluation évaluable prime sur une exclusion sans cote. La perte reste au bilan. |
| 2 — Neutralisation / retrait | Slot distinguant le match ; une rétrogradation de cote, statut ou certitude ne remplace pas la preuve antérieure. Omissions et rétrogradations suspendent la comparabilité. Une sélection retenue sans règlement bloque le rapport après son coup d'envoi. |
| 3 — Combinés | Même auteur et observation du combiné avant chaque jambe. Une correction de jambe invalide le résultat périmé du combiné ; le rapport attend le résultat corrigé avec audit et son évaluation. Le test vérifie ensuite la mise à −1. |
| 4 — Couverture | Toutes les visites planifiées de la fenêtre entrent au dénominateur, y compris les sources sans contribution. Sans `at`, référence déterministe à la dernière observation du journal. |
| 5 — Temps | Monotonie de toutes les observations, y compris visites terminées, retraits, identités et définition de cohorte. Une visite future seulement planifiée ne constitue pas une observation. Cotes datées au plus tard à l'observation de contribution ; cote observée jamais antérieure à la première observation de version. Une cote déclarée peut précéder sa découverte. |
| 6 — Identités | Tout alias entre identités différentes est refusé avec `similarite`. Chaque révision attestée est un snapshot complet : les comptes omis retrouvent leur identité propre. |
| 7 — Reprises | Les relais ayant un lien sortant ne peuvent plus être choisis comme racine d'origine. |
| 8 — Catégorie cotée | Au moins une cote explicite obligatoire dans le modèle et le JSON Schema ; compteur de catégorie soumis à l'évaluabilité de la base de cote choisie. |

Les tests des contre-exemples ont été exécutés avant les corrections : 25 échecs initiaux. Le cas supplémentaire « première mi-temps » était une fixture de test incorrecte (période actuellement non prise en charge), retirée sans ouvrir ce marché. Les 24 autres contre-exemples échouaient bien pour les défauts décrits. Après correction : **273 tests du domaine passent** (2,24 s). Typage : 9 fichiers sans erreur. L'ordre des imports a été corrigé après le contrôle lint.

Le constat mineur 9 est aussi corrigé : la fixture rétrospective évalue désormais la contribution effectivement persistée. Deux attentes anciennes ont été adaptées aux invariants demandés (toutes les visites comptées, alias similaire refusé dès sa construction), ainsi que les attentes d'erreur pour les dates invalides.

Aucun constat de fond contesté. Ces tests constituent une vérification technique, pas une relecture indépendante ni une acceptation par David. Preuve de mesure : `ENG.SOURCE_OBSERVATORY.ROUND2.T7.20261026` (rapport final et evidence graph complétés après T7).
