# Revue contradictoire PR #127 — `codex/observatoire-sources-v1`

- **Relecteur** : GEMINI (relecture contradictoire indépendante du producteur Codex)
- **Dépôt inspecté (lecture seule)** : worktree `observatoire` (chemin relatif au projet)
- **Référentiel** : `reports/source_observatory/REGLES-DOSSIER-CONCEPTION.md` (§04, §05, §17, §19)
- **Verdict final** : **REFUSE** (4 constats **BLOQUANTS**, 5 **MAJEURS**, 1 **MINEUR**)

---

## 1. Synthèse par axe de contrôle demandé

| Axe de contrôle | Statut | Synthèse |
| :--- | :--- | :--- |
| **1. Cote reconstruite / imputée** | Partiellement tenu | `cote_declaree` et `cote_observee` restent séparées (`Decimal \| None`), mais `categorie='selection_avec_cote'` accepte deux cotes `None` (`models.py:285-295`), et les catégories sans cote (`probabilite_explicite`, `information_factuelle`) restent couplées à un `odds_basis` arbitraire dans `rankings()` (`ranking.py:133`). |
| **2. Horodatage imputé** | **FAILLE (MAJEUR / BLOQUANT)** | Aucune heure courante n'est appelée, mais `PublicationVersion.__post_init__` (`models.py:111-126`) accepte `previous_version_id` avec `modification_observed_at=None`, `store.py:194` autorise une correction sans avancement temporel (`usable_at == last.usable_at`), et `store.py:199-209` n'impose aucune cohérence entre `cote_observee_at` / `cote_declaree_at` et `first_observed_by_robin_at`. |
| **3. Texte post-match accepté comme pré-match** | **FAILLE (BLOQUANT)** | `Contribution` n'ayant pas d'horodatage d'observation propre, `store.py:199-209` permet d'ajouter dans le journal — *après* le `Result` du match — une nouvelle `Contribution` (`selection-2`) rattachée à une `PublicationVersion` pré-match existante (`v1`), qui est alors validée comme pré-match par `evaluate()` et `rankings()`. |
| **4. Mutation / contournement du stockage append-only** | **FAILLE (BLOQUANT)** | Le fichier JSONL n'est pas réécrit sur disque, mais l'invariant d'auditabilité des résultats (`store.py:222-230`) se contourne en ajoutant un second `MatchMarket` (`mm2`) pour la même `Contribution` (`store.py:210-217`), ce qui permet de remplacer un `Result` perdant par un `Result` gagnant sans `previous_result_id` ni `audit_evidence_sha256`. De même, `Cohort` (`store.py:256-261`) peut être enregistrée après tous les `Result`. |
| **5. Fusion d'identités par pseudo similaire** | **FAILLE (BLOQUANT)** | Contrairement à `RepriseLink` (`certainty: Literal['attestee', 'similarite']`), `IdentityRevision` (`models.py:441-458`) n'a aucun champ de certitude et `rankings()` (`ranking.py:122-125`) fusionne inconditionnellement deux comptes même avec `reason='pseudo similaire'`. |
| **6. Retrait qui améliore un score** | **FAILLE (BLOQUANT)** | Un auteur qui retire une sélection perdante en publiant une version corrigée pré-match `v2` omettant ce `selection_key` voit sa sélection `v1` éliminée par `pre_match_contributions` (`ranking.py:27-41, 141-143`) : la perte disparaît du ROI (même si un `Withdrawal` est enregistré !) et, sans `Withdrawal`, `Comparable suspendu` n'est même pas déclenché. |
| **7. Règlement sans règle documentée non mis en attente** | **FAILLE (MAJEUR)** | `settle()` (`settlement.py:55-63`) règle un marché `1N2`/`1X2`/`qualification` en ignorant une `ligne` non nulle au lieu de le mettre en `en_attente`, accepte un `total` à ligne négative, et `evaluate()` (`service.py:123-132`) évalue des combinés à 1 seule jambe ou dont les jambes ne correspondent à aucune `Contribution` du journal ni à `Result.outcome`. |
| **8. Payload brut stocké** | **FAILLE (MAJEUR)** | Si `preuve_permise` est fourni, `Contribution.extraits_preuve` (`models.py:130-148, 301-310`) et `contribution.schema.json:89-122` autorisent un nombre illimité de tranches contiguës de 500 caractères, permettant de stocker l'intégralité d'un payload brut arbitrairement long. |
| **9. ROI mal calculé (gagné c-1, perdu -1, remboursé 0)** | **FAILLE (MAJEUR)** | La formule unitaire par pari (`c-1`, `-1`, `0`) est exacte, mais `rankings()` (`ranking.py:157-161`) additionne toutes les reprises attestées d'un même pronostic dans `net`, `stakes` et `roi` au lieu de les dédupliquer par groupe d'origine, ce qui permet de multiplier artificiellement le ROI en republiant un pari gagnant. |
| **10. Tests qui ne testent rien** | **FAILLE (MINEUR)** | Assertion tautologique dans `test_conception.py:130` (`copies[0].source_id == origin.source_id` sur deux fixtures initialisées avec la même constante `'s1'`), test de cohorte sur constantes passées en dur (`test_conception.py:313-328`), et absence totale de test sur le refus de fusion d'identités par pseudo similaire. |

