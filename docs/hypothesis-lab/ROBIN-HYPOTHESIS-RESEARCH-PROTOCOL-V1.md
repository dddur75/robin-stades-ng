# Robin Hypothesis Research Protocol V1

```text
EXPLORATORY
UNVALIDATED
NO_PROMOTION
NO_BET
```

## Résultat de cette mission

Cette mission livre un catalogue et des protocoles de falsification. Elle ne livre aucune
découverte sportive, aucun résultat de backtest, aucune sélection fondée sur un rendement
historique et aucune recommandation d'action externe.

Le catalogue V1 est construit sur la révision immuable
`6cb8de636890959bd2ddb7e1c791a2eb04ee8763`. Il contient :

- 336 formulations brutes persistées : trois angles déclarés pour chacune de 112 questions
  scientifiques semées (`MECHANISM`, `OBSERVABLE_ESTIMAND`, `FALSIFICATION`) ;
- 112 estimands/assertions distincts observés après projection sémantique V2, clustering et
  adjudication ; le validateur accepte le contrat demandé de 80 à 150 et ne force pas 112 ;
- 8 familles principales de multiplicité ;
- 224 tests primaires au maximum, car les deux branches de-vig 1X2 sont toujours comptées
  et rapportées séparément ;
- 25 protocoles prioritaires gelés, tous au statut `NOT_RUN` ;
- 9 contrôles négatifs planifiés, tous au statut `NOT_RUN`.

Les six rapports JSON portent les quatre labels de sécurité ci-dessus, un hash canonique de
contenu et des compteurs d'effets externes tous égaux à zéro.

## 1. Autorité scientifique et limites

Le contrat mathématique est `ROBIN_SCIENTIFIC_TRUTH_KERNEL_V1`. L'autorité de-vig globale
reste `DEVIG_PROTOCOL_CONFLICT`. Le contrat temporel est
`robin-point-in-time-lineage-v1`.

Le dépôt ne prouve actuellement aucune des 72 surfaces historiques comme point-in-time.
Une donnée historique utile à l'exploration ne devient donc jamais, par simple reconstruction,
une preuve de disponibilité. Tous les protocoles V1 restent prospectifs : ils exigent des
reçus immuables et échouent fermés si cette preuve manque.

Cette mission n'a effectué :

- aucun appel provider ;
- aucun accès Neon ou PostgreSQL de production ;
- aucune opération R2 ;
- aucun workflow live ;
- aucun achat ;
- aucun calcul de performance sportive ;
- aucun pari et aucune promotion.

## 2. Réconciliation avec le prior art du dépôt

Le catalogue V1 n'est pas une réécriture des résultats antérieurs. Les objets existants sont
utilisés uniquement pour l'identité, le périmètre et la détection de doublons.

| Source existante | Réutilisation autorisée | Réutilisation interdite |
|---|---|---|
| `docs/registre_hypotheses_v1.yaml` | atomes, alias `S###`, `HC-##`, dépendances | statut ou chiffre historique comme preuve |
| campagne J10 | bandes de prix, marges, identité des trois règles nommées | classement historique ou métrique de rendement |
| Genome V2 | familles de données, propriétés et blocages | relance des campagnes atomiques ou de paires |
| Phase-C V2 | contrat de multiplicité et types de contrôles | import de résultats ou nouveau census massif |
| Truth Kernel V1 | méthodes/version/hash de-vig explicites | choix de méthode d'après le meilleur résultat observé |
| Point-in-Time Lineage V1 | reçus, `available_at`, cutoff et mutations du futur | assimilation d'une reconstruction à un reçu |

Chaque hypothèse contient `prior_art_refs` et
`prior_art_usage = IDENTITY_AND_SCOPE_ONLY_NO_RESULT_IMPORT`.

## 3. Génération large et déduplication

### 3.1 Univers initial

