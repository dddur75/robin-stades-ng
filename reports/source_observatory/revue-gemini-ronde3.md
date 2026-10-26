# Revue contradictoire Ronde 3 — PR #128 (`codex/observatoire-sources-v2`)

- **Relecteur** : GEMINI (relecture contradictoire indépendante, Ronde 3)
- **Branche inspectée (lecture seule)** : `codex/observatoire-sources-v2` (`cf9ec465166fd4b069fcd0a07b8a9ced30dbb5e4`)
- **Périmètre pilote prioritaire** : chaîne `collecte -> contribution -> horodatages -> reglement` (`src/robin/source_observatory/collector.py`, `src/robin/source_observatory/extractor.py`, `src/robin/source_observatory/models.py`, `src/robin/source_observatory/store.py`, `src/robin/source_observatory/service.py`, `src/robin/source_observatory/settlement.py`, `data/source_observatory/`)
- **Périmètre classé séparément (`HORS_PILOTE`)** : `rankings()` et cohortes (`src/robin/source_observatory/ranking.py`)
- **Référentiels** : `reports/source_observatory/REGLES-DOSSIER-CONCEPTION.md` (§04, §05, §17, §19), `data/source_observatory/pilot_criteria.md` (critères gelés C1–C6) et `reports/source_observatory/reponse-revue-gemini-ronde2.md`
- **Verdict final pour le périmètre pilote** : **`REFUSE`** (5 constats **BLOQUANTS**, 1 **MAJEUR**, 1 **MINEUR**, 1 **HORS_PILOTE**)

---

## 1. Examen de `reports/source_observatory/reponse-revue-gemini-ronde2.md`

Dans `reports/source_observatory/reponse-revue-gemini-ronde2.md`, Codex n'a contesté aucun constat de fond de la Ronde 2 (les 5 bloquants, 3 majeurs et 1 mineur ont été acceptés et accompagnés de `tests/source_observatory/test_round2_regressions.py`). Seul un cas de test sur la période « première mi-temps » a été écarté par Codex au motif que seule la période `'reglementaire'` est ouverte au règlement dans ce jalon.

### Décision GEMINI sur la réponse de Codex (Ronde 2)
- **Point sur la période `'mi_temps'` (ligne 16 de `reponse-revue-gemini-ronde2.md`)** : **ACCEPTÉ** — tant que `settlement.supported()` (`src/robin/source_observatory/settlement.py:17-20`) restreint explicitement le règlement automatique à `period == 'reglementaire'` et laisse toute autre période en `'en_attente'`, ne pas ouvrir ce marché est conforme au §19.
- **Évaluation des correctifs de Ronde 2 appliqués par Codex** :
  - **Constat 1 (Déduplication `ligne`/`periode` et tri `not e.evaluable`)** : **ACCEPTÉ** (`src/robin/source_observatory/ranking.py:236-241`).
  - **Constat 2 (Neutralisation / retrait / `preserves_evidence`)** : **PARTIELLEMENT CORRIGÉ — FAILLE RÉSIDUELLE BLOQUANTE** dans `pre_match_contributions()` (`src/robin/source_observatory/ranking.py:38-64`) lorsqu'une sélection perdante est supprimée en `v2` sur un match comportant une seconde sélection gagnante qui se décale en `selection-1` (voir **Constat 3**), et dans `rankings()` lorsqu'un `Withdrawal` est fourni sans `MatchMarket` (voir **Constat 8 — HORS_PILOTE**).
  - **Constat 3 (Combinés)** : **PARTIELLEMENT CORRIGÉ — FAILLE RÉSIDUELLE BLOQUANTE** dans `combined_legs_proven()` (`src/robin/source_observatory/service.py:177-201`), qui ne vérifie pas l'éligibilité pré-match de la version du combiné lui-même dans `items` et autorise un combiné dont les deux jambes portent sur le même match et la même sélection (voir **Constat 3**).
  - **Constat 4 (Couverture de cohorte et `at` par défaut)** : **ACCEPTÉ** sur `cohort_state()` (`src/robin/source_observatory/ranking.py:153-155, 326-333`), mais le nouveau collecteur T7 introduit un **BLOQUANT** sur `visit_coverage()` et la couverture du plan pilote (voir **Constat 5**).
  - **Constat 5 (Monotonie temporelle et bornes de cotes)** : **PARTIELLEMENT CORRIGÉ — FAILLE RÉSIDUELLE BLOQUANTE** sur `PublicationVersion` initiale avec `modification_observed_at != None` et sur `cote_observee_at` comparée à `first_observed_by_robin_at` au lieu de `version.usable_at` lors d'une modification `v2` (voir **Constat 2**).
  - **Constat 6 (Identités / alias `similarite` et snapshot complet)** : **ACCEPTÉ** (`src/robin/source_observatory/models.py:479-481`, `src/robin/source_observatory/ranking.py:165-167`).
  - **Constat 7 (Étiquette de racine dans `reprise_groups`)** : **ACCEPTÉ** (`src/robin/source_observatory/ranking.py:72-97`).
  - **Constat 8 (Catégorie `'selection_avec_cote'` exigeant une cote explicite)** : **ACCEPTÉ** (`src/robin/source_observatory/models.py:293-295`, `src/robin/source_observatory/schemas/contribution.schema.json:283-288`).
  - **Constat 9 (Fixture rétrospective dans `test_conception.py`)** : **ACCEPTÉ** (`tests/source_observatory/test_conception.py:85-95`).

