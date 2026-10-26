# Notes de vérification CGU & `robots.txt` — Mission T2 (`pilot_sources.csv`)

Date de vérification : `2026-10-25`  
Périmètre : 42 sources publiques de pronostics Ligue 1 (24 médias/sites/tipsters connus et 18 petits auteurs/inconnus).  
Règle appliquée : lecture directe uniquement, sans contournement, sans création de compte. Lorsqu'une page de CGU est absente (HTTP 404) ou inaccessible sans contournement (HTTP 403), l'état CGU est explicitement noté **`inconnu`** et seul le fichier `robots.txt` effectivement lu est rapporté.

---

## SRC_001 — RueDesJoueurs (RDJ) - Pronostics Ligue 1
- **Adresse vérifiée** : `https://www.ruedesjoueurs.com/pronostics/ligue-1-937873.html` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.ruedesjoueurs.com/conditions-dutilisation.html` (HTTP 200)
  - `https://www.ruedesjoueurs.com/mentions-legales.html` (HTTP 200)
  - `https://www.ruedesjoueurs.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **CGU** : Les conditions d'utilisation précisent que les contenus du site sont la propriété de la société **LUDIO MEDIA** et de ses partenaires, protégés par les lois relatives à la propriété intellectuelle, et n'autorisent *« que l'unique affichage lors de la navigation sur le Présent Site ou Forum »*.
  - **`robots.txt`** : Règle Joomla standard (`User-agent: *`), bloquant uniquement les dossiers techniques (`/administrator/`, `/bin/`, `/cache/`, `/cli/`, `/components/`, `/includes/`, `/installation/`, `/language/`, `/layouts/`, `/libraries/`, `/logs/`, `/modules/`, `/plugins/`, `/tmp/`). Les pages `/pronostics/` ne sont pas bloquées par `robots.txt`.
- **Statut connecteur retenu** : `manuel` (restriction contractuelle explicite au seul affichage de navigation humaine).

---

## SRC_002 — Coteur - Pronostics Ligue 1
- **Adresse vérifiée** : `https://www.coteur.com/pronostic/foot/ligue-1` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.coteur.com/mention-legale` (HTTP 200)
  - `https://www.coteur.com/privacy-statement` (HTTP 200)
  - `https://www.coteur.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Mentions légales** : La page `mention-legale` traite de l'éditeur, de l'hébergement, des données personnelles et des liens hypertextes, sans clause spécifique interdisant l'indexation automatisée des pages publiques.
  - **`robots.txt`** : Pour `User-agent: *`, interdit `/admin/`, `/ajax/`, `/menu_`, `/bloc/`, `/chat/`, `/user/`, `/concours-prono-classement`, `/bookmaker-redirect`, `/cote-direct`. Le chemin `/pronostic/foot/ligue-1` est autorisé.
- **Statut connecteur retenu** : `a_construire` (en excluant tout appel vers `/ajax/` interdit par `robots.txt`).

---

## SRC_003 — Pronosoft - Forum & Pronostics Ligue 1
- **Adresse vérifiée** : `https://www.pronosoft.com/forums/viewforum.php?f=79` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.pronosoft.com/fr/contct/mentions_legales.htm` (HTTP 200)
  - `https://www.pronosoft.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Mentions légales** : Clause « Reproduction » : *« Les contenus du site sont la propriété exclusive de Pronosoft. Aucune copie ou reproduction n'est autorisée sans l'accord de Pronosoft. »*
  - **`robots.txt`** : Bloque intégralement (`Disallow: /`) 12 robots d'analyse/crawl tiers (`AhrefsBot`, `BLEXBot`, `SiteAuditBot`, `SemrushBot-BA`, `SemrushBot-SI`, `SemrushBot-SWA`, `SemrushBot-CT`, `SemrushBot-BM`, `SplitSignalBot`, `MJ12bot`, `Waiterr`, `DataForSeoBot`). Pour `User-agent: *`, bloque `/forums/viewonline.php`, `/forums/search.php`, `/forums/memberlist.php`, `/forums/ucp.php`, `/forums/posting.php`.
- **Statut connecteur retenu** : `manuel` (reproduction interdite sans accord de Pronosoft).

---

## SRC_004 — ProTipster France - Pronostics Ligue 1
- **Adresse vérifiée** : `https://www.protipster.fr/pronostics/foot/france/ligue-1` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.protipster.fr/robots.txt` (HTTP 200)
  - `https://www.protipster.fr/conditions-generales` (HTTP 404) et `https://www.protipster.com/terms-of-use` (HTTP 404)
- **Constat réel** :
  - **CGU** : **`inconnu`** (aucun lien CGU fonctionnel dans le DOM public ; les URLs usuelles retournent HTTP 404).
  - **`robots.txt`** : `User-agent: *` avec une seule règle `Disallow: /affiliate/`. Toutes les pages de pronostics `/pronostics/foot/france/ligue-1` sont autorisées au crawl.