---

## 2. Constats détaillés

### Constat 1 — [BLOQUANT] Retrait d'une sélection qui améliore le ROI (et contournement de `Comparable suspendu`)
- **Fichier:ligne** : `src/robin/source_observatory/ranking.py:27-41` et `src/robin/source_observatory/ranking.py:126-148`
- **Scénario d'échec concret** :
  1. Un auteur publie à `18h00` la version `v1` de `p1` contenant deux sélections sur un match à `20h00` : `c1` (`selection_key='selection-1'`, perdante, `unit_profit = Decimal('-1')`) et `c2` (`selection_key='selection-2'`, gagnante à cote `2.40`, `unit_profit = Decimal('1.4')`). Son vrai bilan est `net = +0.4`, `ROI = +0.20`.
  2. À `19h50` (avant le coup d'envoi de `20h00`), l'auteur modifie sa publication (`v2`, `previous_version_id='v1'`, `usable_at=19h50`) en supprimant `selection-1` et en ne gardant que `selection-2` (`c2_v2`).
  3. Dans `ranking.py:27-41`, `pre_match_contributions` ne retient que `v2` (la docstring ligne 29-30 l'indique explicitement : *"Selecting a whole version also removes selections omitted by a correction"*).
  4. Dans `ranking.py:141-143`, `if c not in eligible: continue` **élimine `c1`**. Même si un événement `Withdrawal('w1', 'c1', ...)` a été dûment enregistré dans le journal, `c1` reste exclu par `if c not in eligible: continue` : la perte de `-1` disparaît et le ROI de l'auteur bondit de `+0.20` à `+1.40`. Si aucun `Withdrawal` n'a été créé lors de l'omission dans `v2`, `coverage_changed` reste en prime à `False` et `status` ne passe même pas à `'Comparable suspendu'`.
  5. Second vecteur dans `ranking.py:126-136, 149` : si `c1` est retirée avant que son `Evaluation` ne soit ajoutée au journal (ou si un `Result` corrigé `r2` est ajouté sans nouvelle `Evaluation`, ligne 136 `entity.result_id != latest_results.get(entity.match_market_id)`), la perte est ignorée du calcul ; et si un auteur retire sa seule contribution avant évaluation, `by_author` est vide et l'auteur disparaît totalement de `rankings()`.
- **Correctif minimal** :
  - Dans `pre_match_contributions()` (`ranking.py:24-41`), résoudre la dernière contribution pré-match **par `(publication_id, selection_key)`** : si une version ultérieure `v2` omet un `selection_key` présent dans `v1`, conserver la contribution de `v1` dans l'évaluation ET marquer l'auteur en `coverage_changed = True` (`'Comparable suspendu'`).
  - Dans `rankings()` (`ranking.py:135-176`), ne jamais exclure du calcul une contribution visée par `Withdrawal`, lever une erreur si le dernier `Result` d'un `MatchMarket` n'a pas d'`Evaluation` correspondante, et initialiser `output` pour tous les auteurs de `affected_authors`.

---

### Constat 2 — [BLOQUANT] Fusion d'identités par pseudo similaire acceptée (`pseudo similaire != fusion`)
- **Fichier:ligne** : `src/robin/source_observatory/models.py:441-458`, `src/robin/source_observatory/store.py:239-248`, `src/robin/source_observatory/ranking.py:122-125`
- **Scénario d'échec concret** :
  1. Deux comptes aux pseudos proches (`author_id='pronostics_du_roi'` et `author_id='pronostics-du-roi'`) ont des bilans distincts.
  2. Un opérateur ou agent crée `IdentityRevision(revision_id='rev-1', previous_revision_id=None, assignments=(AccountAssignment('pronostics_du_roi', 'roi'), AccountAssignment('pronostics-du-roi', 'roi')), observed_at=T, evidence_sha256=H, reason='pseudo similaire')`.
  3. `IdentityRevision.__post_init__` (`models.py:449-458`) et `_validate_lineage` (`store.py:239-248`) l'acceptent sans vérifier la nature de la preuve, et `rankings()` (`ranking.py:122-125`) fusionne les deux comptes sous `'roi'`, violant la règle décisive §04 : *« Identites ambigues = separees (pseudo similaire != fusion) »*.
- **Correctif minimal** :
  - Ajouter sur `IdentityRevision` (ou `AccountAssignment`) un champ explicite `certainty: Literal['attestee', 'similarite']` (comme sur `RepriseLink` dans `models.py:153`).
  - Dans `rankings()` (`ranking.py:122-125`), ignorer toute affectation multi-comptes dont `certainty != 'attestee'` (ou refuser `certainty == 'similarite'` lors d'un rattachement vers un `identity_id` partagé dans `IdentityRevision.__post_init__`).

---

### Constat 3 — [BLOQUANT] Injection post-match d'une sélection rattachée à une version pré-match et absence de monotonie temporelle
- **Fichier:ligne** : `src/robin/source_observatory/store.py:184-210` et `src/robin/source_observatory/models.py:107-127`
- **Scénario d'échec concret** :
  1. Avant un match dont le coup d'envoi est à `20h00`, le journal enregistre `Source` (`s1`), `Publication` (`p1`), `PublicationVersion` (`v1`, `usable_at=18h00`), `Contribution` (`c1`, `version_id='v1'`, `selection_key='selection-1'`), `MatchMarket` (`mm1`, `match_usable_at=20h00`).
  2. À `22h00`, le match est terminé et `Result` (`r1`, `observed_at=22h00`) est enregistré à la ligne 6 du journal.
  3. À la ligne 7 du journal (donc *après* le match et après `r1`), on ajoute une nouvelle `Contribution` `c2` avec `version_id='v1'`, `selection_key='selection-2'`, portant sur le résultat gagnant désormais connu, puis `mm2` (`contribution_usable_at=v1.usable_at=18h00`, `match_usable_at=20h00`).
  4. Comme `Contribution` ne possède pas d'horodatage d'extraction/observation et que `_validate_lineage` (`store.py:199-209`) vérifie uniquement l'unicité de `(version_id, selection_key)`, `store.append(c2)` réussit. `mm2.pre_match_valid` vaut `True` (`18h00 < 20h00`), et ce pronostic créé après le match est comptabilisé comme pré-match dans `evaluate()` et `rankings()`.
  5. De même, `store.py:184-198` permet d'ajouter après un `Result` (`observed_at=22h00`) une toute nouvelle `PublicationVersion` déclarant `first_observed_by_robin_at=18h00, usable_at=18h00`. Enfin, `store.py:194` utilise `<` au lieu de `<=` (`entity.usable_at < last.usable_at`), autorisant une version corrigée `v2` sans avancement de `usable_at`, et `PublicationVersion.__post_init__` (`models.py:111-126`) accepte `previous_version_id='v1'` avec `modification_observed_at=None`.
- **Correctif minimal** :
  - Dans `PublicationVersion.__post_init__` (`models.py:111-126`), exiger `self.modification_observed_at is not None` dès que `self.previous_version_id is not None`.
  - Dans `store.py:194`, remplacer `entity.usable_at < last.usable_at` par `entity.usable_at <= last.usable_at` (ou imposer la monotonie stricte de `modification_observed_at`).
  - Dans `store.py:_validate_lineage`, interdire l'ajout d'une `Contribution` sur une `PublicationVersion` dès qu'un `MatchMarket`, `Result` ou une `PublicationVersion` suivante a déjà été enregistré, et vérifier que les horodatages d'observation (`first_observed_by_robin_at`, `modification_observed_at`, `observed_at`) ne reculent pas par rapport aux événements déjà présents dans le journal.

---

### Constat 4 — [BLOQUANT] Contournement de l'auditabilité append-only des `Result` (via duplication de `MatchMarket`) et antidatage des `Cohort`
- **Fichier:ligne** : `src/robin/source_observatory/store.py:210-232` et `src/robin/source_observatory/store.py:256-261`
- **Scénario d'échec concret** :
  1. **Réécriture d'un résultat réglé sans preuve d'audit** : Pour une contribution `c1`, le journal contient `MatchMarket` `mm1` et `Result` `r1` (`outcome='perdu'`). Normalement, `store.py:225-230` bloque tout nouveau `Result` sur `mm1` sans `previous_result_id='r1'` et `audit_evidence_sha256`. Or `_validate_lineage` (`store.py:210-217`) n'interdit pas d'enregistrer un second `MatchMarket` `mm2` (`match_market_id='mm2'`) pointant vers le même `contribution_id='c1'`. On peut alors ajouter `Result('r2', 'mm2', outcome='gagne', previous_result_id=None, audit_evidence_sha256=None)` puis son `Evaluation` : le garde-fou d'audit est intégralement contourné.
  2. **Cohorte définie après les résultats** : Dans `store.py:256-261`, l'enregistrement d'une `Cohort` vérifie uniquement `if isinstance(existing, Evaluation)` et `if c.author_id in entity.author_ids`. Si tous les `Result` des matchs sont déjà enregistrés dans le journal (avant l'ajout des objets `Evaluation`), ou si les auteurs ont été regroupés sous un nouvel `identity_id` via `IdentityRevision`, on peut ajouter une `Cohort` choisissant a posteriori les auteurs gagnants avec un `defined_at` dans le passé.
- **Correctif minimal** :
  - Dans `store.py:210-217`, interdire l'ajout d'un `MatchMarket` si un `MatchMarket` existe déjà dans `known` pour le même `entity.contribution_id`.
  - Dans `store.py:256-261`, refuser l'ajout d'une `Cohort` si le journal contient déjà des observations (`PublicationVersion`, `Contribution`, `Result`, `Evaluation`) postérieures à `entity.defined_at` ou concernant les membres de la cohorte (après résolution des `IdentityRevision`).

---

### Constat 5 — [MAJEUR] ROI et métriques faussés par les reprises d'une même origine, cassure des reprises inter-auteurs et bogue d'`origin_groups`
- **Fichier:ligne** : `src/robin/source_observatory/ranking.py:82-96` et `src/robin/source_observatory/ranking.py:150-175`
- **Scénario d'échec concret** :
  1. **Gonflement du ROI par auto-reprises ou comptes fusionnés** : Si un auteur (ou deux comptes fusionnés) publie 1 sélection perdante (`-1`) et 10 reprises attestées (`certainty='attestee'`) d'une même sélection gagnante (`+1.4`) sur le même match, `rankings()` (`ranking.py:157-161`) calcule `net = sum(profits)` et `roi = net / len(profits)` sur les 11 évaluations (`net = +13.0`, `roi = +1.18`) au lieu de dédupliquer les reprises attestées d'un même groupe d'origine (`net = +0.4`, `roi = +0.20`).
  2. **Cassure de chaîne de reprise** : `ranking.py:150-151` appelle `reprise_groups(cs)` uniquement sur les contributions évaluées de l'auteur courant. Si deux publications d'un auteur reprennent une même source via une publication intermédiaire d'un autre auteur (ou via une publication non évaluée), le lien transitif est perdu et `independent_groups` est surestimé.
  3. **Origines résolues marquées `non_resolu` et cycles masqués dans `origin_groups`** : Dans `ranking.py:91-95`, `targets = {target for pub in pubs for target in outgoing[pub]}`. Toute publication originale autonome (sans `liens_reprise` entrant ni sortant, y compris une publication originale de Robin) a `targets = set()`, donc `origin_publication_id = None` et `statut = 'non_resolu'`. Inversement, un groupe contenant à la fois un cycle `p1 <-> p2` et une flèche `p2 -> p0` obtient `roots = {'p0'}` (`len(roots) == 1`) et est déclaré `'resolu'`, masquant le cycle.
- **Correctif minimal** :
  - Calculer `reprise_groups` sur **toutes** les contributions du journal avant d'agréger par auteur, et dédupliquer les évaluations partageant le même `(origin_group, match_id, market_id, selection_id)` avant de sommer `profits`, `brier`, `log_loss` et `factual_accuracy`.
  - Dans `origin_groups()` (`ranking.py:82-96`), détecter tout cycle dans la composante connexe (si cycle présent → `statut = 'non_resolu'`), et définir les racines sur `pubs` (`roots = {p for p in pubs if not outgoing[p]}`) en distinguant explicitement une publication d'origine attestée d'une origine inconnue.

---

### Constat 6 — [MAJEUR] Règlements (`settle` / `settle_combined` / `evaluate`) : combinés sans preuves sur les jambes, contradiction `Result.outcome` vs `legs` et lignes ignorées
- **Fichier:ligne** : `src/robin/source_observatory/settlement.py:41-110`, `src/robin/source_observatory/service.py:123-138`, `src/robin/source_observatory/store.py:218-232`
- **Scénario d'échec concret** :
  1. **Jambes de combiné non vérifiées et combiné à 1 jambe** : Dans `settlement.py:78-110`, `service.py:123-132` et `store.py:218-232`, les `SettlementLeg` d'un combiné ont un `contribution_id` qui n'est jamais relié ni vérifié dans `known` (aucun contrôle d'existence, de validité pré-match ni de preuve du résultat de chaque jambe). Un combiné avec une seule jambe (`len(legs) == 1`) est également accepté et évalué.
  2. **Contradiction entre `result.outcome` et `result.legs`** : Dans `service.py:123-132`, `evaluate()` calcule `profit = combined_return(result.legs) - 1` sans vérifier la cohérence avec `result.outcome` (tant que `result.outcome != 'en_attente'`). Un `Result` portant `outcome='perdu'` avec deux jambes marquées `'gagne'` donne un `unit_profit` positif.
  3. **Ligne présente sur `1N2`/`1X2`/`qualification` ou `total` négatif non mis en `en_attente`** : Dans `settlement.py:55-70`, si `marche='1N2'` mais `ligne=Decimal('-1.5')` (handicap extrait par erreur comme `1N2`), `settle()` ignore `ligne` et règle le pari en `1N2` sec au lieu de retourner `'en_attente'`. Si `marche='total'` et `ligne=Decimal('-2.5')`, `settle()` règle le pari en `'gagne'` au lieu de `'en_attente'`.
- **Correctif minimal** :
  - Dans `settlement.py:55-74`, retourner `'en_attente'` si `line is not None` sur `1N2`/`1X2`/`qualification` ou si `line < 0` sur `total`.
  - Dans `settlement.py:78` et `service.py:123-132`, exiger `len(legs) >= 2` et vérifier que l'`outcome` déduit de `factor` correspond exactement à `result.outcome` (sinon `reason = 'en_attente'`).
  - Dans `store.py:218-232`, vérifier que chaque `leg.contribution_id` référence une `Contribution` pré-match résolue dans `known`.

---

### Constat 7 — [MAJEUR] États d'évaluation (`classification_state`) et couverture de visites (`visit_coverage`) déconnectés des preuves du journal
- **Fichier:ligne** : `src/robin/source_observatory/ranking.py:170`, `src/robin/source_observatory/ranking.py:179-183`, `src/robin/source_observatory/ranking.py:218-235`
- **Scénario d'échec concret** :
  1. `rankings()` (`ranking.py:170`) renvoie systématiquement `'Comparable suspendu' if changed else 'En observation'` et ignore les objets `Cohort` et `Visit` présents dans `entities`.
  2. `classification_state()` (`ranking.py:218-235`) prend en paramètres des compteurs libres (`independent_matches: int`, `prospective_matches: int`, `coverage: Decimal | None`, `prospective_coverage: Decimal | None`) sans qu'aucune fonction du module ne filtre les `Evaluation` ni les `Visit` selon les fenêtres `[evaluation_starts_at, evaluation_ends_at)` et `[prospective_starts_at, prospective_ends_at)` de la `Cohort`.
  3. `visit_coverage()` (`ranking.py:179-183`) calcule le ratio global sur un itérable de `Visit` sans séparer par `source_id` ni par fenêtre temporelle.
- **Correctif minimal** :
  - Ajouter le calcul de `independent_matches`, `coverage`, `prospective_matches` et `prospective_coverage` directement depuis `(entities, cohort, author_id, at)` en filtrant strictement les matchs et visites par `source_id`/`author_id` et par les fenêtres temporelles de la `Cohort`, puis l'intégrer à `rankings()`.

---

### Constat 8 — [MAJEUR] Contournement de la limite d'extrait de 500 caractères par découpage en tranches dans `extraits_preuve`
- **Fichier:ligne** : `src/robin/source_observatory/models.py:130-148`, `src/robin/source_observatory/models.py:301-310`, `src/robin/source_observatory/schemas/contribution.schema.json:89-122`
- **Scénario d'échec concret** :
  1. Avec `preuve_permise='https://example.invalid/perm'`, on construit une `Contribution` dont `extraits_preuve` contient 40 objets `EvidenceExcerpt` contigus de 500 caractères (`(0, 500)`, `(500, 1000)`, ..., `(19500, 20000)`).
  2. Chaque `EvidenceExcerpt` respecte individuellement `len(self.text) <= 500` (`models.py:146`), ce qui permet de persister un article brut complet de 20 000 caractères dans le journal JSONL.
  3. De plus, `contribution.schema.json:112-119` n'impose pas `"pattern": "\\S"` sur `extraits_preuve.items.properties.text` (contrairement à `models.py:145`) ni `maxItems` sur `extraits_preuve`.
- **Correctif minimal** :
  - Dans `Contribution.__post_init__` (`models.py:301-310`), borner la longueur cumulée des textes d'extraits par contribution (`sum(len(e.text) for e in self.extraits_preuve if e.text is not None) <= 500`) et interdire le chevauchement ou la concaténation intégrale du texte source.
  - Synchroniser `contribution.schema.json` avec `"pattern": "\\S"` et `"maxItems"`.

---

### Constat 9 — [MAJEUR] Incohérence entre `resolve_match_market` et `Contribution.match_id`, et éviction des catégories sans cote dans `rankings()`
- **Fichier:ligne** : `src/robin/source_observatory/service.py:16-51`, `src/robin/source_observatory/store.py:215-217`, `src/robin/source_observatory/ranking.py:133-135`
- **Scénario d'échec concret** :
  1. Si `contribution` a `match_id=None, certitude_rapprochement='non_resolue'`, `resolve_match_market()` (`service.py:16-51`) résout néanmoins `fixture` en `match_id='fixture'` avec `statut='resolu'`, et `store.py:215-217` l'accepte car il ne teste la cohérence que si `contribution.match_id is not None`.
  2. Une contribution de catégorie `probabilite_explicite` ou `information_factuelle` (sans cote) doit être évaluée en passant un `odds_basis` arbitraire à `evaluate()`. Si elle a été évaluée avec `odds_basis='cote_declaree'`, l'appel `rankings(entities, odds_basis='cote_observee')` (`ranking.py:133`) filtre cette évaluation et renvoie `brier=None, log_loss=None, factual_accuracy=None`.
- **Correctif minimal** :
  - Dans `resolve_match_market()` (`service.py:37-51`) et `store.py:215-217`, exiger que `contribution.match_id == match_id` lorsque `MatchMarket.statut == 'resolu'`.
  - Dans `rankings()` (`ranking.py:133`), n'appliquer le filtre `entity.odds_basis != odds_basis` qu'aux évaluations de catégorie `'selection_avec_cote'`.

---

### Constat 10 — [MINEUR] Tests tautologiques ou incomplets et caractères UTF-8 corrompus dans le schéma
- **Fichier:ligne** : `tests/source_observatory/test_conception.py:84-94, 130, 313-328` et `src/robin/source_observatory/schemas/contribution.schema.json:4`
- **Scénario d'échec concret** :
  1. Dans `test_conception.py:130`, `assert copies[0].source_id == origin.source_id  # provenance is never rewritten` compare deux instances créées par le helper `contribution()` qui fixe `source_id='s1'` par défaut, sans qu'aucune fonction n'ait inspecté ou transformé `source_id`. C'est un test purement tautologique.
  2. Dans `test_conception.py:313-328`, `test_cohort_is_fixed_before_evaluation_and_signal_requires_future_holdout` teste uniquement les `if` de `classification_state` avec des entiers passés en dur, sans aucune donnée du journal.
  3. Dans `test_conception.py:84-94`, la fixture de publication découverte à `T + 4h` utilise une `Contribution` dont `cote_declaree_at = T` (4 heures avant la première observation par Robin).
  4. Dans `src/robin/source_observatory/schemas/contribution.schema.json:4` (ainsi que `reports/source_observatory/PLAN-CONFORMITE.md:31-34`), les caractères accentués et symboles ont été remplacés par des `?` (`"Dossier fid?le ? contribution ?04/05 version 2"`).
- **Correctif minimal** :
  - Remplacer l'assertion tautologique de `test_conception.py:130` par un test vérifiant que l'origine d'une publication Robin reste résolue sur Robin, tester le calcul de cohorte depuis les entités du journal, ajouter un test de non-fusion par pseudo similaire, et corriger l'encodage UTF-8 de `contribution.schema.json:4`.

---

## 3. Conclusion

**Verdict : `REFUSE`**

La base de modélisation (dataclasses figées, `Decimal` explicites, hachage canonique JSONL, séparation `cote_declaree` / `cote_observee`) est propre, mais **quatre failles bloquantes** permettent aujourd'hui :
1. d'améliorer un ROI en retirant une sélection perdante via une nouvelle version pré-match (`ranking.py:27-41, 141-143`) ;
2. de fusionner des comptes sur simple pseudo similaire (`models.py:441-458`, `ranking.py:122-125`) ;
3. d'injecter après le match une sélection gagnante sur une `PublicationVersion` pré-match existante (`store.py:199-209`) ;
4. de contourner l'auditabilité append-only d'un `Result` via un second `MatchMarket` et d'enregistrer une `Cohort` après les `Result` (`store.py:210-232, 256-261`).