Le registre `tools/hypothesis-lab/raw-candidates-v1.json` est antérieur aux identifiants
`RDS-HYP`. Il contient exactement trois formulations de chacune des 112 questions semées :
mécanisme supposé, estimand observable et voie de réfutation. Il est donc décrit honnêtement
comme **336 formulations de 112 questions**, et non comme 336 idées conçues indépendamment.
Il ne contient ni ID canonique, ni résultat sportif, ni sweep de seuil. Le rapport de
déduplication conserve ensuite les 336 lignes, les clusters effectivement obtenus et la preuve
d'adjudication. Dans cette source V1, les 112 questions restent distinctes et chaque cluster a
trois formulations ; ces nombres sont un résultat de la signature gelée, pas une contrainte du
clustering. Les invalidités de protocole sont traitées par les neuf contrôles négatifs,
pas utilisées pour gonfler l'univers candidat.

### 3.2 Deux niveaux d'identité

Le `estimand_hash` est le SHA-256 de `ESTIMAND_SIGNATURE_V2` : marchés, population, unité,
tags de features normalisés, modérateurs, cible, horizon, échelle d'effet et cutoff. Pour les
11 signatures de base réellement en collision, un AST structuré `transform`/`comparator`
distingue l'opérateur et ses opérandes ; cet AST est interdit sur les 84 singletons. La clé
exclut les IDs candidats/canoniques, `seed_question_hash`, `concept_key`, titre, claim, direction,
type/orientation du claim, sélection du portefeuille et seuils numériques. Le `assertion_hash`
ajoute ensuite la direction, le type de claim et son orientation.
`semantic_core_hash` est un alias contrôlé de cet assertion hash.

Le `protocol_variant_hash` ajoute définition opérationnelle, seuils, contrat de falsification,
règle d'échantillon, cutoff, correction statistique et triples de-vig. Deux protocoles peuvent
ainsi partager un estimand tout en restant des variantes traçables.

Les identifiants `RDS-HYP-V1-<16 HEX>` ne sont assignés qu'après clustering et dérivent de
l'assertion hash. Inverser l'ordre des
sources ne change ni les identifiants ni les octets générés. Un doublon sémantique portant
des assertions contradictoires doit échouer fermé.

## 4. Schéma obligatoire d'une hypothèse

Chaque objet de `hypothesis-universe-v1.json` déclare au minimum :

| Domaine | Champs |
|---|---|
| Identité | `hypothesis_id`, `estimand_hash`, `assertion_hash`, `semantic_core_hash`, `protocol_variant_hash`, `concept_key`, `title` |
| Proposition | `intuition`, `assumed_causal_mechanism`, `null_hypothesis`, `expected_effect` |
| Population | `market`, `population`, `unit_of_analysis`, `eligibility_condition` |
| Données | `required_variables`, `required_data`, `data_dependencies` |
| Temps | `temporal_cutoff`, `point_in_time.event_at`, `available_at`, `cutoff_at` |
| Marché | `devig_protocol`, `truth_kernel_version` |
| Mesure | `primary_metric`, `secondary_metrics`, `minimum_sample_size` |
| Multiplicité | `multiplicity_family`, `statistical_correction` |
| Hors échantillon | `holdout`, `walk_forward`, `league_holdout`, `season_holdout` |
| Contradiction | `adversarial_slices`, `falsification_contract`, `falsification_criterion`, `abandonment_criterion` |
| Faisabilité | `operational_definition`, `compute_cost`, `prior_art_refs`, `status` |

Le statut distingue le cycle du dépôt et les quatre axes de mission :

- `lifecycle_status = DISCOVERED` ou `DATA_GATE_BLOCKED` ;
- `scientific_status = NOT_TESTED` ;
- `research_status = EXPLORATORY` ;
- `validation_status = UNVALIDATED` ;
- `promotion_status = NO_PROMOTION` ;
- `betting_status = NO_BET`.

Cinq hypothèses portent `DATA_NOT_PROSPECTIVELY_OBSERVABLE` dans leur contrat point-in-time :
liquidité/limites réelles, saut de prix relié à une publication non versionnée et trois
formulations sur le changement d'entraîneur. Elles restent dans le catalogue pour documenter
la question scientifique, mais leur condition d'éligibilité reste fausse tant qu'une source
receipt-backed gouvernée n'existe pas.

## 5. Familles et multiplicité

Chaque hypothèse appartient à une seule famille principale. L'exposition causale décide de
la famille ; ligue, bookmaker et domicile-extérieur restent des slices sauf si leur
interaction est l'estimand déclaré.