---

## 2. Synthèse des axes prioritaires du périmètre pilote (Ronde 3)

| Axe de contrôle pilote | Statut Ronde 3 | Synthèse |
| :--- | :--- | :--- |
| **1. Horodatage imputé / antidaté** | **FAILLE (BLOQUANT)** | `_Articles` (`collector.py:296-297`) écrase la date de publication par toute balise `<time>` ultérieure (ex. heure du coup d'envoi dans l'article) ; `_persist_post` (`collector.py:308, 389`) impute le `first_observed_by_robin_at` d'un article antérieur à un nouvel article sans permalien propre ; `store.py:185-219` permet d'antidater `first_observed_by_robin_at` sur une `v1` dotée d'un `modification_observed_at` et d'antidater `cote_observee_at` avant `v2.modification_observed_at`. |
| **2. Texte post-coup-d'envoi accepté comme pré-match** | **FAILLE (BLOQUANT)** | Un article post-coup-d'envoi publié sur une page sans `id`/`rel="bookmark"` hérite du `first_observed_by_robin_at` pré-match de l'article précédent (`collector.py:308, 389`) ; `combined_legs_proven()` (`service.py:186-200`) ne vérifie pas que le combiné lui-même appartient à `pre_match_contributions(items, m.match_usable_at)`. |
| **3. Cote reconstruite / inventée** | **FAILLE (BLOQUANT)** | Dans `extractor.py:294-298`, sur une conjonction `&` où seule la dernière jambe porte une cote (`"Victoire de Nice & plus de 1,5 buts @1.42"`), `not any(_odds(leg)[0] for leg in legs[:-1])` vaut `True` et la cote de la seule seconde jambe (`1.42`) est attribuée comme `cote_declaree` du combiné entier. |
| **4. Payload brut écrit dans Git** | **CONFORME** | `collector.py:357-365` exige `SOURCE_OBSERVATORY_RAW_DIR` hors de tout worktree Git et `store.py` ne persiste que des métadonnées typées et empreintes SHA-256 (`<= 500` caractères autorisés). |
| **5. Collecte qui contourne `robots.txt` / CGU** | **FAILLE (BLOQUANT)** | `robots_policy()` (`collector.py:239-243`) ignore toute directive `User-agent: RobinSourceObservatory/1.0` ou `RobinSourceObservatory*` (`Disallow: /`) ; `_endpoint()` (`collector.py:207-209`) supprime le mot `"interdiction"` après toute négation précédente dans la phrase (`"pas de flux RSS, interdiction de scraping"`), autorisant la collecte d'une source interdite par ses CGU. |
| **6. Écrasement d'une version / sélection au lieu d'une nouvelle version** | **FAILLE (BLOQUANT)** | `_Articles` + `_persist_post` (`collector.py:308-310, 379-391`) fusionnent deux articles distincts sans `id`/`rel="bookmark"` sous le même `publication_id` ; `pre_match_contributions()` (`ranking.py:38-64`) écrase une sélection perdante `selection-1` en `v1` lorsqu'elle est supprimée en `v2` et que la sélection gagnante `selection-2` du même match se décale en `selection-1`. |
| **7. Couverture de visites mal calculée** | **FAILLE (BLOQUANT)** | `collector.py:432-440` inscrit dès le premier run les 819 visites du plan (y compris futures non échues) avec `succeeded=False`, faussant `visit_coverage(store.entities())` ; et `_endpoint()` + `parse_publications()` plafonnent structurellement le plan gelé `visit_plan_20261031.json` à 14/39 sources (`35,9 %` max contre `>= 80 %` et `>= 25` sources exigés par `C1.1`/`C1.2`) tout en ignorant `<media:description>` sur YouTube Atom. |
| **8. Kickoffs (`Europe/Paris` -> `UTC`) et règlement** | **FAILLE (BLOQUANT / MAJEUR)** | Les 7 horaires de `kickoffs_20261031.json` (`+01:00` `Europe/Paris`) ont des instants UTC exacts dans `visit_plan_20261031.json`, mais `build_plan()`/`collect()` perdent le fuseau d'origine `Europe/Paris` dans le journal (`origin_timezone='UTC'`) et `test_collector.py:314-325` ne vérifie jamais `kickoffs_20261031.json`. Surtout, `settle()` (`settlement.py:56, 68, 80`) ignore `match.selection_id` et laisse en `'en_attente'` 100 % des sélections nommant une équipe issues de `extractor.py`. |

---

## 3. Constats détaillés de Ronde 3