- **Statut connecteur retenu** : `a_construire` (sous réserve de vérification manuelle ultérieure d'éventuelles CGU).

---

## SRC_005 — Tipstop - Consensus Tipsters Football
- **Adresse vérifiée** : `https://tipstop.co/fr` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://tipstop.co/fr/legal-notice` (HTTP 200)
  - `https://tipstop.co/fr/cgu` (HTTP 200)
  - `https://tipstop.co/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Mentions légales & CGU** : *« L'ensemble des éléments composant le site et l'application TIPSTOP, notamment : textes, logos, graphismes, interfaces, bases de données, algorithmes, marques, sont protégés par le droit de la propriété intellectuelle et sont la propriété exclusive de TIPSTOP SAS ou de ses partenaires. Toute reproduction, représentation, modification, adaptation ou exploitation, totale ou partielle, sans autorisation écrite préalable est strictement interdite. »*
  - **`robots.txt`** : Autorise explicitement `User-Agent: *` (`Allow: /`) ainsi que `GPTBot`, `ChatGPT-User`, `Google-Extended`, `ClaudeBot`, `PerplexityBot`, mais interdit `Disallow: /api/`, `Disallow: /payment/`, `Disallow: /_next/`, `Disallow: /mobile/web/`, `Disallow: /data/`.
- **Statut connecteur retenu** : `manuel` (protection explicite des bases de données et interdiction de `/api/` et `/data/`).

---

## SRC_006 — PenseBet - Pronostics Ligue 1
- **Adresse vérifiée** : `https://pensebet.com/categorie/previews-et-pronostics/pronostics-foot/pronostics-ligue-1/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://pensebet.com/terms` (HTTP 200)
  - `https://pensebet.com/robots.txt` (HTTP 200)
  - Flux RSS vérifié : `https://pensebet.com/feed/` (HTTP 200)
- **Constat réel** :
  - **CGU** : Décrit le fonctionnement du site d'information, du chatbot IA et du forum (respect des droits de propriété intellectuelle), sans clause interdisant la consommation du flux RSS public WordPress.
  - **`robots.txt`** : `User-agent: *` avec uniquement `Disallow: /wp-admin/` et `Disallow: /wp-content/uploads/complianz/`.
- **Statut connecteur retenu** : `a_construire` (via le flux RSS public `https://pensebet.com/feed/` ou les pages publiques de la catégorie Ligue 1).

---

## SRC_007 — MediaPronos (Site Web)
- **Adresse vérifiée** : `https://mediapronos.com/` et `https://mediapronos.com/ligue-1-pronostics-et-enjeux-de-la-derniere-journee-du-17-mai/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://mediapronos.com/conditions-generales-utilisation/` (HTTP 200)
  - `https://mediapronos.com/mentions-legales/` (HTTP 200)
  - `https://mediapronos.com/robots.txt` (HTTP 200)
  - Flux RSS vérifié : `https://mediapronos.com/feed/` (HTTP 200)
- **Constat réel** :
  - **CGU** : *« Propriété intellectuelle : Tous les contenus sont protégés. Toute reproduction sans autorisation est interdite. »*
  - **`robots.txt`** : `User-agent: *` avec `Disallow:` vide et déclaration du sitemap `https://mediapronos.com/sitemap_index.xml`.
- **Statut connecteur retenu** : `a_construire` (collecte de veille via le flux RSS public `https://mediapronos.com/feed/` sans reproduction intégrale des articles ni contournement de l'espace Gold).

---

## SRC_008 — DailySportPick - Ligue 1 Tips
- **Adresse vérifiée** : `https://dailysportpick.com/fr/tips/ligue-1-tips/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://dailysportpick.com/fr/disclaimer/` (HTTP 200)
  - `https://dailysportpick.com/fr/legal-notice/` (HTTP 200)
  - `https://dailysportpick.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Disclaimer & Legal Notice** : *« Propriété intellectuelle : Tout le contenu de ce site web, y compris les cartes de pronostic, les analyses, le texte et les graphiques, est la propriété de Daily Sport Pick [Exploité par Mave Media, KvK 01139129]. »*
  - **`robots.txt`** : `User-agent: *` (`Allow: /`), et autorise explicitement les agents IA (`User-agent: GPTBot Allow: /`, `User-agent: ClaudeBot Allow: /`, `User-agent: PerplexityBot Allow: /`, `User-agent: Google-Extended Allow: /`, `User-agent: OAI-SearchBot Allow: /`), en bloquant uniquement les paramètres de tri/filtre `/*?st=`, `/*?lg=`, `/*?pg=`.
- **Statut connecteur retenu** : `a_construire` (ouverture explicite aux robots dans `robots.txt`).

---

## SRC_009 — Zone-Supporter (ex-ClubPronostics)
- **Adresse vérifiée** : `https://www.zone-supporter.com/tipsters-foot/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.zone-supporter.com/mentions-legales/` (HTTP 200)
  - `https://www.zone-supporter.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Mentions légales** : *« L'intégralité du contenu du site Internet, son contenu, son organisation, sont la propriété exclusive de son propriétaire [BARDY David] et sont protégés par la législation française relative à la propriété intellectuelle. »* Mentionne également la pratique de la courte citation d'analyses d'autres pronostiqueurs.
  - **`robots.txt`** : `User-agent: *` avec `Disallow:` vide (aucune restriction).
- **Statut connecteur retenu** : `a_construire` (dans le respect du droit de courte citation / métadonnées).

---

## SRC_010 — Les-Transferts - Rubrique Paris Sportifs
- **Adresse vérifiée** : `https://www.les-transferts.com/paris-sportifs/page/5/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.les-transferts.com/notice-legale/` (HTTP 200)
  - `https://www.les-transferts.com/robots.txt` (HTTP 200)
  - Flux RSS vérifié : `https://www.les-transferts.com/paris-sportifs/feed/` (HTTP 200)
- **Constat réel** :
  - **Notice légale** : Mentionne l'éditeur et *« © Transfert Foot Mercato 2026. Tous droits réservés »*, sans clause restrictive sur les flux RSS ou robots.
  - **`robots.txt`** : `User-agent: *` bloque uniquement `/wp-admin`, `/27185805/LT*`, `/go-*`, `/?d`.
- **Statut connecteur retenu** : `a_construire` (flux RSS dédié `https://www.les-transferts.com/paris-sportifs/feed/` opérationnel).

---

## SRC_011 — OneFootball - Pronostics & Analyses
- **Adresse vérifiée** : `https://onefootball.com/fr/paris-sportif/pronostics` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://static.onefootball.com/legal/imprint/fr` (HTTP 200)
  - `https://onefootball.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Mentions légales** : Mentions d'identification de OneFootball GmbH (Berlin) et crédits photos/données, sans clause anti-indexation sur cette page.
  - **`robots.txt`** : `User-agent: *` bloque `/admin`, `/magazine`, `/network`, `/wordpress`, `/cms`, mais autorise `/fr/paris-sportif/pronostics`.
- **Statut connecteur retenu** : `a_construire`.

---

## SRC_012 — MatchEnDirect - Ligue 1 & Pronos Communauté
- **Adresse vérifiée** : `https://www.matchendirect.fr/france/ligue-1/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.matchendirect.fr/robots.txt` (HTTP 200)
  - `https://www.matchendirect.fr/mentions-legales.html` (HTTP 404) et `https://www.matchendirect.fr/cgu.html` (HTTP 404)
- **Constat réel** :
  - **CGU** : **`inconnu`** (aucun lien CGU fonctionnel trouvé sur le site ; les URLs de mentions légales testées renvoient HTTP 404).
  - **`robots.txt`** : Fichier très restrictif contenant **119 blocs `User-agent`** bannissant nominativement des dizaines de robots et scrapers tiers, et interdisant `/public/` ainsi que divers motifs d'URLs.
- **Statut connecteur retenu** : `manuel` (politique anti-bots très stricte dans `robots.txt` et absence de CGU vérifiables).

---

## SRC_013 — FootMercato - Ligue 1
- **Adresse vérifiée** : `https://www.footmercato.net/france/ligue-1/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.footmercato.net/contact-mentions-legales-flux-rss` (HTTP 200)
  - `https://www.footmercato.net/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Mentions légales** : *« La structure générale, ainsi que les textes et images composant ce site sont la propriété de la société Adversport France. Toute représentation totale ou partielle de ce site ou d'un ou plusieurs de ces composants, par quelque procédé que ce soit, sans autorisation expresse de la société Adversport France, est interdite et constituerait une contrefaçon sanctionnée par les articles L.335-2 et suivants du Code de la propriété intellectuelle. »*
  - **`robots.txt`** : `User-agent: *` avec `Disallow:` vide.
- **Statut connecteur retenu** : `manuel` (interdiction expresse de toute représentation partielle ou totale par quelque procédé que ce soit sans autorisation).

---

## SRC_014 — OLBG - French Ligue 1 Betting Tips
- **Adresse vérifiée** : `https://www.olbg.com/betting-tips/Football/French_Ligue_1/20` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.olbg.com/robots.txt` (HTTP 200)
  - `https://www.olbg.com/terms` (HTTP 404) et `https://www.olbg.com/terms-and-conditions` (HTTP 404)
- **Constat réel** :
  - **CGU** : **`inconnu`** (les pages `/terms` et `/terms-and-conditions` renvoient HTTP 404).
  - **`robots.txt`** : Contient 70 blocs `User-agent` (bloquant de nombreux crawlers tiers) et interdit `/tipster/`, `/premium/`, `/cache/`, `/sports/`, `/tips/hot`. La route `/betting-tips/Football/French_Ligue_1/20` reste accessible.
- **Statut connecteur retenu** : `manuel` (CGU non vérifiables en 404 et restrictions nombreuses dans `robots.txt`).

---

## SRC_015 — Betrush - France Ligue 1 Picks
- **Adresse vérifiée** : `https://www.betrush.com/pick,france___ligue_1,93.html` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.betrush.com/tcdp.html` (HTTP 200)
  - `https://www.betrush.com/robots.txt` (HTTP 404)
- **Constat réel** :
  - **Terms and Conditions** : Article 4 : *« Copying and redistribution of any materials contained on the site (intellectual property of Betrush.com and its respective authors) is strictly forbidden, unless a written permission is granted. »*
  - **`robots.txt`** : HTTP 404 (pas de fichier `robots.txt`).
- **Statut connecteur retenu** : `manuel` (interdiction contractuelle stricte de copie sans permission écrite).

---

## SRC_016 — Vitibet - Pronostics Statistiques Ligue 1
- **Adresse vérifiée** : `https://www.vitibet.com/index.php?clanek=quicktips&sekce=fotbal&lang=fr` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.vitibet.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **CGU** : **`inconnu`** (aucune page de conditions générales dédiée sur le site en dehors du bandeau de consentement cookies).
  - **`robots.txt`** : Interdit explicitement (`Disallow: /`) une longue liste de robots d'IA et d'extraction : `SmartViper`, `CCBot`, `Omgilibot`, `Omgili`, `FacebookBot`, `Meta-ExternalAgent`, `Meta-ExternalFetcher`, `Diffbot`, `DuckAssistBot`, `AI2Bot`, `Bytespider`, `ImagesiftBot`, `Kangaroo Bot`, `cohere-ai`, `Timpibot`, `Webzio-Extended`, `YouBot`, `GPTBot`. Autorise `Mediapartners-Google` et `User-agent: *` (hors `/admin/`).
- **Statut connecteur retenu** : `manuel` (opposition explicite aux bots IA et extracteurs de données dans `robots.txt`).

---

## SRC_017 — FreeSuperTips - French Ligue 1 Predictions
- **Adresse vérifiée** : `https://www.freesupertips.com/predictions/french-ligue-1/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.freesupertips.com/terms-conditions/` (HTTP 200)
  - `https://www.freesupertips.com/disclaimer/` (HTTP 200)
  - `https://www.freesupertips.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Terms & Conditions** : *« This website and contents are copyright of Apsley Group International Ltd. Copying and printing are permitted only for personal, non-commercial use unless expressly agreed in writing. »*
  - **`robots.txt`** : `User-agent: *` bloque uniquement `/wp-admin/`, `/login/`, `/ppc-free-bet-archive/`, `/previews/?&date=19`.
- **Statut connecteur retenu** : `manuel` (copie limitée à l'usage personnel non commercial).

---

## SRC_018 — SportsMole - Ligue 1 Previews & Predictions
- **Adresse vérifiée** : `https://www.sportsmole.co.uk/football/ligue-1/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.sportsmole.co.uk/about/information/terms-and-conditions_467.html` (HTTP 200)
  - `https://www.sportsmole.co.uk/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Terms and Conditions** : *« You may use the Site only for personal, private, and non-commercial purposes... Site Content is the property of North Star Network or its content suppliers and is protected by international copyright laws. »*
  - **`robots.txt`** : `User-agent: *` bloque uniquement `*.amp_latest_update_time`, `/fwd/*`, `/go/*`.
- **Statut connecteur retenu** : `manuel` (usage restreint aux fins personnelles et privées par North Star Network).

---

## SRC_019 — SoccerStats - France Ligue 1 Form & Trends
- **Adresse vérifiée** : `https://www.soccerstats.com/latest.asp?league=france` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.soccerstats.com/legal.asp` (HTTP 200)
  - `https://www.soccerstats.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Legal / Usage Terms** : *« Use of the Website is limited to lawful, personal, non-commercial use. You are only entitled to use the Website for lawful purposes, for your own personal, non-commercial use and will not use the Website in breach of our or any third parties' intellectual property rights. »*
  - **`robots.txt`** : `User-agent: *` bloque `/*1000` et les fichiers d'images (`/*.gif$`, `/*.jpg$`, `/*.png$`).
- **Statut connecteur retenu** : `manuel` (usage personnel uniquement).

---

## SRC_020 — Feedinco - French Ligue 1 Predictions
- **Adresse vérifiée** : `https://www.feedinco.com/predictions/french-ligue-1` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.feedinco.com/robots.txt` (HTTP 200)
  - `https://www.feedinco.com/terms` (HTTP 404)
- **Constat réel** :
  - **CGU** : **`inconnu`** (aucun lien CGU sur la page ; `/terms` renvoie HTTP 404).
  - **`robots.txt`** : `User-agent: *` interdit `/info*`, `/increment*`, `/TipsFootball*`, `/TipsTennis*`, `/TipsBasketball*`, `/TipsHockey*`, `/TipsHandball*`, `/TipsVolleyball*`, mais autorise `/predictions/french-ligue-1`.
- **Statut connecteur retenu** : `a_construire` (route `/predictions/french-ligue-1` autorisée par `robots.txt`).

---

## SRC_021 — Statarea - Football Predictions
- **Adresse vérifiée** : `https://www.statarea.com/predictions` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.statarea.com/help/terms` (HTTP 200)
  - `https://www.statarea.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Terms of Service** : Interdit l'usage illicite ou en violation des lois sur le copyright (*« nor may you, in the use of the Service, violate any laws in your jurisdiction (including but not limited to copyright laws) »*), sans clause anti-crawler spécifique.
  - **`robots.txt`** : `User-agent: *` avec `Disallow:` vide (tout le site est ouvert).
- **Statut connecteur retenu** : `a_construire`.

---

## SRC_022 — Reddit - Communauté r/Ligue1
- **Adresse vérifiée** : `https://www.reddit.com/r/Ligue1/.rss` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://redditinc.com/policies/user-agreement` (HTTP 200)
  - `https://redditinc.com/policies/data-api-terms` (HTTP 200)
  - `https://www.reddit.com/robots.txt` (HTTP 403 en requête script non authentifiée)
- **Constat réel** :
  - **User Agreement (Section 7)** : Interdit de *« Access, search, or collect data from the Services by any means (automated or otherwise) except as permitted in these Terms or in a separate agreement with Reddit (we conditionally grant permission to crawl the Services in accordance with the parameters set forth in our robots.txt file, but scraping the Services without Reddit's prior written consent is prohibited) »*.
  - **Data API Terms** : Tout accès automatisé hors navigation humaine doit passer par l'API officielle Reddit Data API sous licence conforme.
- **Statut connecteur retenu** : `manuel` (ou nécessité d'un accès API Reddit officiel approuvé ; scraping interdit).

---

## SRC_023 — Parieurs Foot - Romain (YouTube)
- **Adresse vérifiée** : `https://www.youtube.com/@DebriefPronoFoot` et `https://www.youtube.com/watch?v=1PqW8k7VE6Q` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.youtube.com/t/terms?hl=fr` (HTTP 200)
  - `https://www.youtube.com/robots.txt` (HTTP 200)
  - Flux Atom/RSS vérifié : `https://www.youtube.com/feeds/videos.xml?channel_id=UCfx9qA0LoWgvAKMbXITPbbg` (HTTP 200)
- **Constat réel** :
  - **CGU YouTube** : Interdit d'*« accéder au Service par le biais de procédés automatisés (tels que les robots, botnets ou scrapers) sauf : (a) dans le cas des moteurs de recherche publics, en accord avec le fichier YouTube robots.txt ; ou (b) avec l'autorisation écrite préalable de YouTube »* (ou via YouTube Data API v3 / flux syndiqués officiels).
  - **`robots.txt`** : Bloque `/api/`, `/comment`, `/get_video_info`, mais laisse ouvert le flux officiel `/feeds/videos.xml` et `/oembed`.
- **Statut connecteur retenu** : `a_construire` (collecte des métadonnées vidéos via le flux Atom officiel `/feeds/videos.xml` ou YouTube Data API v3 uniquement, sans scraping HTML).

---

## SRC_024 — SportyTrader - Pronostics Ligue 1
- **Adresse vérifiée** : `https://www.sportytrader.com/fr/pronostics/football/france/ligue-1-73/` (HTTP 404) et `https://www.sportytrader.com/pronostics/football/france/ligue-1-73/` (HTTP 403)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.sportytrader.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **CGU** : **`inconnu`** (toutes les pages HTML du domaine renvoient HTTP 403 Forbidden lors d'une requête HTTP GET standard sans navigateur).
  - **`robots.txt`** : Accessible en HTTP 200. Bloque `ia_archiver` (`Disallow: /`) et, pour `User-agent: *`, interdit `/mobile/`, `/meilleur/`, `/book/`, `/async/`, `/widgets/`, `/*/preview/`, `/check/`, `/link/`.
- **Statut connecteur retenu** : `bloque` (blocage technique HTTP 403 sur les pages publiques sans contournement).

---

## SRC_025 — Objectif Profits - Paris Sportifs Football (YouTube)
- **Adresse vérifiée** : `https://www.youtube.com/@ParisSportifsFootballObjectifP` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.youtube.com/t/terms?hl=fr` (HTTP 200)
  - `https://www.youtube.com/robots.txt` (HTTP 200)
  - Flux Atom/RSS vérifié : `https://www.youtube.com/feeds/videos.xml?channel_id=UCTl5F_SZE0k9Qevf4P2J6Gg` (HTTP 200)
- **Constat réel** :
  - **CGU YouTube & `robots.txt`** : Même cadre légal que `SRC_023` (scraping HTML interdit par `https://www.youtube.com/t/terms?hl=fr` ; flux Atom officiel `/feeds/videos.xml`, oEmbed et YouTube Data API v3 ouverts et conformes).
- **Statut connecteur retenu** : `a_construire` (via flux Atom officiel ou YouTube Data API v3).

---

## SRC_026 — MediaPronos TV (YouTube)
- **Adresse vérifiée** : `https://www.youtube.com/@TeamMediaPronos` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.youtube.com/t/terms?hl=fr` (HTTP 200)
  - `https://www.youtube.com/robots.txt` (HTTP 200)
  - Flux Atom/RSS vérifié : `https://www.youtube.com/feeds/videos.xml?channel_id=UCc6uHcXhEG6jC-bI0_5K-GA` (HTTP 200)
- **Constat réel** :
  - **CGU YouTube & `robots.txt`** : Scraping HTML interdit par `https://www.youtube.com/t/terms?hl=fr` ; flux Atom public `/feeds/videos.xml` et oEmbed ouverts sans restriction dans `robots.txt`.
- **Statut connecteur retenu** : `a_construire` (via flux Atom officiel ou YouTube Data API v3).

---

## SRC_027 — Arno Prono Foot (YouTube)
- **Adresse vérifiée** : `https://www.youtube.com/@arnaud9647` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.youtube.com/t/terms?hl=fr` (HTTP 200)
  - `https://www.youtube.com/robots.txt` (HTTP 200)
  - Flux Atom/RSS vérifié : `https://www.youtube.com/feeds/videos.xml?channel_id=UC1dxTHo5KZke1ZtoNsbYMRw` (HTTP 200)
- **Constat réel** :
  - **CGU YouTube & `robots.txt`** : Scraping HTML interdit par `https://www.youtube.com/t/terms?hl=fr` ; flux Atom public `/feeds/videos.xml` et oEmbed ouverts.
- **Statut connecteur retenu** : `a_construire` (via flux Atom officiel ou YouTube Data API v3).

---

## SRC_028 — Rostom Foot (YouTube)
- **Adresse vérifiée** : `https://www.youtube.com/@RostomFoot` et `https://www.youtube.com/watch?v=KEyNcFx44vY` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.youtube.com/t/terms?hl=fr` (HTTP 200)
  - `https://www.youtube.com/robots.txt` (HTTP 200)
  - Flux Atom/RSS vérifié : `https://www.youtube.com/feeds/videos.xml?channel_id=UC-nQ-xo9_Yzi58bbBRnRNSA` (HTTP 200)
- **Constat réel** :
  - **CGU YouTube & `robots.txt`** : Scraping HTML interdit par `https://www.youtube.com/t/terms?hl=fr` ; flux Atom public `/feeds/videos.xml` et oEmbed ouverts.
- **Statut connecteur retenu** : `a_construire` (via flux Atom officiel ou YouTube Data API v3).

---

## SRC_029 — Arthur D (YouTube)
- **Adresse vérifiée** : `https://www.youtube.com/@_ArthurD` et `https://www.youtube.com/watch?v=YSWitDBEp8Q` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.youtube.com/t/terms?hl=fr` (HTTP 200)
  - `https://www.youtube.com/robots.txt` (HTTP 200)
  - Flux Atom/RSS vérifié : `https://www.youtube.com/feeds/videos.xml?channel_id=UC8zz4KsLHylM3H8V233bZkA` (HTTP 200)
- **Constat réel** :
  - **CGU YouTube & `robots.txt`** : Scraping HTML interdit par `https://www.youtube.com/t/terms?hl=fr` ; flux Atom public `/feeds/videos.xml` et oEmbed ouverts.
- **Statut connecteur retenu** : `a_construire` (via flux Atom officiel ou YouTube Data API v3).

---

## SRC_030 — TonyoTv (YouTube)
- **Adresse vérifiée** : `https://www.youtube.com/@tonyo_ytb` et `https://www.youtube.com/watch?v=Ks_f6xip1Lk` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.youtube.com/t/terms?hl=fr` (HTTP 200)
  - `https://www.youtube.com/robots.txt` (HTTP 200)
  - Flux Atom/RSS vérifié : `https://www.youtube.com/feeds/videos.xml?channel_id=UCtKlXcnN6yNIK2078QHZCmQ` (HTTP 200)
- **Constat réel** :
  - **CGU YouTube & `robots.txt`** : Scraping HTML interdit par `https://www.youtube.com/t/terms?hl=fr` ; flux Atom public `/feeds/videos.xml` et oEmbed ouverts.
- **Statut connecteur retenu** : `a_construire` (via flux Atom officiel ou YouTube Data API v3).

---

## SRC_031 — Leonel Prono (YouTube)
- **Adresse vérifiée** : `https://www.youtube.com/@LEONELPRONO` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.youtube.com/t/terms?hl=fr` (HTTP 200)
  - `https://www.youtube.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **CGU YouTube & `robots.txt`** : Scraping HTML interdit par `https://www.youtube.com/t/terms?hl=fr` ; flux Atom public `/feeds/videos.xml` et oEmbed ouverts.
- **Statut connecteur retenu** : `a_construire` (via flux Atom officiel ou YouTube Data API v3).

---

## SRC_032 — Genie Pro (YouTube)
- **Adresse vérifiée** : `https://www.youtube.com/@GENIEPRO-b5z` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.youtube.com/t/terms?hl=fr` (HTTP 200)
  - `https://www.youtube.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **CGU YouTube & `robots.txt`** : Scraping HTML interdit par `https://www.youtube.com/t/terms?hl=fr` ; flux Atom public `/feeds/videos.xml` et oEmbed ouverts.
- **Statut connecteur retenu** : `a_construire` (via flux Atom officiel ou YouTube Data API v3).

---

## SRC_033 — Rostom Foot sur X
- **Adresse vérifiée** : `https://x.com/RostomFoot` (HTTP 200 — coquille HTML initiale sans les posts de la timeline)
- **URL(s) CGU / Mentions consultées** :
  - `https://x.com/fr/tos` (HTTP 200)
  - `https://x.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Conditions d'utilisation de X (`https://x.com/fr/tos`)** : *« vous ne pouvez pas extraire les Services sans l'autorisation écrite expresse de X... (REMARQUE : le « crawling » [indexation systématique] et le « scraping » [extraction à des fins d'exploration] des Services, sous quelque forme que ce soit et quel qu'en soit le motif, sont expressément interdits sans notre autorisation préalable et expresse) »*.
  - **`robots.txt`** : Bloque `/search/realtime`, `/search/users`, `/search/*/grid` et impose `Crawl-delay: 1` pour certains bots. En pratique, les tweets d'un profil ne sont pas chargés sans session authentifiée ou accès API payant X.
- **Statut connecteur retenu** : `bloque` (interdiction contractuelle explicite du scraping et timeline non accessible sans compte/API payante).

---

## SRC_034 — MediaPronos sur X
- **Adresse vérifiée** : `https://x.com/MediaPronos` (HTTP 200 — coquille HTML initiale sans les posts de la timeline)
- **URL(s) CGU / Mentions consultées** :
  - `https://x.com/fr/tos` (HTTP 200)
  - `https://x.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Conditions d'utilisation de X (`https://x.com/fr/tos`)** : Même interdiction formelle de tout crawling ou scraping hors API officielle payante de X.
- **Statut connecteur retenu** : `bloque` (interdiction contractuelle du scraping et timeline non accessible sans compte/API payante).

---

## SRC_035 — Parieur-Sportif.com
- **Adresse vérifiée** : `https://www.parieur-sportif.com/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.parieur-sportif.com/robots.txt` (HTTP 200)
  - `https://www.parieur-sportif.com/mentions-legales/` (HTTP 404)
  - Flux RSS vérifié : `https://parieur-sportif.com/feed/` (HTTP 200)
- **Constat réel** :
  - **CGU** : **`inconnu`** (aucune page de mentions légales ou CGU liée sur le site ; `/mentions-legales/` renvoie HTTP 404).
  - **`robots.txt`** : `User-agent: *` avec `Disallow:` vide (tout est ouvert) et flux RSS WordPress actif.
- **Statut connecteur retenu** : `a_construire` (flux RSS public disponible).

---

## SRC_036 — PariSportifForum.com
- **Adresse vérifiée** : `https://parisportifforum.com/articles/forum-pronostic-foot/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://parisportifforum.com/mentions-legales/` (HTTP 200)
  - `https://parisportifforum.com/robots.txt` (HTTP 200)
  - Flux RSS vérifié : `https://parisportifforum.com/feed/` (HTTP 200)
- **Constat réel** :
  - **Mentions légales** : *« Droits d'Auteur et Propriété Intellectuelle : Les contenus et œuvres créés par les exploitants de ce site sont soumis au droit d'auteur français. Les téléchargements et copies de ce site sont autorisés uniquement pour un usage privé et non commercial. »*
  - **`robots.txt`** : `User-agent: *` interdit `/wp-admin/`, `/wp-json/` (API REST WordPress explicitement désactivée pour les bots), `/?s=`, `/cdn-cgi/`.
- **Statut connecteur retenu** : `manuel` (restriction `/wp-json/` dans `robots.txt` et limitation aux copies privées non commerciales).

---

## SRC_037 — Pari-Ligue1.fr - Concours Pronostics
- **Adresse vérifiée** : `https://www.pari-ligue1.fr/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.pari-ligue1.fr/reglement` (HTTP 200)
  - `https://www.pari-ligue1.fr/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Règlement** : Détaille le barème de points du concours de pronostics Ligue 1 entre amis et le nettoyage automatique des comptes inactifs, sans clause interdisant la lecture automatisée des pages publiques.
  - **`robots.txt`** : `User-agent: *` bloque uniquement les répertoires techniques `/cache/`, `/crons/`, `/erreurs/`, `/include/`, `/libs/`, `/logs/`.
- **Statut connecteur retenu** : `a_construire`.

---

## SRC_038 — Forum SCO1919 - Topic Pronos Ligue 1
- **Adresse vérifiée** : `http://forum.sco1919.com/viewtopic.php?t=13259` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `http://forum.sco1919.com/ucp.php?mode=terms` (HTTP 200)
  - `http://forum.sco1919.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Conditions d'utilisation phpBB** : Texte standard phpBB régissant la responsabilité des messages publiés par les membres et leur stockage en base de données, sans clause anti-scraping.
  - **`robots.txt`** : `User-agent: *` avec `Disallow:` vide (aucune restriction).
- **Statut connecteur retenu** : `a_construire`.

---

## SRC_039 — Forum Stade Rennais Online - Pronostics J8 L1
- **Adresse vérifiée** : `https://forum.stade-rennais-online.com/viewtopic.php?pid=1677368` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://www.stade-rennais-online.com/Mentions-legales.html` (HTTP 200)
  - `https://forum.stade-rennais-online.com/robots.txt` (HTTP 404)
- **Constat réel** :
  - **Mentions légales** : *« Reproduction et téléchargement des contenus : Les contenus (articles, textes, photos, vidéos...) mis à disposition sur ce site sont, sauf indication contraire, la propriété de Stade Rennais Online [NT Médias SARL]. Ils ne peuvent donc être repris sans autorisation de reproduction préalable, obtenue par la page contact du site. »*
  - **`robots.txt`** : HTTP 404 sur le sous-domaine `forum.stade-rennais-online.com`.
- **Statut connecteur retenu** : `manuel` (reprise soumise à autorisation préalable selon les mentions légales de l'éditeur).

---

## SRC_040 — Forum Poteaux-Carrés - Concours Pronostics
- **Adresse vérifiée** : `https://forum.poteaux-carres.com/viewforum.php?f=42` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://forum.poteaux-carres.com/ucp.php?mode=terms` (HTTP 200)
  - `https://forum.poteaux-carres.com/robots.txt` (HTTP 404)
- **Constat réel** :
  - **Conditions d'utilisation phpBB** : Contrat type phpBB d'inscription au forum des supporters stéphanois, sans clause interdisant l'indexation ou la lecture automatisée des sujets publics.
  - **`robots.txt`** : HTTP 404 (absent sur le sous-domaine du forum).
- **Statut connecteur retenu** : `a_construire`.

---

## SRC_041 — Forum MadeInLens - Section Pronostics
- **Adresse vérifiée** : `https://forum.madeinlens.com/forum/16-pronostics/` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://forum.madeinlens.com/terms/` (HTTP 200)
  - `https://forum.madeinlens.com/robots.txt` (HTTP 200)
- **Constat réel** :
  - **Conditions d'inscription** : Règles de modération des contributions sur la plateforme Invision Community, sans interdiction d'indexation des sujets publics.
  - **`robots.txt`** : Pour `User-agent: *`, bloque les actions d'écriture/recherche (`/startTopic/`, `/discover/unread/`, `/markallread/`, `/staff/`, `/search/`) et fixe un **`Crawl-delay: 5`**.
- **Statut connecteur retenu** : `a_construire` (en respectant strictement `Crawl-delay: 5` secondes entre deux requêtes).

---

## SRC_042 — Forum Hardware.fr - Topic Mon Petit Prono L1/L2
- **Adresse vérifiée** : `https://forum.hardware.fr/hfr/Discussions/Sports/petit-ligue-ligue-sujet_94713_1.htm` (HTTP 200)
- **URL(s) CGU / Mentions consultées** :
  - `https://forum.hardware.fr/robots.txt` (HTTP 200)
  - `https://forum.hardware.fr/hfr/charte.php` (HTTP 404) et `https://www.hardware.fr/html/mentions_legales.php` (HTTP 404)
- **Constat réel** :
  - **CGU** : **`inconnu`** (les anciennes URLs de charte et mentions légales HFR retournent HTTP 404 ; la charte s'affiche uniquement lors du parcours d'inscription de compte, non ouvert conformément aux consignes).
  - **`robots.txt`** : `https://forum.hardware.fr/robots.txt` répond HTTP 200 avec un contenu vide (aucune directive `Disallow`).
- **Statut connecteur retenu** : `a_construire` (sous réserve de vérifier la charte HFR hors parcours d'inscription).
