# Revue contradictoire Ronde 2 — `codex/observatoire-sources-v2` (après fusion PR #127)

- **Relecteur** : GEMINI (relecture contradictoire indépendante, Ronde 2)
- **Branche inspectée (lecture seule)** : `codex/observatoire-sources-v2` (`a58fc2adad1fcf886ed1d56e721d417adab68a83`, incluant le correctif `c7dac32e3d174780bf7354a17499d28111173cdb`)
- **Périmètre** : `src/robin/source_observatory/` (hors `extractor*.py`, `evaluate*.py` et `schema_validation.py` non commités) et `tests/source_observatory/` (hors `test_extractor.py` non commité)
- **Référentiels** : `reports/source_observatory/REGLES-DOSSIER-CONCEPTION.md` (§04, §05, §17, §19) et `reports/source_observatory/reponse-revue-gemini.md`
- **Verdict final** : **`REFUSE`** (5 constats **BLOQUANTS**, 3 **MAJEURS**, 1 **MINEUR**)

---

## 1. Arbitrage contradictoire des points de Ronde 1 contestés par Codex

Dans `reports/source_observatory/reponse-revue-gemini.md` (lignes 22-28), Codex a contesté trois nuances issues de la Ronde 1. Voici la décision motivée pour chacune :

### Point contesté 1 — Statut d'une publication sans `liens_reprise` dans `origin_groups()` (issu du Constat 5.3 de Ronde 1)
- **Argument de Codex** : *« l'absence de lien de reprise ne prouve pas qu'une publication est originale ; elle reste inconnue (test des origines inconnues conservé). »*
- **Décision GEMINI** : **ACCEPTÉ sur le statut d'une publication isolée sans lien entrant**, mais **MAINTENU sur le bogue de sélection de racine dans `reprise_groups()` (`src/robin/source_observatory/ranking.py:50-53, 70`)**.
- **Justification et scénario d'échec concret** :
  - Nous acceptons qu'en l'absence de champ booléen d'originalité sur une publication isolée sans `RepriseLink` entrant, `origin_groups()` laisse `statut='non_resolu'` (conformément au §19 : *« 2 origines inconnues = 2 origines non resolues »*), tandis que la provenance `source_id='robin'` est conservée sur `Contribution`.
  - En revanche, nous **maintenons** le constat sur `reprise_groups()` (`src/robin/source_observatory/ranking.py:50-53, 70`) qui confond « cible d'un lien de reprise » et « racine d'origine » :
    - **Scénario d'échec concret** : Soit une publication d'origine `p_orig` (`publication_id='pub-origin'`), reprise par un relais intermédiaire `p_relais` (`publication_id='aaa-relais'`, `liens_reprise=(RepriseLink('pub-origin', 'attestee', H),)`), lui-même repris par `p_copie` (`publication_id='zzz-copie'`, `liens_reprise=(RepriseLink('aaa-relais', 'attestee', H),)`). Dans `ranking.py:53`, `roots.add(link.publication_id)` ajoute `'aaa-relais'` et `'pub-origin'` dans `roots`. À la ligne 70, `min(set(pubs) & roots)` choisit `'aaa-relais'` (car `'aaa-relais' < 'pub-origin'`) au lieu de la racine `'pub-origin'`. On obtient `reprise_groups() == {'aaa-relais': ('aaa-relais', 'pub-origin', 'zzz-copie')}` et `OriginGroup(group_id='aaa-relais', ..., origin_publication_id='pub-origin', statut='resolu')` : le groupe est identifié par le relais intermédiaire et non par son origine attestée (voir **Constat 7**).