### Constat 1 — [BLOQUANT] Contournement de directives `robots.txt` ciblant le User-Agent complet/wildcard et contournement de clauses CGU interdisant la collecte dans `collector.py`
- **Fichier:ligne** : `src/robin/source_observatory/collector.py:207-209`, `src/robin/source_observatory/collector.py:239-243`
- **Scénario concret** :
  1. **Contournement d'un bloc `robots.txt` ciblant `RobinSourceObservatory/1.0` ou `RobinSourceObservatory*` (`collector.py:239-243`)** :
     - Le collecteur envoie l'en-tête `User-Agent: RobinSourceObservatory/1.0` (`collector.py:39, 97`), mais la ligne 239 tronque `ua = USER_AGENT.split('/')[0].lower()` à `'robinsourceobservatory'`, puis `specificity()` (`collector.py:240-242`) évalue `name in ua`.
     - Si un éditeur bloque explicitement ce bot dans son `robots.txt` avec :
       ```text
       User-agent: RobinSourceObservatory/1.0
       Disallow: /

       User-agent: *
       Allow: /
       ```
       (ou `User-agent: RobinSourceObservatory*`), alors `'robinsourceobservatory/1.0' in 'robinsourceobservatory'` vaut `False` (`specificity = -1`). Le collecteur ignore la directive `Disallow: /` spécifique, retombe sur `User-agent: *` (`Allow: /`), et **collecte la source en violation directe de `robots.txt`**.
  2. **Contournement d'une interdiction contractuelle de scraping dans `_endpoint()` (`collector.py:207-209`)** :
     - La ligne 207 exécute `cleaned = re.sub(r"(?:pas de|pas d'|aucune? )[^;:.]*?(?:interdiction|anti-scraping)", '', terms)` avant de tester `re.search(r'interdit|interdiction|prohib|uniquement.*navigation|usage prive', cleaned)` à la ligne 208.
     - Comme `[^;:.]*?` traverse les virgules et propositions, dès qu'une mention négative précède une interdiction dans la même proposition — par exemple `"CGU : pas de flux RSS public, interdiction de scraping et de collecte automatisee"` ou `"CGU : aucune autorisation accordee, interdiction d'extraction"` — `re.sub` efface tout depuis `"pas de "` jusqu'à `"interdiction"`. La chaîne nettoyée devient `"cgu :  de scraping et de collecte automatisee"`, ne déclenche plus la ligne 208, et `_endpoint()` renvoie `(source.url, None)`, **autorisant la collecte automatisée d'une source qui l'interdit**.
     - De même, les interdictions contractuelles formulées avec `"scraping"`, `"usage personnel"`, `"non commercial"`, `"forbidden"` ou `"not permitted"` ne figurent pas dans l'expression de refus de la ligne 208.
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/collector.py:239-243`, normaliser le jeton d'agent (`token = name.rstrip('*').split('/')[0]`) et calculer la spécificité pour tout `name` vérifiant `name == '*' or (token and token in ua)` (en rejetant `name == ''`).
  - Dans `src/robin/source_observatory/collector.py:207-209`, restreindre la suppression aux seules négations directes sans traverser de virgule ni de conjonction (`r"(?:pas de|pas d'|aucune?|sans)\s+(?:clause\s+)?(?:d'|de\s+)?(?:interdiction|anti-scraping|restriction)"`) et étendre le motif de refus de la ligne 208 à `r'interdit|interdiction|prohib|forbidden|not permitted|anti-scraping|scraping\s+interdit|usage personnel|non[- ]commercial|uniquement.*navigation|usage prive'`.

---

### Constat 2 — [BLOQUANT] Écrasement de publications distinctes en fausse « version corrigée » et imputation/antidatage d'horodatages (`first_observed_by_robin_at`, `announced_by_platform_at`, `cote_observee_at`) dans `collector.py`, `models.py` et `store.py`
- **Fichier:ligne** : `src/robin/source_observatory/collector.py:296-297`, `src/robin/source_observatory/collector.py:308-310`, `src/robin/source_observatory/collector.py:379-392`, `src/robin/source_observatory/models.py:111-129`, `src/robin/source_observatory/store.py:185-220`
- **Scénario concret** :
  1. **Écrasement d'une publication par une autre et antidatage de `first_observed_by_robin_at` (`collector.py:308-310, 379-391`)** :
     - Dans `_Articles.handle_endtag` (`collector.py:308-309`), lorsqu'un `<article>` HTML ne possède ni attribut `id` ni lien `<a rel="bookmark">`, son URL cible est initialisée à `target = self.url` (l'URL de la page de liste/rubrique).
     - À `12h00 UTC` (avant le coup d'envoi de `16h15 UTC`), la page contient un `<article>` pour le billet A (`"Ligue 1 : pronostic Nice - Rennes"`). `_persist_post()` crée `pub_id = 'publication:' + text_fingerprint(source_id + ':' + self.url)` et `v1` avec `first_observed_by_robin_at = 12h00 UTC`.
     - À `17h00 UTC` (après le coup d'envoi de `16h15 UTC`), un nouveau billet B (`"Ligue 1 : bilan Nice - Rennes et prono Lyon"`) remplace le billet A en tête de page dans `<article>`. Son `target` vaut toujours `self.url` : `_persist_post()` calcule le **même `pub_id`**, enregistre le billet B comme une version corrigée `v2` (`previous_version_id = v1.version_id`) du billet A, et **lui impute `first_observed_by_robin_at = 12h00 UTC`** (`previous.first_observed_by_robin_at if previous else observed`, `collector.py:389`).
  2. **Imputation ou effacement de `announced_by_platform_at` par une balise `<time>` secondaire dans `_Articles` (`collector.py:296-297`)** :
     - Dans `_Articles.handle_starttag`, `if tag == 'time': self.date = _announced(values.get('datetime'))` écrase `self.date` à chaque balise `<time>` de l'article.
     - Si l'en-tête de l'article indique `<time datetime="2026-10-30T10:00:00+01:00">Publié le 30/10</time>` et que le corps du texte mentionne `<time datetime="2026-10-31T20:45:00+01:00">Coup d'envoi à 20h45</time>` (ou `<time>20h45</time>` sans attribut `datetime`), `announced_by_platform_at` est écrasé par l'horaire du coup d'envoi du match (**horodatage imputé**) ou remis à `None`.
  3. **Antidatage de `first_observed_by_robin_at` sur une `v1` et de `cote_observee_at` sur une `v2` dans `AppendOnlyStore` (`models.py:111-129`, `store.py:185-189, 217-219`, `ranking.py:27-28`)** :
     - `PublicationVersion.__post_init__` (`models.py:111-114`) n'interdit pas `modification_observed_at is not None` lorsque `previous_version_id is None`. Comme `observation_time(v)` (`ranking.py:27-28`) retourne `v.modification_observed_at or v.first_observed_by_robin_at`, un appelant peut enregistrer à `22h00` (après le match) une toute première version `v1` (`previous_version_id=None`, `modification_observed_at=22h00`, `usable_at=22h00`) avec `first_observed_by_robin_at = 18h00` (antidaté de 4 heures avant le match) sans être bloqué par `store.py:188`.
     - Dans `store.py:217-219`, la garde `entity.cote_observee_at < version.first_observed_by_robin_at` compare l'observation de cote par Robin à `first_observed_by_robin_at` (`18h00`, hérité de `v1`) au lieu de `version.usable_at` (`22h00` pour une `v2` modifiée après le match) : une contribution extraite d'une version `v2` modifiée à `22h00` peut ainsi porter une `cote_observee_at = 18h00` pré-match antidatée avant même l'existence de `v2`.
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/collector.py:296-310`, ne renseigner `self.date` et `self.post_url` que s'ils sont encore `None`, et refuser tout `<article>` HTML dépourvu à la fois de `self.post_url` et de `self.identifier` (`raise ValueError('publication without public permalink')`) au lieu de retomber sur `self.url`.
  - Dans `src/robin/source_observatory/models.py:111-115`, ajouter `elif self.modification_observed_at is not None: raise ValueError('initial version cannot have modification_observed_at')` lorsque `self.previous_version_id is None`.
  - Dans `src/robin/source_observatory/store.py:217-219`, remplacer `version.first_observed_by_robin_at` par `version.usable_at` (`if entity.cote_observee_at is not None and entity.cote_observee_at < version.usable_at:`).

---

### Constat 3 — [BLOQUANT] Écrasement d'une sélection pré-match perdante par décalage d'emplacement (`selection-1`) lors d'une modification `v2` dans `pre_match_contributions()`, et validation de combinés illégitimes dans `combined_legs_proven()`
- **Fichier:ligne** : `src/robin/source_observatory/ranking.py:38-64`, `src/robin/source_observatory/service.py:177-201`, `src/robin/source_observatory/extractor.py:305-321`
- **Scénario concret** :
  1. **Écrasement d'une sélection perdante sur un même match lors d'une suppression de ligne en `v2` (`ranking.py:38-64`)** :
     - `extract_contributions()` (`extractor.py:305, 321`) attribue `selection_key = f'selection-{slot}'` selon l'ordre d'apparition dans le texte (`selection-1`, `selection-2`, ...).
     - En `v1` à `18h00`, un auteur publie deux pronostics sur le même match `m1` :
       - `c1_v1` (`selection_key='selection-1'`, `marche='1N2'`, `selection='away'`, `cote_declaree=Decimal('2.4')`) → perdant (`-1.0`) ;
       - `c2_v1` (`selection_key='selection-2'`, `marche='total'`, `selection='over'`, `ligne=Decimal('1.5')`, `cote_declaree=Decimal('1.5')`) → gagnant (`+0.5`).
     - En `v2` à `18h30` (avant le coup d'envoi de `20h00`), l'auteur supprime la première phrase (`1N2 away`). Le second pronostic (`total over 1.5`) devient alors la première sélection extraite de `v2` (`c1_v2`, `selection_key='selection-1'`, `match_id='m1'`, `marche='total'`, `selection='over'`, `ligne=Decimal('1.5')`, `cote_declaree=Decimal('1.5')`).
     - Dans `pre_match_contributions()` (`ranking.py:59-63`), `c1_v2` partage le `slot = ('p1', 'm1', 'selection-1')` avec `c1_v1`, et `preserves_evidence(c1_v1, c1_v2)` renvoie `True` (car il ne vérifie pas si `c1_v2` est en réalité la sélection déjà présente en `selection-2` dans `v1` ni si un marché de `v1` a disparu).
     - `latest[('p1', 'm1', 'selection-1')]` écrase `c1_v1` par `c1_v2` : `pre_match_contributions()` retourne `(c1_v2, c2_v1)` (deux fois `over 1.5`), **effaçant la perte `-1.0` de `c1_v1`** (le bilan passe de `ROI = -0.25` à `ROI = +0.50`).
  2. **Validation d'un combiné mono-match (deux fois la même sélection) ou dont la version `v_combo` est post-match / remplacée dans `combined_legs_proven()` (`service.py:177-201`)** :
     - `combined_legs_proven()` (`service.py:186-200`) vérifie `c in pre_match_contributions(items, m.match_usable_at)` pour chaque jambe `c`, mais ne vérifie jamais que `contribution` (le combiné lui-même) appartient à `pre_match_contributions(items, m.match_usable_at)` lorsque sa `PublicationVersion` est présente dans `items`.
     - De plus, `combined_legs_proven()` vérifie uniquement `len({leg.contribution_id for leg in result.legs}) >= 2` sans vérifier que les jambes portent sur des matchs distincts (ou au moins des marchés/sélections distincts) : deux contributions `c1` et `c2` du même auteur répétant le même pari simple `home @ 2.0` sur le même match `m1` valident un combiné gagnant à cote `4.0` (`+3.0` unités de profit).
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/ranking.py:38-64` (et `172-178`), indexer le slot par `(entity.publication_id, entity.match_id, entity.marche, entity.selection_key)` (ou refuser dans `pre_match_contributions` qu'une contribution de `v2` dont le quadruplet `(marche, selection, ligne, periode)` existait déjà sous un autre `selection_key` dans `v1` n'écrase un slot de `v1` ayant un quadruplet différent).
  - Dans `src/robin/source_observatory/service.py:184-200`, exiger que les jambes d'un combiné portent sur des `match_id` distincts (`len({ms[leg.contribution_id].match_id for leg in result.legs if leg.contribution_id in ms}) == len(result.legs)`) et que, si `contribution.version_id` est dans `items`, `contribution in pre_match_contributions(items, m.match_usable_at)` pour chaque jambe `m`.