| Famille | Hypothèses | Tests max. | Premiers protocoles |
|---|---:|---:|---:|
| `FAMILY_1X2_PRICE_STRUCTURE` | 16 | 32 | 4 |
| `FAMILY_BOOKMAKER_MICROSTRUCTURE` | 12 | 24 | 3 |
| `FAMILY_MARKET_DYNAMICS` | 12 | 24 | 3 |
| `FAMILY_FORM_REGRESSION` | 16 | 32 | 3 |
| `FAMILY_VENUE_COHORT` | 12 | 24 | 3 |
| `FAMILY_SCHEDULE_FATIGUE` | 14 | 28 | 3 |
| `FAMILY_TEAM_STATE_RANKING` | 14 | 28 | 3 |
| `FAMILY_CROSS_MARKET` | 16 | 32 | 3 |
| **Total** | **112** | **224** | **25** |

Dans chaque famille, la correction est Benjamini-Hochberg avec `q = 0.05`. Une seconde
correction est calculée sur la campagne complète ; la valeur rapportée doit être
`max(family_q, global_q)`. Un test bloqué reçoit conventionnellement `p = 1`. Aucun résultat
des branches de-vig n'est regroupé.

Le noyau, la famille, les exclusions, le minimum d'échantillon, les cutoffs, les branches et
les contrôles doivent être gelés avant matérialisation du snapshot d'analyse. La règle de
promotion de cette mission est `NO_PROMOTION_ALWAYS`.

## 6. De-vig sans arbitrage par résultat

Pour tout marché 1X2, deux branches sont obligatoires :

| Branche | `devig_method` | `devig_version` | `devig_definition_hash` |
|---|---|---|---|
| proportionnelle | `PROPORTIONAL` | `PROPORTIONAL_COMPLETE_MARKET_V1` | `265d91ae…076684` |
| Shin legacy | `SHIN` | `LEGACY_SHIN_VAGUE1_V1` | `3ff94a3d…75367` |

Le schéma lie méthode, version et hash comme un triple canonique indivisible ; croiser une
méthode avec la version ou le hash de l'autre est invalide. Chaque branche couvre exactement
une fois tous les marchés déclarés. La méthode est explicite, sans valeur par défaut. Les
sorties sont séparées ; une divergence ne désigne pas de méthode gagnante et empêche
l'assertion commune si elle contredit la direction préenregistrée.

Pour un marché binaire over/under, seule la méthode proportionnelle constitue une branche
indépendante. Demander Shin sur deux issues conduit à une équivalence proportionnelle dans le
noyau actuel et ne doit pas être compté comme un test supplémentaire. Les protocoles
cross-market combinent donc chacune des deux branches 1X2 avec le même composant total
proportionnel.

## 7. Contrat point-in-time

Le cutoff prédicteur par défaut est `H2`. EXP006 déclare explicitement `H24`, car son
estimand compare la déviation bookmaker H24 à une cible H2 post-cutoff :

```text
cutoff_at = kickoff_at - PT2H                 # défaut
cutoff_at(EXP006) = kickoff_at - PT24H        # prédicteur H24
available_at = max(trusted source_published_at, robin_first_observed_at)
available_at <= cutoff_at
robin_ingested_at <= cutoff_at
cutoff_at < kickoff_at
```

`event_at` est le temps du fait métier et ne prouve jamais la disponibilité. Une égalité
`available_at == cutoff_at` est admissible. Deux payloads différents au dernier instant
admissible, une absence de reçu, une date naïve ou un payload reçu après cutoff provoquent un
échec fermé.

Chaque source doit résoudre les champs de reçu : `receipt_id`, `source_name`,
`request_identity`, `payload_sha256`, `source_published_at`,
`robin_first_observed_at`, `robin_ingested_at`, `capture_code_revision`,
`storage_identity`, `availability_status` et `supersedes_receipt_id`.

