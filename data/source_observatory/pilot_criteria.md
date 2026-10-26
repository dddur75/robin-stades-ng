# Critères chiffrés — pilote « Dossier fidèle » (GELÉS avant collecte)
Gelé le 2026-10-26 (avant la journée de Ligue 1 du 31/10–02/11/2026). Toute modification après le commit de gel est interdite ; un écart est consigné, jamais corrigé rétroactivement (§17 : critères numériques fixés avant évaluation).

Périmètre : publications publiques pré-match de la journée 31/10–02/11/2026, sources de `pilot_sources.csv` d'état `a_construire` ou `manuel`. Aucun contournement d'accès, aucun payload brut dans Git (métadonnées + SHA-256).

## C1 Couverture et échantillon
- C1.1 Couverture de visites (réussies/planifiées, par source et globale) ≥ 80 % ; rapportée telle quelle, jamais présentée comme rappel.
- C1.2 ≥ 25 sources effectivement visitées, dont ≥ 8 petits auteurs/inconnus.
- C1.3 ≥ 100 contributions structurées au total, dont ≥ 30 issues de petits/inconnus.
- C1.4 L'échantillon contient au moins : 5 pertes, 1 correction/modification observée, 1 panne de collecte documentée.

## C2 Temps et pré-match
- C2.1 100 % des versions ont les 4 temps présents ou explicitement « absent » (aucune valeur imputée) ; UTC + fuseau d'origine.
- C2.2 100 % des contributions découvertes après le coup d'envoi sont classées « rétrospectives » et exclues du bilan pré-match.
- C2.3 Pour toute modification observée, la version antérieure au match fait foi (scénario A) : 0 exception.

## C3 Extracteur (jeu de référence ≥ 40 textes réels annotés)
- C3.1 Précision (marché ET sélection exacts parmi les contributions « résolues ») ≥ 85 %.
- C3.2 Cotes déclarées inventées ou reconstruites : 0 (tolérance nulle).
- C3.3 Cas ambigus (annotation « non résolu ») correctement laissés « non résolu » ≥ 90 %.
- C3.4 Rappel (annotations résolues retrouvées) rapporté, sans seuil.
- C3.5 Conformité JSON Schema : 100 % des sorties.

## C4 Rapprochement match/marché
- C4.1 ≥ 90 % des contributions résolues rapprochées au bon match (contrôle manuel sur ≥ 30 tirées au sort, graine déclarée).
- C4.2 100 % des rapprochements incertains marqués avec niveau de certitude ; 0 fusion d'identités sur pseudo similaire.

## C5 Résultat et évaluation
- C5.1 Règlement automatique uniquement avec règle documentée ; sinon « en_attente » (0 règlement sans règle).
- C5.2 Évaluation à mise unitaire (gagné c−1, perdu −1, remboursé 0) ; contributions sans cote : descriptif seul, non évaluées.
- C5.3 Aucun classement ni conclusion de performance : états Découverte/En observation seulement ; pas de « Comparable » ni « Signal prospectif ».

## C6 Reproductibilité et intégrité
- C6.1 Recalcul complet depuis le stockage append-only = résultats identiques (empreintes) : 100 %.
- C6.2 Reprises certaines groupées ; 0 groupe fondé sur la seule similarité.
- C6.3 Rapport final : écarts, ambiguïtés, pannes et limites listés ; jalon « Dossier fidèle » = PASS seulement si C1–C6 sont tous satisfaits ; sinon PARTIAL avec critères manqués nommés.