### Point contesté 2 — `cote_declaree_at` antérieur à `first_observed_by_robin_at` (issu de l'Axe 2 et du Constat 10.3 de Ronde 1)
- **Argument de Codex** : *« Une cote déclarée par l'auteur peut précéder sa découverte par Robin : elle n'antidate ni la version ni la contribution. La fixture rétrospective conserve cette distinction, avec une observation de contribution désormais explicite. »*
- **Décision GEMINI** : **ACCEPTÉ pour `cote_declaree_at < first_observed_by_robin_at`**, mais **MAINTENU pour `cote_observee_at < first_observed_by_robin_at` et pour `cote_declaree_at > Contribution.observed_at` / `cote_observee_at > Contribution.observed_at`** (`src/robin/source_observatory/models.py:281-288`, `src/robin/source_observatory/store.py:209-221`).
- **Justification et scénario d'échec concret** :
  - Nous acceptons qu'un auteur ait pu déclarer une cote à `18h00` (`cote_declaree_at = 18h00`) dans un billet découvert par Robin à `22h00` (`first_observed_by_robin_at = 22h00`).
  - En revanche, nous **maintenons** qu'aucun contrôle n'empêche d'antidater une cote **observée par Robin** (`cote_observee_at`) avant que Robin n'ait observé la publication, ni d'attacher à une contribution figée à `18h00` une cote datée dans le futur :
    - **Scénario d'échec concret** :
      1. Pour un match à `20h00`, Robin découvre une publication après le match à `22h00` (`first_observed_by_robin_at = 22h00`), ou avant le match à `19h00`, mais `Contribution.__post_init__` (`models.py:281-288`) et `AppendOnlyStore._validate_lineage` (`store.py:209-221`) acceptent sans erreur `cote_observee_at = 12h00` (horodatage d'observation de cote par Robin antérieur de plusieurs heures à la première observation de la publication par Robin).
      2. Inversement, pour une `Contribution` observée à `observed_at = 18h00`, `models.py:281-288` et `store.py:209-221` acceptent `cote_observee_at = 19h55` et `cote_declaree_at = 19h55` (postérieurs à `contribution.observed_at`), permettant d'injecter dans une observation de `18h00` une cote qui n'existait qu'à `19h55` (voir **Constat 5**).

### Point contesté 3 — Constantes dans le test unitaire `classification_state` (issu du Constat 10.2 de Ronde 1)
- **Argument de Codex** : *« Les constantes dans un test unitaire de transitions ne sont pas une tautologie ; elles ne suffisaient cependant pas à vérifier l'intégration au journal. »*
- **Décision GEMINI** : **ACCEPTÉ sur le principe du test unitaire**, sous réserve que l'intégration au journal (`cohort_state()` dans `src/robin/source_observatory/ranking.py:245-284`) soit fidèle aux règles §05 et §19 — or cette nouvelle fonction `cohort_state()` introduit un défaut **BLOQUANT** sur le calcul de la couverture de visites et l'état par défaut de `rankings()` (voir **Constat 4**).

---

## 2. Synthèse par axe de contrôle en Ronde 2

| Axe de contrôle | Statut Ronde 2 | Synthèse |
| :--- | :--- | :--- |
| **1. Cote reconstruite / imputée** | Partiellement tenu | `cote_declaree` et `cote_observee` restent séparées, mais une sélection sans aucune cote (`cote_declaree=None, cote_observee=None`) avec `categorie='selection_avec_cote'` reste acceptée et comptabilisée comme sélection avec cote dans `Ranking.categories` (`ranking.py:204-206`). |
| **2. Horodatage imputé / antidaté** | **FAILLE (BLOQUANT)** | `store.py:183-191` ne vérifie la monotonie temporelle que sur `(PublicationVersion, Contribution)` vis-à-vis de `(PublicationVersion, Contribution, Result)`, permettant d'antidater une version/contribution pré-match après un `Visit`, `Withdrawal` ou `IdentityRevision` post-match déjà inscrit au journal ; `cote_observee_at` et `cote_declaree_at` n'ont aucune borne par rapport à `first_observed_by_robin_at` et `observed_at`. |
| **3. Texte post-match accepté comme pré-match** | **FAILLE (BLOQUANT)** | Pour un pari `combine`, `evaluate()` et `combined_legs_proven()` (`service.py:146-159, 176-197`) vérifient uniquement que `c_leg1` était pré-match par rapport à la jambe 1, mais **jamais** que le combiné `c_combo` lui-même a été publié avant le coup d'envoi de chaque jambe : un combiné publié à `20h00` (après la victoire de la jambe 1 de `18h00`) est validé comme pré-match gagnant. |
| **4. Mutation / contournement append-only** | **FAILLE (BLOQUANT)** | Si une jambe d'un combiné gagnant est corrigée en `'perdu'` avec preuve d'audit (`Result` `r_leg1_v2`), `store.read()` et `rankings()` (`ranking.py:158-190`) ne revérifient pas les jambes du combiné et continuent de compter le combiné comme gagnant (`+3.00`). |
| **5. Fusion d'identités par pseudo similaire** | **FAILLE (MAJEUR)** | `IdentityRevision` (`models.py:474-476`) et `AppendOnlyStore` acceptent d'enregistrer `AccountAssignment('account-b', 'account-a')` avec `certainty='similarite'` ; et `ranking.py:141` (`identities.update`) conserve indéfiniment les anciennes fusions non réécrites lors d'une révision partielle. |
| **6. Retrait qui améliore un score** | **FAILLE (BLOQUANT)** | Trois vecteurs permettent encore d'effacer une perte `-1` dans `rankings()` : (a) une version `v2` pré-match qui rétrograde `selection-1` en `selection_sans_cote` / `cote_declaree=None` / `non_resolu` (ou décale le match 2 en `selection-1`) écrase la perte sans même déclencher `Comparable suspendu` ; (b) une contribution retirée via `Withdrawal` mais remplacée dans `v2` (ou non dotée d'un `Result`) reste exclue du ROI ; (c) une évaluation non évaluable (`cote_absente`) à `T` écrase une évaluation perdante (`-1`) à `T+1m` dans `unique.setdefault(key, e)` (`ranking.py:196-199`). |
| **7. Règlement et états de cohorte** | **FAILLE (BLOQUANT)** | `combined_legs_proven()` (`service.py:184-195`) permet à un auteur de construire un combiné gagnant avec les `Contribution` d'un **autre auteur**. Dans `cohort_state()` (`ranking.py:255, 270`), `sources` est déduit des seules contributions collectées : 10 visites planifiées échouées sur une seconde source `s2` (0 contribution collectée) sont ignorées, donnant `coverage = 100%` et promouvant l'auteur en `'Comparable'` / `'Signal prospectif'`. |
| **8. Payload brut stocké** | Corrigé | Limite globale à 5 emplacements, au plus 1 extrait textuel <= 500 caractères, sans chevauchement (`models.py:307-321`, `contribution.schema.json:124-136`). |
| **9. ROI mal calculé** | **FAILLE (BLOQUANT)** | Dans `ranking.py:198`, la clé de déduplication `(group_for[c.publication_id], m.match_id, m.market_id, m.selection_id, e.category)` omet `c.ligne` et `c.periode` : deux sélections distinctes d'une même publication sur le même match (`Over 1.5` gagné `+0.5` et `Over 3.5` perdu `-1.0`) collisionnent et la perte `-1.0` est effacée (`ROI = +0.50` au lieu de `-0.25`). |
| **10. Tests** | **FAILLE (MINEUR)** | `test_conception.py:91` passe `contribution()` (`observed_at=T`) au lieu de la contribution tardive de la ligne 89 dans `test_scenario_b_platform_18_discovered_22_is_retrospective`. |