---

### Constat 4 — [BLOQUANT] Cote de jambe individuelle imputée au combiné entier dans `extractor.py`, incompatibilité entre `extractor.py` et `settlement.py` sur les sélections par nom d'équipe, et règlement sans règle accepté dans `store.py`
- **Fichier:ligne** : `src/robin/source_observatory/extractor.py:91-122`, `src/robin/source_observatory/extractor.py:294-298`, `src/robin/source_observatory/settlement.py:49-85`, `src/robin/source_observatory/models.py:370-399`, `src/robin/source_observatory/store.py:234-253`
- **Scénario concret** :
  1. **Cote d'une seule jambe attribuée comme `cote_declaree` du combiné entier (`extractor.py:294-298`)** :
     - Dans `extract_contributions()`, la règle des lignes 294-298 :
       ```python
       if ('&' in clause and not re.search(r'\bcombine\b', clause) and
               not any(_odds(leg)[0] for leg in legs[:-1])):
           odds, odds_conflict = _odds(clause)
       ```
       ne vérifie l'absence de cote par jambe que sur `legs[:-1]` (toutes les jambes sauf la dernière).
     - Sur `"Mon pari : victoire de Dijon & plus de 1,5 buts @1.42"` (où la 1re jambe n'a pas de cote et seule la 2e jambe porte `@1.42`), `not any(_odds(leg)[0] for leg in legs[:-1])` est `True` : `extract_contributions()` attribue `cote_declaree = '1.42'` et `categorie = 'selection_avec_cote'` au combiné `'dijon & over 1.5'`, violant le critère gelé `C3.2` (*« Cotes déclarées inventées ou reconstruites : 0 »*).
  2. **Rupture de la chaîne `contribution -> reglement` entre `extractor.py` et `settlement.py` (`extractor.py:95, 101, 121`, `service.py:32-71`, `settlement.py:56, 68, 80`)** :
     - Pour tout pronostic en français nommant une équipe (`"Mon pronostic : victoire de Toulouse cote 1.85"`, `"Toulouse gagne"`, `"Handicap Toulouse -1,5"`), `extractor.py` émet `Contribution.selection = 'toulouse'` (et `periode = 'non_precisee'`).
     - Ensuite, `resolve_match_market()` (`service.py:32-71`) résout l'identité fournisseur de la sélection dans `MatchMarket.selection_id` (par ex. `'home'` ou `'away'`).
     - Mais `settle(contribution, match, ...)` (`settlement.py:56, 68, 80`) lit uniquement `selection = contribution.selection` (`'toulouse'`) et ignore `match.selection_id` : comme `'toulouse' not in ('home', 'away', 'draw')`, **`settle()` renvoie systématiquement `outcome = 'en_attente'` pour 100 % des contributions `1N2`/`handicap`/`qualification` extraites avec un nom d'équipe**.
  3. **Règlement `'gagne'`/`'perdu'` sans règle documentée (`reglement=None`) ou sur `MatchMarket` non résolu accepté par `models.py`, `settlement.py` et `store.py` (`models.py:370-399`, `settlement.py:49-85`, `store.py:234-253`)** :
     - `settle()` (`settlement.py:49-85`) calcule un résultat `'gagne'`/`'perdu'` même lorsque `match.statut == 'non_resolu'` ou `observed_at < match.match_usable_at`.
     - `models.Result` (`models.py:370-399`) et `AppendOnlyStore._validate_lineage` (`store.py:234-253`) acceptent d'enregistrer dans le journal `Result(..., outcome='gagne', reglement=None)` sans aucune `SettlementRule`, en violation du critère gelé `C5.1` (*« 0 règlement sans règle »*).
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/extractor.py:294-298`, n'accepter une cote sur une conjonction `&` sans mot-clé `cote totale/globale` que lorsque la conjonction entière est délimitée (guillemets ou parenthèses) avant la cote (ex. `r'["»)]\s*(?:\(\s*)?(?:cote\s*(?:a\s+)?|@\s*)' + _decimal_odds`), afin qu'une cote attachée à `legs[-1]` ne devienne jamais la cote du combiné.
  - Dans `src/robin/source_observatory/settlement.py:54-84`, renvoyer `'en_attente'` si `match.statut != 'resolu'`, lever `ValueError('result observation precedes kickoff')` si `match.match_usable_at is not None and observed_at < match.match_usable_at`, et résoudre la sélection avec `selection = match.selection_id if match.selection_id in ('home', 'away', 'draw', 'over', 'under') else contribution.selection`.
  - Dans `src/robin/source_observatory/models.py:385-395` (et `store.py:234-243`), exiger `if self.outcome != 'en_attente' and self.reglement is None: raise ValueError('settled result requires a documented settlement rule')`.

---

### Constat 5 — [BLOQUANT] Couverture de visites faussée dans `visit_coverage()`, perte de `<media:description>` sur les flux Atom YouTube, et plafond structurel à 35,9 % (14/39 sources) sur le plan pilote `visit_plan_20261031.json`
- **Fichier:ligne** : `src/robin/source_observatory/collector.py:190-214`, `src/robin/source_observatory/collector.py:328-341`, `src/robin/source_observatory/collector.py:432-440`, `src/robin/source_observatory/ranking.py:281-300`, `data/source_observatory/visit_plan_20261031.json`
- **Scénario concret** :
  1. **Injection des visites futures non échues dans `store` faussant `visit_coverage()` (`collector.py:432-440`, `ranking.py:281-300`)** :
     - Dès le premier lancement de `collect()` au premier créneau (`2026-10-28T23:00:00+00:00`), la boucle `collector.py:433-439` ajoute immédiatement les **819 entités `Visit`** de `plan['visits']` (jusqu'au `2026-11-01T19:44:00+00:00`) dans `store` avec `succeeded=False, completed_at=None`, alors que seules les 39 visites du premier créneau sont échues (`planned <= observed`, ligne 459).
     - En conséquence, `visit_coverage(store.entities())` (`ranking.py:295-300`) — qui prend au dénominateur toutes les `Visit` présentes dans `store` sans filtrer sur `planned_at <= at` ni sur l'existence d'un `VisitReceipt` — divise les réussites du premier créneau par 819 (soit au plus `39 / 819 = 4,76 %` même si 100 % des visites échues ont réussi).
  2. **Impossibilité structurelle d'atteindre les critères gelés `C1.1` (≥ 80 %) et `C1.2` (≥ 25 sources visitées) avec `_endpoint()` sur `visit_plan_20261031.json` (`collector.py:190-214`)** :
     - Sur les 39 sources incluses dans `data/source_observatory/visit_plan_20261031.json`, `_endpoint(source)` renvoie `(None, reason)` (échec immédiat sans requête HTTP) pour **25 sources sur 39** :
       - 14 sources d'état `'manuel'` ;
       - 4 sources `'a_construire'` à `CGU : inconnu` (`SRC_004`, `SRC_020`, `SRC_035`, `SRC_042`) ;
       - 2 sources `'a_construire'` refusées pour CGU (`SRC_007`, `SRC_021`) ;
       - 1 source `'a_construire'` (`SRC_041`, Forum MadeInLens) refusée par **faux positif** de la ligne 207-208 : son champ `cgu_connues` contient `"sans interdiction d'indexation"`, qui n'est pas retiré par `r"(?:pas de|pas d'|aucune? )"` et déclenche à tort `'cgu_collecte_automatisee_refusee'` ;
       - 4 chaînes YouTube `'a_construire'` (`SRC_023`, `SRC_027`, `SRC_031`, `SRC_032`), dont `SRC_023` et `SRC_027` disposent pourtant d'une URL officielle `/feeds/videos.xml?channel_id=...` dans `mode_acces`, mais sont rejetées parce que `collector.py:204` exige la sous-chaîne `r'flux (atom public|rss public|officiels)'` dans `cgu_connues` alors que `SRC_023` et `SRC_027` y mentionnent `"API officielle"` (la mention `"flux Atom public"` figurant dans `limites` / `mode_acces`).
     - Même avec 100 % de disponibilité réseau, seules **14 sources sur 39** peuvent être interrogées, plafonnant la couverture globale à `14 / 39 = 35,9 %` (294 / 819 visites).
  3. **Omission de `<media:description>` sur tous les flux Atom YouTube et échec sur tag vide (`collector.py:331-338`)** :
     - Dans `parse_publications()`, `fields = {_local(e.tag): ''.join(e.itertext()) for e in entry}` (`collector.py:331`) n'inspecte que les enfants directs de `<entry>`. Or, dans les flux Atom publics de YouTube (`/feeds/videos.xml`), la description de la vidéo est imbriquée dans `<media:group><media:description>...</media:description></media:group>`. `fields.get('description')` est donc toujours `None` et seul `<title>` est collecté.
     - En outre, la ligne 338 teste `if fields.get(key)` sans `.strip()` : si un flux RSS contient `<content:encoded>   </content:encoded>` (espaces) et un `<description>` non vide, `text` prend la valeur `"   "` et la ligne 352 (`if not post.text.strip(): raise ValueError(...)`) fait échouer toute la visite.
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/collector.py:203-207`, autoriser un `youtube_feed` officiel dès que `/feeds/videos.xml?channel_id=` est présent dans `source.access` et que `terms` mentionne `r'flux (atom public|rss public|officiels)|api officielle'`, et inclure `sans` dans les négations de la ligne 207.
  - Dans `src/robin/source_observatory/collector.py:331-338`, extraire aussi le texte de `media:description` (`for sub in entry.iter()` pour `description` si absent des enfants directs) et filtrer par `if fields.get(key, '').strip()`.
  - Dans `src/robin/source_observatory/collector.py:433-460`, n'ajouter l'entité `Visit` au journal que lorsque la visite est échue (`planned <= observed`), ou filtrer `effective_visits()` (`src/robin/source_observatory/ranking.py:281-293`) sur `v.planned_at <= at`.

---

### Constat 6 — [MAJEUR] Corruption irréversible du journal append-only lorsque `store.append()` écrit un horodatage non décodable par `_timestamp()`, perte du fuseau `Europe/Paris` sur les `Visit` du plan, et écritures partielles lors d'une erreur dans `collect()`
- **Fichier:ligne** : `src/robin/source_observatory/store.py:85-91`, `src/robin/source_observatory/store.py:109-126`, `src/robin/source_observatory/store.py:359-380`, `src/robin/source_observatory/collector.py:164-171`, `src/robin/source_observatory/collector.py:497-503`, `tests/source_observatory/test_collector.py:314-325`
- **Scénario concret** :
  1. **Écriture sur disque avant vérification de décodage dans `AppendOnlyStore.append()` (`store.py:359-380`)** :
     - `append()` sérialise `body['data'] = _wire(entity)` et écrit immédiatement la ligne dans le fichier JSONL append-only (`self.path.open('ab')`) sans vérifier que `_decode(type(entity).__name__, body['data'])` réussit.
     - Si une entité contient un `datetime` dont `tzinfo` est un décalage fixe portant un nom de zone IANA à un offset différent (ex. `datetime(2026, 7, 1, 12, 0, tzinfo=timezone(timedelta(hours=1), 'Europe/Paris'))` ou une date RFC 2822 avec abréviation de fuseau incompatible avec `ZoneInfo`), ou dont `tzname()` renvoie `None`, `_wire()` réussit et écrit l'enregistrement dans `collection.jsonl`, puis tout appel ultérieur à `store.read()` ou `store.append()` lève `IntegrityError('invalid journal: origin timezone offset mismatch')`, bloquant définitivement le journal.
  2. **Écritures partielles dans le journal lors d'un échec sur un second post dans `collect()` (`collector.py:497-503`)** :
     - Dans `collect()`, `publication_ids = tuple(_persist_post(store, source, p, observed, raw_root) for p in selected)` écrit chaque `Publication` et `PublicationVersion` au fil de l'eau dans `store`. Si `selected` contient `[p1, p2]`, que `p1` est persisté puis que `p2` lève `ValueError` ou `OSError`, le bloc `except` (`collector.py:500-503`) journalise `VisitReceipt(..., status='echec', publication_ids=(), reason='lecture_publique_echouee')` alors que `p1` et sa version sont déjà inscrits dans le journal.
  3. **Perte du fuseau d'origine `Europe/Paris` (`+01:00`) dans `build_plan()`/`collect()` et absence de vérification de `kickoffs_20261031.json` (`collector.py:164-171, 434-439`, `test_collector.py:314-325`)** :
     - Les 7 coups d'envoi de `data/source_observatory/kickoffs_20261031.json` sont en `Europe/Paris` (`+01:00`, après le passage à l'heure d'hiver du 25/10/2026) et leurs instants UTC dans `data/source_observatory/visit_plan_20261031.json` (`16:15Z`, `19:45Z`, `14:00Z`) sont exacts. Toutefois, `build_plan()` les sérialise en `+00:00` via `instant_text()`, de sorte que `collect()` enregistre toutes les entités `Visit` dans le store avec `"origin_timezone": "UTC", "origin_offset_seconds": 0` au lieu de `"Europe/Paris"` (`+01:00`). Par ailleurs, `test_real_plan_matches_registry_and_requested_date_scope` (`test_collector.py:314-325`) relit `p['fixtures']` depuis `visit_plan_20261031.json` sans jamais charger `data/source_observatory/kickoffs_20261031.json`.
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/store.py:366-369`, valider `if _decode(type(entity).__name__, body['data']) != entity: raise ValueError('noncanonical or unroundtrippable metadata')` **avant** d'ouvrir `self.path.open('ab')`.
  - Dans `src/robin/source_observatory/collector.py:123-125`, normaliser en `UTC` toute date issue de `parsedate_to_datetime` dont le `tzinfo` n'est pas un `ZoneInfo` valide, et valider tous les posts de `selected` avant d'appeler `store.append()`.
  - Dans `tests/source_observatory/test_collector.py:314-325`, charger les fixtures depuis `data/source_observatory/kickoffs_20261031.json` et vérifier que `visit_plan_20261031.json` correspond exactement à `build_plan()` construit depuis `kickoffs_20261031.json`.

---

### Constat 7 — [MINEUR] Absence de garde `match.contribution_usable_at >= contribution.observed_at` dans `service.evaluate()` et acceptation de `float` pour un champ `integer` dans le validateur de secours
- **Fichier:ligne** : `src/robin/source_observatory/service.py:98`, `src/robin/source_observatory/service.py:125-131`, `src/robin/source_observatory/schema_validation.py:43`
- **Scénario concret** :
  1. Lorsqu'on appelle directement `service.evaluate(contribution, match, result, odds_basis=...)` hors `AppendOnlyStore`, `evaluate()` vérifie `match.pre_match_valid` et `contribution.observed_at < match.match_usable_at`, mais pas `match.contribution_usable_at >= contribution.observed_at`. Si `contribution` est une `'information_factuelle'` observée à `19h59` sur une version `v` (`usable_at = 18h00`) et que `match` est construit avec `contribution_usable_at = 18h00` et `match_usable_at = 20h00`, `anteriority_seconds` vaut `7200` secondes au lieu de `60` secondes.
  2. Dans `src/robin/source_observatory/schema_validation.py:43`, le validateur sans dépendance accepte `type(value) is float and value.is_integer()` (ex. `start = 0.0`) pour le type JSON Schema `'integer'`, alors que `EvidenceExcerpt.__post_init__` (`models.py:142`) et `store._timestamp` (`store.py:114`) exigent `type(value) is int`.
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/service.py:98`, ajouter `or match.contribution_usable_at < contribution.observed_at` à la condition `'invalide_pre_match'`.
  - Dans `src/robin/source_observatory/schema_validation.py:43`, remplacer `'integer': type(value) is int or (type(value) is float and value.is_integer())` par `'integer': type(value) is int`.

---

### Constat 8 — [HORS_PILOTE] Contournement du blocage sur retrait (`Withdrawal`) par omission de `MatchMarket` dans `rankings()` et absence de validation des combinés dans `cohort_state()`
- **Fichier:ligne** : `src/robin/source_observatory/ranking.py:185-199`, `src/robin/source_observatory/ranking.py:313-334`
- **Scénario concret** :
  1. Dans `rankings()` (`src/robin/source_observatory/ranking.py:185-192`), la vérification qui empêche d'omettre le résultat d'une sélection retirée (`Withdrawal`) ou rétrogradée itère uniquement sur `for m in matches.values():`. Si un auteur retire sa sélection perdante `loser` via `Withdrawal('w', 'c1', ...)` et que l'appelant passe `[version(), loser, winner, Withdrawal('w', 'c1', ...), *evaluated(winner, match_id='m2')]` **sans fournir `MatchMarket(loser)`**, `loser` n'apparaît pas dans `matches.values()` : aucune exception n'est levée et `rankings()` retourne `roi = Decimal('1.4')` en ignorant la perte retirée.
  2. Dans `cohort_state()` (`src/robin/source_observatory/ranking.py:316-325`), la boucle qui compte les matchs indépendants `matches` ne vérifie pas `combined_legs_proven()` sur les évaluations de combinés et filtre sur `start <= c.observed_at < end` sans vérifier `start <= versions[c.version_id].usable_at < end`.
- **Correctif minimal** :
  - Dans `src/robin/source_observatory/ranking.py:185-192`, vérifier que toute contribution pré-match d'un auteur de `affected_authors` possède son `MatchMarket` dans `matches` lorsque `at` dépasse les coups d'envoi observés (ou lever `ValueError('retained contribution requires match market, result and evaluation')`), et appliquer `combined_legs_proven()` dans `cohort_state()`.

---

## 4. Verdict final pour le périmètre pilote

**Verdict : `REFUSE`**

Même en écartant du verdict pilote le constat sur `rankings()`/cohortes (**Constat 8 — `HORS_PILOTE`**), le périmètre pilote (`collecte -> contribution -> horodatages -> reglement`) comporte **5 constats bloquants** et **1 constat majeur** qui empêchent le lancement conforme du pilote :
1. le collecteur peut contourner un `Disallow` adressé à `RobinSourceObservatory/1.0` et une clause CGU d'interdiction précédée d'une négation dans la même phrase (**Constat 1**) ;
2. la collecte HTML sans permalien explicite fusionne des articles successifs en une fausse version corrigée en leur imputant le `first_observed_by_robin_at` initial, `_Articles` écrase `announced_by_platform_at` par la dernière balise `<time>`, et `store.py` permet d'antidater `first_observed_by_robin_at` (sur une `v1` avec `modification_observed_at`) ainsi que `cote_observee_at` (sur une `v2` modifiée) (**Constat 2**) ;
3. la suppression pré-match en `v2` d'une sélection perdante `selection-1` sur un match ayant une seconde sélection `selection-2` écrase la sélection perdante dans `pre_match_contributions()`, et `combined_legs_proven()` accepte des combinés mono-match (**Constat 3**) ;
4. `extractor.py` impute la cote de la dernière jambe comme `cote_declaree` du combiné entier sur les conjonctions `&`, `settlement.py` laisse en `'en_attente'` toutes les sélections nommant une équipe faute de lire `match.selection_id`, et `store.py` accepte des `Result` réglés sans `SettlementRule` (**Constat 4**) ;
5. `collector.py` injecte dès le premier créneau les 819 visites futures dans `store` (faussant `visit_coverage()`), ignore `<media:description>` sur YouTube Atom, et bloque 25 des 39 sources du plan gelé (plafond théorique à `35,9 %` et 14 sources contre `>= 80 %` et `>= 25` sources exigés par `C1.1`/`C1.2`) (**Constat 5**).