Chaque dépendance est typée `FEATURE`, `ODDS`, `METADATA`, `TARGET` ou `LABEL`. Les trois
premiers rôles sont les seuls admissibles dans les features et l'éligibilité pré-cutoff. Une
cible `TARGET` est receipt-backed mais strictement postérieure au cutoff déclaré et ne peut
jamais devenir un prédicteur. Les protocoles 005 et 023 gèlent ainsi une cible H1 distincte
(`cutoff_at < available_at <= target_window_end`) pour, respectivement, la contraction de
dispersion et l'alignement cross-market ultérieur. EXP006 gèle de la même façon une cible H2
de déviation bookmaker, distincte de son prédicteur H24. Un label est
explicitement exclu de ces entrées ; il exige après l'événement `result_available_at` et
`settlement_receipt_at`, en plus des champs de reçu communs. Les snapshots prédicteurs,
`TARGET` et `LABEL` doivent porter des identités/hashes séparés. Une source absente ferme
simultanément le data gate, impose `DATA_GATE_BLOCKED` et maintient toute expérience à
`NOT_RUN`.

Les données suivantes sont interdites avant cutoff : résultat du match courant, settlement,
xG/tirs/cartons/événements post-match du match courant, correction reçue après cutoff et
artefact de modèle ou calibration créé après la prédiction.

Le test de mutation du futur doit ajouter, modifier, supprimer et réordonner des lignes
futures, puis injecter une correction tardive. Les hashes d'éligibilité, de feature et de
protocole antérieurs doivent rester identiques octet pour octet.

## 8. Dimensionnement et hors échantillon

Les tailles minimales sont des planchers conservateurs de planification, jamais une puissance
démontrée : référence normale à 80 %, alpha bilatéral brut 5 %, effet standardisé minimal de
0,15 ou 0,18 selon la famille et clustering par fixture. Le champ
`reference_power_is_demonstrated` reste `false`. La correction FDR est ensuite appliquée comme
déclaré.

Le plancher indépendant utilise l'approximation
`n = 2 × (z(0,975) + z(0,80))² / d²`, soit 698 unités pour `d = 0,15` et
485 pour `d = 0,18`. Chaque objet gèle aussi les hypothèses effectivement utilisées : variance
standardisée 1, ICC 0,05, taille moyenne de cluster 4 (design effect 1,15),
holdout 20 % (multiplicateur 1,25), multiplicité 1,15 et slices adversariales 1,25. Le maximum
du minimum familial et du calcul inflaté devient un plancher, pas une garantie de puissance.

Chacun des 25 protocoles gèle en plus une famille d'estimateur, une distribution de travail,
la transformation de la cible, le modèle de variance, la standardisation training-only et un
contraste primaire scalaire. Il préenregistre un dimensionnement Monte-Carlo spécifique au
modèle. Son contrat exécutable gèle la formule et le test de Wald, l'alternative signée au MDE,
la distribution de l'exposition (dont prévalence binaire ou structure paired/AR/spline), les
covariables de nuisance déclarées, huit strates ligue-saison, un ICC fixture de 0,05 et le grain
intra-fixture propre à l'estimand, ainsi que l'équation d'injection de l'effet. Les deux branches de-vig
partagent les fixtures latentes mais restent des fits et décisions séparés. Chaque réplication
applique BH dans la famille et dans la campagne complète, utilise
`max(family_q, global_q)`, puis ne réussit que si chaque branche satisfait le contrat
d'intervalle signé ou non signé préenregistré.

