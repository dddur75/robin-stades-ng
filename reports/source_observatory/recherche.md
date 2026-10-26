# Rapport de recherche et méthodologie — Mission T2 (`pilot_sources.csv`)

Date d'exécution : `2026-10-25`  
Rôle : GEMINI (Recherche)  
Dossier de sortie : `C:\Users\ddura\IA-Team\robin-stades-ng-wt\inbox\gemini\`

---

## 1. Méthode de sélection et de vérification

### 1.1 Constitution de l'échantillon (42 sources)
L'objectif de la mission T2 est de construire un registre pilote de **30 à 50 sources publiques** de pronostics sur la **Ligue 1 (France)** comprenant **au moins 1/3 de petits auteurs ou sources peu connues**.

Le registre `pilot_sources.csv` rassemble **42 sources vérifiées**, réparties ainsi :
- **24 sources `media_site_tipster_connu` (57,1 %)** : sites francophones et internationaux de pronostics (`RueDesJoueurs`, `Coteur`, `PenseBet`, `MediaPronos`, `DailySportPick`, `FreeSuperTips`, `SportyTrader`), plateformes communautaires de tipsters (`ProTipster`, `Tipstop`, `Zone-Supporter`, `OLBG`, `Betrush`), sites de prévisions statistiques (`Vitibet`, `SoccerStats`, `Feedinco`, `Statarea`, `MatchEnDirect`), médias sportifs (`Les-Transferts`, `OneFootball`, `FootMercato`, `SportsMole`), grands espaces communautaires (`Pronosoft`, `Reddit r/Ligue1`) et chaîne YouTube établie (`Parieurs Foot` — 98,3k abonnés).
- **18 sources `petit_auteur_inconnu` (42,9 %, soit > 1/3)** :
  - **8 petites chaînes YouTube indépendantes** de pronostics Ligue 1 (de 1,19k à 23,6k abonnés) : `Objectif Profits` (1,19k abonnés), `Leonel Prono` (1,33k abonnés), `MediaPronos TV` (2,71k abonnés), `Genie Pro` (2,79k abonnés), `Arno Prono Foot` (3,05k abonnés), `Rostom Foot` (15,5k abonnés), `Arthur D` (20,9k abonnés), `TonyoTv` (23,6k abonnés).
  - **2 comptes X publics** de petits pronostiqueurs (`@RostomFoot`, `@MediaPronos`).
  - **3 petits blogs et sites amateurs indépendants** (`Parieur-Sportif.com`, `PariSportifForum.com`, `Pari-Ligue1.fr`).
  - **5 forums publics de supporters ou sujets communautaires à faible audience** (`Forum SCO1919` Angers, `Forum Stade Rennais Online`, `Forum Poteaux-Carrés` ASSE, `Forum MadeInLens` RC Lens, topic `Mon Petit Prono L1/L2` sur `Hardware.fr`).

### 1.2 Protocole technique (lecture seule, zéro contournement)
Pour chaque source candidate :
1. **Ouverture directe de l'URL cible (`adresse`)** via requête HTTP `GET` standard en lecture seule, sans création de compte, sans cookie d'authentification et sans contournement de pare-feu.
2. **Vérification des accès structurés sans contournement (`mode_acces`)** : test systématique des flux RSS WordPress (`/feed/`), des flux Atom publics YouTube (`https://www.youtube.com/feeds/videos.xml?channel_id=...`), de l'endpoint `oEmbed` YouTube (`https://www.youtube.com/oembed`) et du flux RSS Reddit (`.rss`).
3. **Lecture directe du fichier `/robots.txt`** à la racine de chaque domaine pour relever les directives `User-agent`, `Allow`, `Disallow` et `Crawl-delay` (notamment les règles visant `GPTBot`, `CCBot`, `ClaudeBot`, `Bytespider`, `Diffbot`, etc.).
4. **Extraction et lecture des pages de CGU / Mentions légales** présentes dans le DOM public de chaque site afin d'identifier les clauses réelles relatives au scraping, à l'extraction de bases de données et au droit d'auteur.

### 1.3 Grille de décision pour `etat_connecteur`
- **`a_construire` (25 sources)** : accès technique ouvert en lecture directe (flux RSS/Atom public, API officielle ou page HTML publique en HTTP 200) **et** absence d'interdiction de crawl sur la ressource ciblée dans `robots.txt` ou les CGU (ou collecte limitée aux métadonnées syndiquées via RSS/Atom/API officielle).
- **`manuel` (14 sources)** : page consultable publiquement par un humain (HTTP 200), mais CGU/Mentions légales interdisant explicitement le scraping, la copie ou toute utilisation autre que l'affichage de navigation personnelle (`RueDesJoueurs`, `Pronosoft`, `Tipstop`, `FootMercato`, `Betrush`, `FreeSuperTips`, `SportsMole`, `SoccerStats`, `Reddit`, `PariSportifForum`, `Stade Rennais Online`), ou `robots.txt` bloquant massivement les bots d'extraction (`MatchEnDirect`, `OLBG`, `Vitibet`).
- **`bloque` (3 sources)** : blocage technique immédiat sans contournement (`SportyTrader` en HTTP 403/404 sur les pages HTML) ou combinaison d'une interdiction contractuelle absolue de scraping et d'une timeline non servie sans compte/API payante (`X / Twitter` pour `@RostomFoot` et `@MediaPronos`).

---

## 2. Ce qui n'a pas pu être vérifié (et motifs)