---

## 3. Constats détaillés de Ronde 2

### Constat 1 — [BLOQUANT] Effacement de sélections perdantes par collision de clé de déduplication (`ligne` / `periode` omises) et par masquage via une évaluation non évaluable dans `rankings()`
- **Fichier:ligne** : `src/robin/source_observatory/ranking.py:195-207`
- **Scénario d'échec concret** :
  1. **Collision sur `total` / `handicap` à lignes différentes (`ranking.py:198`)** :
     - Un auteur publie dans `p1` (`v1`) deux paris sur le même match `m1` (score final `2-0`) :
       - `c1` (`selection_key='s1'`, `marche='total'`, `selection='over'`, `ligne=Decimal('1.5')`, `cote_declaree=Decimal('1.5')`) → gagné (`unit_profit = Decimal('0.5')`) ;
       - `c2` (`selection_key='s2'`, `marche='total'`, `selection='over'`, `ligne=Decimal('3.5')`, `cote_declaree=Decimal('3.0')`) → perdu (`unit_profit = Decimal('-1')`).
     - Comme `MatchMarket` ne contient que `(match_id, market_id, selection_id)` (`'m1'`, `'total'`, `'over'`) et que la ligne 198 calcule `key = (group_for[c.publication_id], m.match_id, m.market_id, m.selection_id, e.category)` **sans `c.ligne` ni `c.periode`**, `c1` et `c2` ont la même clé `('p1', 'm1', 'total', 'over', 'selection_avec_cote')`.
     - `unique.setdefault(key, e)` écrase `c2` : `rankings()` renvoie `net = Decimal('0.5')`, `stakes = 1`, `roi = Decimal('0.5')` au lieu de `net = Decimal('-0.5')`, `stakes = 2`, `roi = Decimal('-0.25')`.
  2. **Masquage d'une perte par une évaluation non évaluable (`unit_profit=None`) antérieure (`ranking.py:169-199`)** :
     - À `T`, `p1` contient `c_no_odds` (`selection='away'`, `cote_declaree=None` → `e_no.unit_profit = None`, `e_no.reason = 'cote_absente'`).
     - À `T + 1 min`, une reprise attestée `p2` du même auteur (ou d'un compte fusionné) publie la cote `cote_declaree=Decimal('2.0')` sur ce même pari (`c_loser`), qui perd (`e_lo.unit_profit = Decimal('-1')`).
     - La boucle `ranking.py:169-190` conserve les évaluations non évaluables dans `by_author`, puis `sorted(evaluations, key=lambda e: contributions[e.contribution_id].observed_at)` place `e_no` (`T`) avant `e_lo` (`T + 1 min`). `unique.setdefault(key, e_no)` garde `e_no` (`unit_profit=None`) et jette `e_lo` (`unit_profit=Decimal('-1')`). Résultat : `net = Decimal('0')`, `stakes = 0`, `roi = None` — la perte de `-1` disparaît.
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/ranking.py:198`, inclure `c.ligne` et `c.periode` dans la clé : `key = (group_for[c.publication_id], m.match_id, m.market_id, m.selection_id, c.ligne, c.periode, e.category)`.
  - Dans `src/robin/source_observatory/ranking.py:196`, trier par `(not e.evaluable, contributions[e.contribution_id].observed_at, c.contribution_id)` afin qu'une évaluation non évaluable (`e.evaluable == False`) ne puisse jamais masquer une évaluation évaluable.

---

### Constat 2 — [BLOQUANT] Retrait ou neutralisation pré-match d'une sélection perdante qui améliore le ROI (sans déclencher `Comparable suspendu` ou malgré `Withdrawal`)
- **Fichier:ligne** : `src/robin/source_observatory/ranking.py:24-40`, `src/robin/source_observatory/ranking.py:142-166`, `src/robin/source_observatory/ranking.py:182-184`
- **Scénario d'échec concret** :
  1. **Neutralisation d'un emplacement `selection_key` dans `v2` (ou décalage d'emplacements entre matchs)** :
     - À `18h00` (`T`), `v1` contient `loser` (`selection_key='s1'`, `match_id='m1'`, `selection='away'`, cote `2.40`, perdante `-1`) et `winner` (`selection_key='s2'`, `match_id='m2'`, `selection='home'`, cote `2.40`, gagnante `+1.40`). Le vrai bilan est `net = +0.40`, `stakes = 2`, `roi = +0.20`.
     - À `18h30` (`T + 30 min`, avant le coup d'envoi à `20h00`), l'auteur modifie sa publication (`v2`) pour retirer son pari perdant sur `m1` :
       - soit en passant `s1` dans `v2` (`c1_v2`) en `categorie='selection_sans_cote', cote_declaree=None` (ou `cote_declaree=None`, ou `statut='non_resolu'`, ou `certitude_rapprochement='probable'`) ;
       - soit en supprimant la ligne du match `m1` de son billet, ce qui décale le pari gagnant sur `m2` en première position (`selection_key='s1'`) dans `v2`.
     - Dans `pre_match_contributions()` (`ranking.py:36-39`), `slot = (entity.publication_id, entity.selection_key)` écrase `loser` par `c1_v2`.
     - Dans `rankings()` (`ranking.py:146-151, 182-184`), `loser not in eligible` élimine la perte `-1` (même si un `Withdrawal('w1', 'c1', ...)` a été enregistré !), et comme `s1` est toujours présent dans `v2`, `affected_authors` n'est même pas activé : `rankings()` renvoie `net = Decimal('1.4')`, `stakes = 1`, `roi = Decimal('1.4')`, `status = 'En observation'`, `coverage_changed = False`.
  2. **Omission de `Result` sur une contribution retirée (`ranking.py:158-166`)** :
     - Si `loser` est retirée à `18h30` via `Withdrawal('w1', 'c1', ...)` (ou omise dans `v2`) et qu'à `22h00` l'opérateur n'ajoute `Result` et `Evaluation` que pour `winner`, `m1.match_market_id in latest_results` vaut `False` (`ranking.py:160`) : aucune erreur n'est levée et `rankings()` renvoie `roi = Decimal('1.4')` sans la perte.
- **Correctif minimal** :
  - Dans `pre_match_contributions()` (`src/robin/source_observatory/ranking.py:24-40`) et la détection d'omission (`ranking.py:146-151`), indexer le slot par `(entity.publication_id, entity.match_id, entity.selection_key)` et refuser qu'une version ultérieure `v2` remplace une contribution résolue/cotée par une contribution non résolue ou sans cote (conserver la contribution cotée de `v1` et marquer `coverage_changed = True`).
  - Dans `src/robin/source_observatory/ranking.py:158-184`, inclure systématiquement les contributions de `withdrawn` (et les contributions omises/rétrogradées) dans les contributions devant être réglées et évaluées avant d'autoriser le calcul du bilan.

---

### Constat 3 — [BLOQUANT] Combinés (`evaluate` / `combined_legs_proven` / `rankings`) : combiné publié après le coup d'envoi d'une jambe validé comme pré-match, usurpation des jambes d'un autre auteur, et survie d'un combiné gagnant après correction perdante d'une jambe
- **Fichier:ligne** : `src/robin/source_observatory/service.py:146-159`, `src/robin/source_observatory/service.py:176-197`, `src/robin/source_observatory/ranking.py:158-190`
- **Scénario d'échec concret** :
  1. **Combiné post-match par rapport à sa 1re jambe et emprunt des jambes d'un autre auteur (`service.py:176-197`)** :
     - Un auteur `'other-author'` publie à `T` deux sélections pré-match : `c_leg1` sur `m1` (coup d'envoi à `T + 1h`, réglé `'gagne'` à `T + 2h30`, cote `2.0`) et `c_leg2` sur `m2` (coup d'envoi à `T + 4h`, réglé `'gagne'` à `T + 6h`, cote `2.0`).
     - À **`T + 3h`** (soit **30 minutes après la fin et le règlement gagnant de `m1`** !), `'account-a'` publie un combiné `c_combo` (`usable_at = T + 3h`, `observed_at = T + 3h`, `cote_declaree = Decimal('4.0')`) rattaché à `m_combo` (`match_usable_at = T + 4h`) et référence `legs = ('c_leg1', 'c_leg2')`.
     - `evaluate()` (`service.py:98, 155`) et `combined_legs_proven()` (`service.py:176-197`) vérifient uniquement `m_combo.pre_match_valid` (`T + 3h < T + 4h`) et `c_leg1 in pre_match_contributions(items, m_leg1.match_usable_at)` (`T < T + 1h`), sans jamais vérifier que `c_combo` a été publié avant `m_leg1.match_usable_at` (`T + 3h < T + 1h` est faux !) ni que `c_leg1.author_id == c_combo.author_id`. Résultat : `e_combo.evaluable == True` et `e_combo.unit_profit == Decimal('3.00')`.
  2. **Survie du combiné gagnant dans `rankings()` après correction auditée d'une jambe en `'perdu'` (`ranking.py:158-190`)** :
     - À `T + 7h`, le résultat de la jambe 1 est corrigé avec preuve d'audit (`r_leg1_v2`, `previous_result_id='r:c_leg1'`, `outcome='perdu'`, `audit_evidence_sha256=H`) suivi de `e_leg1_v2` (`unit_profit = Decimal('-1')`).
     - `AppendOnlyStore.read()` valide chaque enregistrement sur son préfixe au moment de l'ajout (`store.py:327`), et `rankings()` (`ranking.py:158-190`) ne revérifie jamais `combined_legs_proven()` sur les derniers résultats `latest_results` des jambes : `rankings()` continue d'attribuer `net = Decimal('3.00')` au combiné dont la jambe 1 est pourtant `'perdu'`.
- **Correctif minimal** :
  - Passer `contribution` et `match` à `combined_legs_proven(contribution, match, result, evidence, basis)` (`src/robin/source_observatory/service.py:176-197`) et exiger pour chaque jambe :
    1. `c.author_id == contribution.author_id` ;
    2. `max(match.contribution_usable_at, contribution.observed_at) < m.match_usable_at` (le combiné doit précéder le coup d'envoi de *chaque* jambe) ;
    3. `r.result_id == latest_results.get(m.match_market_id)`.
  - Dans `src/robin/source_observatory/ranking.py:158-190`, vérifier `combined_legs_proven(...)` sur `items` pour toute évaluation de combiné et lever une `ValueError` si une jambe a reçu un nouveau `Result` sans mise à jour du résultat/évaluation du combiné.

---

### Constat 4 — [BLOQUANT] Cohorte (`cohort_state` et `rankings`) : visites planifiées échouées ignorées sur toute source sans contribution collectée (`coverage` surestimée à `100%`) et `Cohort` ignorée lorsque `rankings()` est appelé sans `at`
- **Fichier:ligne** : `src/robin/source_observatory/ranking.py:217-225`, `src/robin/source_observatory/ranking.py:245-284`
- **Scénario d'échec concret** :
  1. **Échecs de collecte ignorés sur une source sans contribution collectée (`ranking.py:255, 270-271`)** :
     - Dans `cohort_state()`, l'ensemble des sources de l'auteur est calculé par `sources = {c.source_id for c in cs.values()}` (`ranking.py:255`), puis les visites sont filtrées par `v.source_id in sources` (`ranking.py:270`).
     - Scénario : Une cohorte exige `minimum_visit_coverage = Decimal('0.8')`. Pendant la fenêtre d'évaluation, Robin planifie 1 visite sur `s1` (`succeeded=True`, 1 contribution collectée et évaluée) et 10 visites sur `s2` qui échouent toutes (`succeeded=False`, donc 0 contribution collectée sur `s2`).
     - La couverture réelle des visites planifiées est `1 / 11 = 9.1% < 80%`. Or, comme aucune contribution n'a pu être collectée sur `s2`, `sources` vaut uniquement `{'s1'}` : les 10 visites échouées sur `s2` sont ignorées, `coverage` vaut `1 / 1 = 100%`, et `rankings()` promeut l'auteur à `'Comparable'` (ou `'Signal prospectif'`), violant directement le §19 (*« Couverture de visites = observations planifiees reussies/planifiees (pas le rappel). Absence dans la collecte != absence de publication »*).
     - De même, si un auteur de la cohorte a 0 contribution collectée dans la fenêtre d'évaluation mais 100% de visites réussies sur sa source, `sources` est `set()`, donc `visits` est vide (`coverage = None`).
  2. **Appel `rankings(entities)` sans paramètre `at` (`ranking.py:222`)** :
     - Si `rankings(store.entities())` est appelé avec sa valeur par défaut `at=None`, la condition `if cohorts and at is not None:` (`ranking.py:222`) est fausse : toutes les cohortes et visites du journal sont ignorées et `status` vaut toujours `'En observation'` (même pour un auteur en `'Decouverte'`, `'Comparable'` ou `'Signal prospectif'`).
- **Correctif minimal** :
  - Dans `cohort_state()` (`src/robin/source_observatory/ranking.py:255, 270-271`), ne pas restreindre `sources` aux seules contributions collectées (`cs`) : inclure toutes les `Visit` planifiées du journal dans la fenêtre (ou ajouter `source_ids: tuple[str, ...]` sur `Cohort` / prendre toutes les `Source` enregistrées dans `items` lorsque `sources` ne couvre pas toutes les sources visitées).
  - Dans `rankings()` (`src/robin/source_observatory/ranking.py:222`), lorsque `cohorts` est non vide et `at is None`, dériver l'instant de référence du dernier horodatage observé dans `items` (ou exiger explicitement `at`).

---

### Constat 5 — [BLOQUANT] Antidatage d'observations pré-match derrière des événements `Visit` / `Withdrawal` / `IdentityRevision` dans `AppendOnlyStore`, et absence de bornes sur `cote_observee_at` / `cote_declaree_at`
- **Fichier:ligne** : `src/robin/source_observatory/store.py:183-191`, `src/robin/source_observatory/store.py:209-221`, `src/robin/source_observatory/models.py:281-288`
- **Scénario d'échec concret** :
  1. **Injection d'une version/contribution antidatée après un `Visit`, `Withdrawal` ou `IdentityRevision` post-match (`store.py:183-191`)** :
     - Un match commence à `20h00` et se termine à `21h50`. À `21h55`, le journal enregistre `Visit('v-post', 's1', planned_at=21h50, completed_at=21h55, succeeded=True)` (ou un `Withdrawal` / `IdentityRevision` observé à `21h55`).
     - Dans `store.py:183-191`, `observations` ne collecte que `(PublicationVersion, Contribution, Result)` et ignore `Visit`, `Withdrawal`, `IdentityRevision` et `Cohort`.
     - On peut alors ajouter à la suite du journal (après `Visit` à `21h55`) une `PublicationVersion` et une `Contribution` gagnante antidatées à `19h00` (`first_observed_by_robin_at = 19h00, usable_at = 19h00, observed_at = 19h00`), qui sont validées comme pré-match. Inversement, `Result`, `Withdrawal`, `IdentityRevision` et `Visit` ne sont pas vérifiés par le bloc `if isinstance(entity, ...)` de la ligne 183 et peuvent être antidatés avant la dernière observation du journal.
  2. **Horodatages de cote `cote_observee_at` et `cote_declaree_at` incohérents (`models.py:281-288`, `store.py:209-221`)** :
     - Une `Contribution` observée à `observed_at = 18h00` sur une version `first_observed_by_robin_at = 18h00` est acceptée avec `cote_observee_at = 12h00` (6h avant que Robin n'ait observé la publication) ou avec `cote_observee_at = 19h55` / `cote_declaree_at = 19h55` (postérieur à `contribution.observed_at`).
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/store.py:183-191`, étendre le contrôle de non-antidatage à l'ensemble des entités horodatées du journal (`PublicationVersion`, `Contribution`, `Result`, `IdentityRevision`, `Withdrawal`, `Visit`, `Cohort`).
  - Dans `src/robin/source_observatory/models.py:281-288` et `src/robin/source_observatory/store.py:209-221`, exiger `cote_declaree_at <= self.observed_at` et `version.first_observed_by_robin_at <= cote_observee_at <= self.observed_at`.

---

### Constat 6 — [MAJEUR] `IdentityRevision` : acceptation d'un alias inter-comptes avec `certainty='similarite'` et persistance des fusions antérieures lors d'une révision partielle
- **Fichier:ligne** : `src/robin/source_observatory/models.py:474-476`, `src/robin/source_observatory/ranking.py:138-141`
- **Scénario d'échec concret** :
  1. **Enregistrement d'un alias sur pseudo similaire accepté par `IdentityRevision` et `AppendOnlyStore` (`models.py:474-476`)** :
     - La garde `if self.certainty != 'attestee' and len({a.identity_id for a in self.assignments}) < len(self.assignments):` n'interdit pas `IdentityRevision('similar', None, (AccountAssignment('account-b', 'account-a'),), T, H, 'pseudo similaire', certainty='similarite')` (car `1 < 1` est faux). Un rattachement d'un compte vers l'identifiant d'un autre compte fondé uniquement sur la similarité est donc accepté par le modèle et inscrit dans la chaîne de hachage du journal.
  2. **Persistance d'une fusion annulée lors d'une révision partielle (`ranking.py:141`)** :
     - Si `rev-1` (`certainty='attestee'`) fusionne `('account-a', 'merged')` et `('account-b', 'merged')`, puis que `rev-2` (`previous_revision_id='rev-1'`, `certainty='attestee'`) met à jour les affectations avec `(AccountAssignment('account-a', 'account-a'),)` (sans répéter `'account-b'`), `identities.update(...)` (`ranking.py:141`) laisse `'account-b'` rattaché à `'merged'`.
- **Correctif minimal** :
  - Dans `IdentityRevision.__post_init__` (`src/robin/source_observatory/models.py:474-476`), si `self.certainty != 'attestee'`, refuser toute affectation où `a.author_id != a.identity_id`.
  - Dans `src/robin/source_observatory/ranking.py:138-141` (et `store.py:259-268`), appliquer uniquement la dernière `IdentityRevision` attestée complète (ou réinitialiser les comptes qui partageaient un `identity_id` modifié).

---

### Constat 7 — [MAJEUR] Étiquetage erroné du groupe par un relais intermédiaire dans `reprise_groups()` et contagion de reprise entre sélections d'une même publication
- **Fichier:ligne** : `src/robin/source_observatory/ranking.py:43-71`, `src/robin/source_observatory/ranking.py:81-102`
- **Scénario d'échec concret** :
  1. Dans `reprise_groups()` (`ranking.py:50-53`), `roots.add(link.publication_id)` ajoute dans `roots` toute cible d'un `RepriseLink` attesté, y compris un relais intermédiaire qui possède lui-même un `RepriseLink` sortant vers la véritable origine.
  2. Avec `p_orig` (`publication_id='pub-origin'`), `p_relais` (`publication_id='aaa-relais'`, `liens_reprise=(RepriseLink('pub-origin', 'attestee', H),)`), et `p_copie` (`publication_id='zzz-copie'`, `liens_reprise=(RepriseLink('aaa-relais', 'attestee', H),)`), `min(set(pubs) & roots)` (`ranking.py:70`) choisit `'aaa-relais'` au lieu de `'pub-origin'`, contredisant `origin_groups()` (`origin_publication_id='pub-origin'`).
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/ranking.py:47-70`, exclure de `roots` toute publication ayant au moins un lien de reprise attesté sortant (`outgoing`), afin que seule une racine sans lien sortant soit privilégiée comme étiquette de groupe.

---

### Constat 8 — [MAJEUR] Catégorie `'selection_avec_cote'` acceptée sans aucune cote (`cote_declaree=None` et `cote_observee=None`) et comptabilisée à tort dans `Ranking.categories`
- **Fichier:ligne** : `src/robin/source_observatory/models.py:291-294`, `src/robin/source_observatory/schemas/contribution.schema.json:440-458`, `src/robin/source_observatory/ranking.py:204-206`
- **Scénario d'échec concret** :
  1. On instancie `Contribution(..., categorie='selection_avec_cote', cote_declaree=None, cote_observee=None)`. Ni `Contribution.__post_init__` (`models.py:291-294`) ni `contribution.schema.json` ne le refusent.
  2. Après évaluation (`e.reason = 'cote_absente'`, `e.evaluable = False`), `rankings()` (`ranking.py:204-206`) incrémente `category_counts['selection_avec_cote'] += 1` pour toutes les évaluations de `evaluations` (même lorsque `not e.evaluable`). Une sélection dépourvue de toute cote est donc rapportée dans `Ranking.categories` comme `('selection_avec_cote', 1)` alors que `stakes == 0`.
- **Correctif minimal** :
  - Dans `Contribution.__post_init__` (`src/robin/source_observatory/models.py:291-294`) et `src/robin/source_observatory/schemas/contribution.schema.json:440-458`, exiger qu'une contribution de catégorie `'selection_avec_cote'` possède au moins une cote non nulle (`cote_declaree is not None or cote_observee is not None`), et dans `src/robin/source_observatory/ranking.py:204-206`, ne compter une `'selection_avec_cote'` que si elle est évaluable sur la base `odds_basis` retenue (ou compter séparément les non-évaluables).

---

### Constat 9 — [MINEUR] Fixture incohérente dans `test_scenario_b_platform_18_discovered_22_is_retrospective`
- **Fichier:ligne** : `tests/source_observatory/test_conception.py:85-95`
- **Scénario d'échec concret** :
  - À la ligne 89, le test enregistre dans le store `c=contribution(observed_at=T + timedelta(hours=4))`, mais aux lignes 91-92 il appelle `service.evaluate(contribution(), match(contribution(), contribution_usable_at=v.usable_at), settled(), odds_basis='cote_declaree')` en repassant `contribution()` par défaut (`observed_at=T`) au lieu de la contribution découverte tardivement à `T + 4h`.
- **Correctif minimal** :
  - Dans `tests/source_observatory/test_conception.py:89-92`, stocker `c = contribution(observed_at=T + timedelta(hours=4))` dans une variable locale et passer cette instance `c` à `service.evaluate(c, match(c, contribution_usable_at=v.usable_at), settled(c), odds_basis='cote_declaree')`.

---

## 4. Verdict final

**Verdict : `REFUSE`**

Les corrections de la Ronde 1 ont bien traité l'encodage du schéma, la limite globale des extraits de preuve (`<= 500` caractères, max 5 emplacements dont 1 textuel sans chevauchement) et le refus d'un second `MatchMarket` sur la même contribution. Toutefois, **cinq défauts bloquants** (dont plusieurs introduits par le code de correction de Ronde 1 dans `ranking.py` et `service.py`) permettent encore :
1. d'effacer une sélection perdante sur un même match lorsque deux paris `total` ou `handicap` ont des lignes différentes (`Over 1.5` vs `Over 3.5`), ou lorsqu'une évaluation `cote_absente` précède une reprise cotée perdante (`src/robin/source_observatory/ranking.py:195-200`) ;
2. d'améliorer un ROI en remplaçant pré-match un emplacement perdant par une sélection sans cote / non résolue (ou en décalant les sélections d'un billet multi-matchs), sans même déclencher `Comparable suspendu` (`src/robin/source_observatory/ranking.py:24-40, 146-151, 182-184`) ;
3. de faire valider comme pré-match gagnant un combiné publié *après* la fin de sa première jambe, d'assembler les jambes d'un autre auteur, et de conserver le gain du combiné dans `rankings()` après correction auditée d'une jambe en `'perdu'` (`src/robin/source_observatory/service.py:146-159, 176-197`, `src/robin/source_observatory/ranking.py:158-190`) ;
4. d'obtenir un statut `'Comparable'` / `'Signal prospectif'` avec 10 visites planifiées échouées sur une source où aucune contribution n'a été collectée (`src/robin/source_observatory/ranking.py:255, 270`), et d'ignorer les cohortes lorsque `rankings()` est appelé sans `at` (`src/robin/source_observatory/ranking.py:222`) ;
5. d'antidater une version et une contribution pré-match dans le journal après un `Visit`, `Withdrawal` ou `IdentityRevision` post-match, et d'enregistrer un `cote_observee_at` antérieur à `first_observed_by_robin_at` ou postérieur à `Contribution.observed_at` (`src/robin/source_observatory/store.py:183-191, 209-221`, `src/robin/source_observatory/models.py:281-288`).