Le simulateur `ROBIN_HYPOTHESIS_POWER_SIMULATOR_V1`, sa définition canonique, chaque design et
la règle de seed SHA-256 sont hash-pinnés. Chaque protocole sérialise sa matrice complète, ses
variables latentes, les probabilités de cellules conjointes, le niveau de référence et le
vecteur de contraste. Le générateur, le fit OLS et la covariance sandwich cluster-robuste sont
des entrypoints testés ; une graine latente commune produit les mêmes fixtures dans les deux
branches, puis seules leurs transformations reçoivent des graines distinctes. Le plan utilise
un enregistrement latent par fixture mis en cache : toutes les covariables marquées `FIXTURE`,
notamment ligue-saison, restent invariantes dans le cluster. L'expansion sérialisée impose le
produit exact de ses axes : une ligne pour un estimand agrégé à la fixture, cinq bookmakers
distincts pour EXP006, HOME puis AWAY pour les protocoles team-fixture, et
HOME/FIRST, HOME/SECOND, AWAY/FIRST, AWAY/SECOND pour EXP018. Les expositions team-level
sont répétées seulement entre les deux mi-temps d'une même équipe ; `venue_home` est dérivé de
l'axe HOME/AWAY et n'est jamais tiré comme un Bernoulli libre. Les déviations H24 et la cible
H2 d'EXP006 sont propres à chaque book. L'exposition H24 est construite par statistiques
d'ordre symétriques puis normalisée à variance unitaire : sa médiane et sa somme sont
exactement nulles dans chaque fixture.
La cible H2 est recentrée à médiane nulle dans chaque fixture, puis de nouveau après le bruit
de transformation de chaque branche de-vig. Le décalage d'intercept aléatoire commun s'annule
donc exactement. Comme la somme de l'exposition
est nulle par fixture, ce recentrage est orthogonal au contraste primaire et préserve
l'alternative `rho_minus_one` injectée ; ce comportement est sérialisé et vérifié à grand n. Toute
taille candidate est arrondie au cluster complet suivant et une fixture partielle fait échouer
le générateur. La taille moyenne 4 utilisée dans le plancher analytique reste une inflation de
planification conservatrice ; le simulateur exécutable utilise le grain exact ci-dessus. Le plan utilise
10 000 réplications par taille candidate, le PRNG compteur
`SHA256_COUNTER_BOX_MULLER_V1` et une borne binomiale de Wilson à 95 %. Il porte
`PREDECLARED_MODEL_SPECIFIC_POWER_DESIGN_NOT_RUN` dans cette mission : avant tout fit sportif,
une étape design-only séparément autorisée devra retenir la première taille dont la borne
inférieure atteint 80 % pour chaque alternative déclarée. Elle pourra seulement augmenter le
plancher, jamais réduire le MDE ni inspecter un holdout.

Le protocole commun prévoit :

- holdout temporel contigu : derniers 20 % des événements éligibles par ligue-saison ;
- walk-forward à fenêtre croissante, sans refit à l'intérieur d'un bloc scoré ;
- league holdout leave-one-league-out, sans agrégation décisionnelle ;
- season holdout sur la saison receipt-backed la plus récente, scellée avant tout choix.

L'échelle Council reste une politique de contrôle. Un éventuel E1 serait limité à 10 fixtures,
une ligue-saison et cinq minutes, uniquement sous un manifeste distinct. Cette mission ne
l'autorise pas.

## 9. Score de priorité sur 100

| Critère | Maximum |
|---|---:|
| plausibilité mécanistique | 15 |
| données disponibles | 15 |
| preuve point-in-time possible | 20 |
| puissance statistique | 10 |
| originalité | 10 |
| stabilité inter-ligues | 10 |
| facilité de falsification | 10 |
| coût de calcul | 5 |
| valeur stratégique | 5 |

Le score n'utilise aucun ROI historique, aucun profit, aucun yield, aucun classement de
backtest et aucun résultat sportif. Une question bloquée peut figurer dans le portefeuille
de design pour rendre explicite un besoin stratégique ; elle ne peut pas être exécutée tant
que son contrat de source manque.

La sélection n'utilise aucun drapeau d'auteur `priority`. Le fichier
`tools/hypothesis-lab/portfolio-strata-v1.json` gèle 25 slots thématiques : quatre pour la
structure 1X2 et trois pour chacune des sept autres familles. Dans chaque strate, l'ordre est
opérationnellement complet, non bloqué, score total, preuve PIT, falsifiabilité, puissance,
coût CPU puis `estimand_hash`. La seule fallback bloquée autorisée est le protocole de
changement d'entraîneur, maintenu `NOT_RUN` pour expliciter le contrat de source manquant.

## 10. Premier portefeuille de 25 protocoles

Les identifiants et hashes complets figurent dans
`first-25-experiment-protocols-v1.json`.