Conformément à la consigne (*« "inconnu" si non vérifié, jamais inventé »*), voici la liste exhaustive des éléments qui n'ont pas pu être vérifiés sans contournement :

### 2.1 Pages de CGU absentes, introuvables ou en erreur HTTP 404 (notées `inconnu`)
Pour 7 sources du registre, le fichier `/robots.txt` et la page de pronostics ont bien été ouverts et vérifiés, mais le texte des CGU reste **`inconnu`** :
- **`SRC_004` (`protipster.fr`)** : aucun lien vers des conditions générales dans le pied de page public ; les URLs `/conditions-generales` et `protipster.com/terms-of-use` retournent `HTTP 404`.
- **`SRC_012` (`matchendirect.fr`)** : aucun lien de mentions légales ou CGU actif ; `/mentions-legales.html` et `/cgu.html` retournent `HTTP 404`.
- **`SRC_014` (`olbg.com`)** : les pages `/terms`, `/terms-and-conditions` et `/about/terms` retournent toutes `HTTP 404`.
- **`SRC_016` (`vitibet.com`)** : aucune page de CGU dédiée sur le site en dehors du bandeau de consentement cookies (la politique vis-à-vis des robots est en revanche très détaillée dans `vitibet.com/robots.txt`).
- **`SRC_020` (`feedinco.com`)** : aucun lien vers des conditions d'utilisation sur l'interface ; `/terms` retourne `HTTP 404`.
- **`SRC_035` (`parieur-sportif.com`)** : petit blog WordPress dépourvu de page de mentions légales (`/mentions-legales/` en `HTTP 404`).
- **`SRC_042` (`forum.hardware.fr`)** : les anciennes URLs `/hfr/charte.php` et `hardware.fr/html/mentions_legales.php` retournent `HTTP 404` ; la charte du forum est affichée lors du formulaire d'inscription de compte, qui n'a pas été ouvert conformément à l'interdiction de créer un compte.

### 2.2 Sites supplémentaires testés mais bloqués par protection anti-bot (HTTP 403 / Challenge / SSL)
Lors de l'exploration initiale, plusieurs sources publiques connues ou forums de supporters ont été testés en `GET` standard mais ont opposé un blocage technique immédiat (WAF Cloudflare, DataDome, Anubis ou erreur réseau/SSL). Conformément à l'interdiction de tout contournement :
- **`sportytrader.com` (`SRC_024`)** : conservé dans `pilot_sources.csv` avec `etat_connecteur = bloque` car `/robots.txt` est accessible (`HTTP 200`), tandis que les pages HTML de pronostics Ligue 1 et du forum renvoient `HTTP 403 Forbidden` / `HTTP 404`.
- **Autres sites testés et bloqués en HTTP 403 (non intégrés ou documentés ici pour traçabilité)** :
  - `wincomparator.com` : `/robots.txt` accessible (`HTTP 200`), mais `https://www.wincomparator.com/fr-fr/pronostics/football/france/ligue-1-123/` renvoie `HTTP 403`.
  - `forebet.com` : `https://www.forebet.com/fr/` et `/robots.txt` renvoient `HTTP 403 Forbidden`.
  - `windrawwin.com` : `https://www.windrawwin.com/fr/pronostics/aujourdhui/` et `/robots.txt` renvoient `HTTP 403 Forbidden`.
  - `oddspedia.com` : `/robots.txt` accessible (`HTTP 200`), mais `https://oddspedia.com/fr/pronostics/classement-pronostiqueurs` renvoie `HTTP 403 Forbidden`.
  - `blogabet.com` & `tipstrr.com` : pages d'accueil bloquées en `HTTP 403 Forbidden` (avec `Crawl-delay: 60` dans `blogabet.com/robots.txt`).
  - `sospronostics.com`, `lequipe.fr`, `sofoot.com`, `footystats.org`, `predictz.com`, `winamax.fr/news`, `jeuxvideo.com/forums/0-20-0-1-0-1-0-football.htm`, `planete-asm.fr/forum` : renvoient `HTTP 403 Forbidden` sur requête HTTP directe sans navigateur.
  - `racingstub.com/forum/` (forum RC Strasbourg) : renvoie un challenge anti-bot actif **Anubis** (*« Making sure you're not a bot! »*) et son `/robots.txt` bloque nominativement `GPTBot`, `ClaudeBot`, `CCBot`, `PerplexityBot`, `Bytespider`, etc.
  - `allezlelosc.fr/forum/` : échec de vérification TLS (`SSL: CERTIFICATE_VERIFY_FAILED - Hostname mismatch`).

### 2.3 Contenus internes aux vidéos YouTube et timelines X
- **Comptes X (`SRC_033`, `SRC_034`)** : l'URL du profil répond `HTTP 200` et permet de vérifier l'existence du compte, et les CGU (`https://x.com/fr/tos`) ont été lues, mais la liste des tweets récents n'est pas livrée par X sans connexion à un compte ou souscription à l'API payante.
- **Chaînes YouTube (`SRC_023` et `SRC_025` à `SRC_032`)** : l'existence des chaînes, leur nombre d'abonnés et leurs vidéos de pronostics Ligue 1 (ex. Journée 8 de la saison 2026-2027) ont été vérifiés via `oEmbed` et les flux Atom publics (`/feeds/videos.xml`), mais les pronostics détaillés uniquement à l'oral dans la piste audio ne figurent pas tous dans le titre ou la description XML.