| Expérience | Hypothèse gelée | Famille |
|---|---|---|
| `RDS-EXP-V1-001` | calibration relative du nul | structure 1X2 |
| `RDS-EXP-V1-002` | calibration des favoris très courts | structure 1X2 |
| `RDS-EXP-V1-003` | calibration des outsiders longs | structure 1X2 |
| `RDS-EXP-V1-004` | pente de calibration selon overround | structure 1X2 |
| `RDS-EXP-V1-005` | dispersion puis contraction vers consensus | microstructure |
| `RDS-EXP-V1-006` | réversion des écarts bookmaker | microstructure |
| `RDS-EXP-V1-007` | proxy de faible liquidité et dispersion | microstructure |
| `RDS-EXP-V1-008` | apport du mouvement H24 vers H2 | dynamiques |
| `RDS-EXP-V1-009` | régime de forte volatilité | dynamiques |
| `RDS-EXP-V1-010` | désynchronisation 1X2-total | dynamiques |
| `RDS-EXP-V1-011` | forme récente ajustée des adversaires | forme-régression |
| `RDS-EXP-V1-012` | surperformance buts-xG et régression | forme-régression |
| `RDS-EXP-V1-013` | clean sheets sans amélioration xGA | forme-régression |
| `RDS-EXP-V1-014` | forme propre au lieu | lieu-cohorte |
| `RDS-EXP-V1-015` | calibration des promus en début de saison | lieu-cohorte |
| `RDS-EXP-V1-016` | derby, nul et faible total | lieu-cohorte |
| `RDS-EXP-V1-017` | différentiel de repos | calendrier-fatigue |
| `RDS-EXP-V1-018` | congestion et seconde période | calendrier-fatigue |
| `RDS-EXP-V1-019` | championnat avant/après Europe | calendrier-fatigue |
| `RDS-EXP-V1-020` | changement d'entraîneur et variance | état-classement |
| `RDS-EXP-V1-021` | surclassement points face à xG/force | état-classement |
| `RDS-EXP-V1-022` | non-linéarité des écarts extrêmes de niveau | état-classement |
| `RDS-EXP-V1-023` | incohérence 1X2-over/under | cross-market |
| `RDS-EXP-V1-024` | favori court avec faible total | cross-market |
| `RDS-EXP-V1-025` | outsider long avec total élevé | cross-market |

Chaque objet contient le dataset requis, le contrat de snapshot attendu, les branches de-vig,
les seuils football/marché et leurs frontières d'égalité, l'estimand, l'estimateur complet et
le contraste primaire scalaire, la taille minimale et son plan de puissance spécifique au
modèle, les holdouts, le walk-forward, les critères GO/NO-GO,
le coût CPU, le temps humain, le risque principal et les contrôles négatifs associés. Les
définitions comprennent notamment les bandes `<= 1,50`/`>= 6,00`, fenêtres H24/H2, lookbacks
de forme, repos/congestion, horizons Europe, bins de saison et tolérances de synchronisation.

Le `expected_snapshot_id` porte `NOT_YET_MATERIALIZED`. Le dépôt n'a pas de format générique
unique : datasets historiques, features et marchés ont des identités natives différentes.
Le protocole exige donc `snapshot_kind`, `snapshot_schema_version`, identité native si elle
existe et SHA-256 canonique avant exécution. Il interdit un faux hash de remplissage.

Un GO signifie seulement « soumettre l'étape de recherche immédiatement suivante à une
autorisation séparée ». Un NO-GO signifie falsifier, arrêter ou redessiner le protocole. Aucun
des deux n'autorise une action externe.

## 11. Contrôles négatifs

Le plan définit neuf contrôles :

1. labels permutés dans des blocs ligue-saison ;
2. feature future sentinelle, qui doit être rejetée avant fit ;
3. prix décalé vers une fixture sans identité commune ;
4. parité d'un hash d'identité sans mécanisme plausible ;
5. condition synthétique impossible ;
6. variable constante triviale ;
7. champ post-résultat sentinelle ;
8. identité gagnant-perdant indisponible au cutoff ;
9. marché synthétique calibré, avec overround et bruit bookmaker déclarés mais sans signal
   résiduel injecté.

Toute violation d'un contrôle `DETERMINISTIC_GUARD` arrête l'usine dès la première occurrence,
notamment l'admission impossible (005) ou le fit d'une constante (006). Pour les contrôles
`STOCHASTIC_REPLICATE` 001, 004 et 009, les 20 seeds/salts sont persistés explicitement et
l'alarme exige au moins 4 réplications sur 20 franchissant à la fois `q <= 0,05` et le même
plancher d'effet. Les contrôles 005, 006 et 008 sont des gardes factory-wide ; tous les autres
sont explicitement affectés aux protocoles.

## 12. Falsification, abandon et contrôles d'intégrité

Chaque claim porte un contrat structuré, jamais déduit de son libellé : type
`SIGNED_MINIMUM` ou `ABSOLUTE_MINIMUM`, orientation, estimand, échelle, MDE `δ`, méthode
d'intervalle et inégalités. Pour un effet positif signé, support exige `L >= δ` et falsification
`U < δ`; pour un effet négatif, support exige `U <= -δ` et falsification `L > -δ`. Pour un
effet absolu, falsification exige `L > -δ` et `U < δ`. L'égalité de la borne de support est
incluse si la q-value passe ; l'égalité de la borne de falsification reste inconclusive.
Chaque branche de-vig est classée séparément. Échantillon insuffisant, preuve PIT invalide,
contrôle négatif en alarme ou exécution de-vig invalide produit `BLOCKED_OR_INVALID`, jamais
une confirmation ou une falsification scientifique.

Le registre V1 type exhaustivement 71 claims directionnels et 41 claims bilatéraux. Un code de
direction bilatéral appartient à une allowlist gelée ; tout autre code doit être
`SIGNED_MINIMUM`. Pour chaque claim signé, un intervalle entièrement situé dans la direction
opposée est testé comme `FALSIFIED` et ne peut jamais devenir `SUPPORTED`.

Le protocole est abandonné si :

- la couverture de reçus est inférieure à 80 % ;
- une mutation future change un hash passé ;
- deux redesigns indépendants échouent pour la même cause ;
- une source indispensable n'est pas prospectivement observable ;
- un contrôle négatif déclenche son alarme.

## 13. Reproductibilité et validation

Depuis le worktree dédié, avec un interpréteur Python 3.12 portant les dépendances de
développement du projet :

```powershell
$pythonExe = 'python'

& $pythonExe tools/hypothesis-lab/build_catalogue.py --check
& $pythonExe -m pytest -q tests/hypothesis-lab
& $pythonExe -m ruff check tools/hypothesis-lab tests/hypothesis-lab
& $pythonExe -m mypy --strict tools/hypothesis-lab/build_catalogue.py
& $pythonExe -m bandit -q -r tools/hypothesis-lab
& $pythonExe scripts/check_no_secrets.py
& $pythonExe scripts/check_no_tracked_absolute_paths.py --repo-root .
git diff --check
git diff --cached --check
```

Le générateur :

- valide le schéma Draft 2020-12 avant les documents ;
- recalcule les hashes de contenu et de protocole ;
- exige exactement six rapports, 336 candidats issus de 112 questions semées, 80 à 150
  hypothèses distinctes (112 observées ici), 8 familles, 25 protocoles et 9 contrôles ;
- vérifie le partitionnement bijectif des clusters, chaque score, l'ordre des strates, les
  références inter-rapports, les triples de-vig, les rôles PIT/labels et les inégalités de
  falsification ;
- rejette des mutations pourtant rehashées : score négatif, ID inconnu, cluster cassé,
  drift de quota/ordre, triple de-vig incohérent et substitution de `event_at` ;
- interdit les statuts scientifiques bannis ;
- rejette les chemins absolus et tout compteur d'effet externe non nul ;
- compare les octets générés aux fichiers suivis avec `--check`.

Les hashes textuels utilisent la représentation Git canonique LF ; `--check` normalise
uniquement la traduction CRLF éventuelle du checkout Windows avant la comparaison.

## 14. Artefacts

- `reports/hypothesis-lab/hypothesis-universe-v1.json`
- `reports/hypothesis-lab/hypothesis-family-map-v1.json`
- `reports/hypothesis-lab/hypothesis-deduplication-v1.json`
- `reports/hypothesis-lab/hypothesis-priority-scorecard-v1.json`
- `reports/hypothesis-lab/first-25-experiment-protocols-v1.json`
- `reports/hypothesis-lab/negative-control-plan-v1.json`
- `tools/hypothesis-lab/build_catalogue.py`
- `tools/hypothesis-lab/catalogue-source-v1.json`
- `tools/hypothesis-lab/raw-candidates-v1.json`
- `tools/hypothesis-lab/portfolio-strata-v1.json`
- `tools/hypothesis-lab/hypothesis-lab-artifact-schema-v1.json`
- `tests/hypothesis-lab/`

Ces artefacts préparent une recherche future. Ils ne constituent ni une preuve de causalité,
ni une preuve historique point-in-time, ni une autorisation d'exécution.
