# Preuves d'accès — Sources publiques Ligue 1 supplémentaires (`SRC_043` à `SRC_065`)

- **Date de vérification** : `2026-10-26`
- **Périmètre** : 23 nouvelles sources publiques Ligue 1 réellement collectables (`etat_connecteur = a_construire`), absentes du registre initial (`pilot_sources.csv`, `SRC_001` à `SRC_042`), dont **11** `media_site_tipster_connu` (`SRC_043` à `SRC_053`) et **12** `petit_auteur_inconnu` (`SRC_054` à `SRC_065`).
- **Méthode** : requêtes HTTP directes sans compte, sans paywall et sans contournement. Toutes les sources présentant un blocage HTTP (403/Cloudflare/Anubis), un `robots.txt` interdisant la page (`Disallow: /`), ou des CGU/mentions légales interdisant le scraping, l'extraction automatisée ou restreignant la consultation à un usage monoposte sur un seul écran ont été exclues.

---

## SRC_043 — Qui Parier ? (QuiParier.com) - Pronostics Ligue 1

- **Catégorie d'audience** : `media_site_tipster_connu` (`comparateur_pronostics`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.quiparier.com/competition-football,ligue-1.html (HTTP 200)`
  - `https://www.quiparier.com/robots.txt (HTTP 200)`
  - `https://www.quiparier.com/mentions-legales.html (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Page de liste HTML publique avec pronostics Ligue 1 datés par journée et horaires de coup d'envoi (ex. matchs de Ligue 1 saison 2026/2027 avec cotes 1N2 comparées et pronostic du trader).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`) et L2 (`Allow: /`) — aucune interdiction sur `/competition-football,ligue-1.html`.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Allow: /
  L4: # Pages / endpoints à ne pas indexer
  L5: Disallow: /valid_contact.php
  L6: Disallow: /test.php
  L7: Disallow: /*?trk=
  L14: Sitemap: https://www.quiparier.com/sitemap.xml
  ```
- **Clause CGU / Mentions légales consultée (`https://www.quiparier.com/mentions-legales.html`)** :
  > « Mentions légales — Date des conditions générales : 21/05/2026 — v2. Éditeur du site : Le site QuiParier.com est édité par la société iNuage, créateur de sites internet à Laval, dont le siège social est situé 53000 Laval — France, immatriculée au RCS sous le n° 483 011 672. [...] Propriété intellectuelle : L'ensemble des contenus présents sur QuiParier.com (textes, graphismes, logos, données, mise en page) est protégé par le droit d'auteur. Toute reproduction, totale ou partielle, sans autorisation écrite préalable est interdite. »
- **Statut lecture automatisée** : Clause de propriété intellectuelle classique ; CGU **silencieuses** sur la lecture automatisée.

---

## SRC_044 — Wallabet - Pronostics Ligue 1

- **Catégorie d'audience** : `media_site_tipster_connu` (`site_pronostics`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://wallabet.fr/pronostic-sportif/football-p1/ligue-1/ (HTTP 200)`
  - `https://wallabet.fr/feed/ (HTTP 200)`
  - `https://wallabet.fr/robots.txt (HTTP 200)`
  - `https://wallabet.fr/mentions-legales/ (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`https://wallabet.fr/feed/`, articles avec `<pubDate>`) + page de rubrique Ligue 1 (`https://wallabet.fr/pronostic-sportif/football-p1/ligue-1/`) listant les pronostics et analyses Ligue 1.
- **Ligne(s) de `robots.txt` consultée(s)** : L10 (`User-agent: *`) et L11-L16 — `/pronostic-sportif/football-p1/ligue-1/` et le flux racine `/feed/` ne sont pas interdits (seuls les sous-flux `/*/feed` sont filtrés en L14).
- **Extrait de `robots.txt`** :
  ```text
  L2: sitemap: https://wallabet.fr/sitemap_index.xml
  L8: # All Bots
  L10: User-agent: *
  L11: Disallow: /*?attachment*
  L12: Disallow: /wp-login.php
  L13: Disallow: */trackback
  L14: Disallow: /*/feed
  L15: Disallow: /*/comments
  L16: Disallow: /cgi-bin
  ```
- **Clause CGU / Mentions légales consultée (`https://wallabet.fr/mentions-legales/`)** :
  > « Edition du site Wallabet.fr : Le site Wallabet.fr est édité par : La société BluewindowLTD à Malte. [...] Utilisateurs / Vous : désignent les internautes majeurs ou mineurs autorisés, agissant à titre non-professionnel se connectant à wallabet.fr en vue de consulter le Site, de partager Nos publications sur les réseaux sociaux ou de prendre contact avec Nous. [...] Propriété intellectuelle : [...] Les Utilisateurs ne peuvent, en aucune manière, reproduire, représenter, diffuser, modifier, concéder tout ou partie des éléments du Site, notamment les éléments audiovisuels, graphiques et/ou littéraires, sans Notre accord préalable et écrit ou celui de Nos partenaires concernés. »
- **Statut lecture automatisée** : Clause de propriété intellectuelle classique ; CGU **silencieuses** sur la lecture automatisée.

---

## SRC_045 — MightyTips - French Ligue 1 Predictions

- **Catégorie d'audience** : `media_site_tipster_connu` (`site_pronostics`, langue `en`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.mightytips.com/football-predictions/ligue-1/ (HTTP 200)`
  - `https://www.mightytips.com/robots.txt (HTTP 200)`
  - `https://www.mightytips.com/about-us/privacy-policy/ (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Page de liste HTML publique (`https://www.mightytips.com/football-predictions/ligue-1/`) affichant les pronostics datés de Ligue 1 (`French Ligue 1 Predictions & Betting Tips for Today`).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`) et L2-L12 — aucune restriction sur `/football-predictions/ligue-1/` (la ligne L6 interdit `/rss`, on utilise donc exclusivement la page HTML publique).
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Disallow: *?s=
  L3: Disallow: *&s=
  L4: Disallow: /search/
  L5: Disallow: *?attachment_id=
  L6: Disallow: /rss
  L7: Disallow: /embed
  L8: Disallow: /go/
  L9: Disallow: /wp-content/
  L14: Sitemap: https://www.mightytips.com/sitemap.xml
  ```
- **Clause CGU / Mentions légales consultée (`https://www.mightytips.com/about-us/privacy-policy/`)** :
  > « Privacy Policy: How We Collect, Use, Maintain and Disclose Information — Last updated August 24, 2023. This Privacy Policy governs the manner in which SEOBROTHERS CY LTD, with company no. HE 433634 (“We”, “Company”) collects, uses, maintains and discloses information collected from users ("User", “Private person”, “You”) of the mightytips.com website ("Website"). [...] General provisions : The controller and the processor of the personal data of the users on this Website is the Company. This Privacy Policy constitutes the integral part of Terms and Conditions. »
- **Statut lecture automatisée** : Mentions et politique d'utilisation **silencieuses** sur la lecture automatisée des pages publiques.

---

## SRC_046 — Kicktipp France - Pronostics Ligue 1

- **Catégorie d'audience** : `media_site_tipster_connu` (`site_pronostics`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.kicktipp.fr/pronostics-ligue1/ (HTTP 200)`
  - `https://www.kicktipp.fr/pronostics-ligue1/tableau-des-pronostics (HTTP 200)`
  - `https://www.kicktipp.fr/robots.txt (HTTP 200)`
  - `https://www.kicktipp.fr/info/service/conditions-utilisation (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Pages publiques de concours et tableaux de pronostics datés par journée de Ligue 1 (`https://www.kicktipp.fr/pronostics-ligue1/` et `https://www.kicktipp.fr/pronostics-ligue1/tableau-des-pronostics`).
- **Ligne(s) de `robots.txt` consultée(s)** : L2 (`User-agent: *`) et L3-L5 (`Disallow: /api/`, `/info/language`, `/error/`) — `/pronostics-ligue1/` est autorisé.
- **Extrait de `robots.txt`** :
  ```text
  L2: User-agent: *
  L3: Disallow: /api/
  L4: Disallow: /info/language
  L5: Disallow: /error/
  L7: User-agent: SemrushBot
  L8: Disallow: /
  ```
- **Clause CGU / Mentions légales consultée (`https://www.kicktipp.fr/info/service/conditions-utilisation`)** :
  > « Conditions d'utilisation : Le service de Kicktipp peut être utilisé par chacun dans le respect des conditions suivantes. Les jeux de pronostics ne peuvent pas être utilisés pour des jeux d'argent et des jeux de chance illégaux, dans le cadre légal en vigueur. [...] Veuillez respecter la propriété intellectuelle et les droits d'auteur tiers. Si des images ou textes violent les droits de tiers ou s'ils font l'objet d'une suspicion fondée, Kicktipp a le droit de supprimer ces contenus. »
- **Statut lecture automatisée** : CGU **silencieuses** sur la lecture automatisée.

---

## SRC_047 — Football.fr - Rubrique Ligue 1

- **Catégorie d'audience** : `media_site_tipster_connu` (`media_sportif`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.football.fr/ligue-1 (HTTP 200)`
  - `https://www.football.fr/ligue-1/feed (HTTP 200)`
  - `https://www.football.fr/robots.txt (HTTP 200)`
  - `https://www.football.fr/mentions-legales (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 dédié Ligue 1 (`https://www.football.fr/ligue-1/feed`, ex. `Mon, 26 Oct 2026 12:49:59 +0000` : *RC Lens, la très lourde sanction !*) + page de liste HTML datée (`https://www.football.fr/ligue-1`).
- **Ligne(s) de `robots.txt` consultée(s)** : L3-L4 (Sitemaps) et L6-L22 (exclusions techniques WordPress `/wp-*.php`, `/wp-login.php`) — aucune interdiction sur `/ligue-1` ni sur `/ligue-1/feed`.
- **Extrait de `robots.txt`** :
  ```text
  L2: # XML Sitemap & Google News Feeds version 4.5 - http://status301.net/wordpress-plugins/xml-sitemap-feed/
  L3: Sitemap: https://www.football.fr/sitemap.xml
  L4: Sitemap: https://www.football.fr/sitemap-news.xml
  L6: Disallow: /*/xmlrpc.php
  L7: Disallow: /wp-*.php
  L8: Disallow: /*/trackback/
  L21: Disallow: /wp-login.php
  L22: Disallow: /wp-content/plugins/
  ```
- **Clause CGU / Mentions légales consultée (`https://www.football.fr/mentions-legales`)** :
  > « MENTIONS LEGALES DU SITE https://www.football.fr/ (le « Site ») — EDITEUR : AU FEMININ Société par actions simplifiée unipersonnelle au capital social de 1 941 758 € Siège social : 8 rue Barthélémy Danjou, 92100 Boulogne-Billancourt RCS : 423 780 113 R.C.S NANTERRE [...] PROPRIETE INTELLECTUELLE : L’intégralité des pages, textes, images, graphiques, animations, vidéos, sons et autres œuvres ainsi que leurs arrangements représentés sur le Site sont protégés par droit d’auteur ou d’autres droits de protection prévus par la loi sont déposés par le Groupe Reworld Media. Sauf accord explicite, aucune licence n’est accordée au titre du présent Site. Il est interdit de copier, diffuser ou modifier tout ou partie du contenu du présent Site à des fins commerciales ou autre et d’en permettre l’accès à des tiers sans l’autorisation préalable écrite de l’Editeur. »
- **Statut lecture automatisée** : Clause de droit d'auteur classique ; mentions légales **silencieuses** sur la lecture automatisée.

---

## SRC_048 — Foot01 - Rubrique Ligue 1

- **Catégorie d'audience** : `media_site_tipster_connu` (`media_sportif`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.foot01.com/ligue1 (HTTP 200)`
  - `https://www.foot01.com/sitemap/news.xml (HTTP 200)`
  - `https://www.foot01.com/robots.txt (HTTP 200)`
  - `https://www.foot01.com/mentions-legales (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS/XML News public (`https://www.foot01.com/sitemap/news.xml`, ex. `Mon, 26 Oct 2026 15:30:00 +0100` : *Clément Turpin l’arbitre anti-OM, c’est prouvé*) + page de liste HTML datée (`https://www.foot01.com/ligue1` avec horodatage par article : `26 oct. , 15:30`, `26 oct. , 15:00`, etc.).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`), L2-L9 (`Disallow: /admin/`, etc.) et L12-L13 (`Sitemap`) — `/ligue1` et `/sitemap/news.xml` sont autorisés.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Disallow: /admin/
  L3: Disallow: /archives,
  L4: Disallow: /*archives,
  L5: Disallow: /*?utm_
  L6: Disallow: /cdm-clubs/
  L7: Disallow: /*?cat_id=
  L8: Disallow: /matchcenter/
  L9: Disallow: /matchcenter?
  L12: Sitemap: https://www.foot01.com/sitemap.xml
  L13: Sitemap: https://www.foot01.com/sitemap/news-latest.xml
  ```
- **Clause CGU / Mentions légales consultée (`https://www.foot01.com/mentions-legales`)** :
  > « Mentions Légales - Confidentialité : Editeur SARL Sportagence, 441 route du Breuil en Auge 14130 St Philbert des Champs, RCS : Lisieux B 518.874.458 [...] Sauf mention contraire, les photos appartiennent à ICON SPORT agence de presse 6 rue des marguerites 92000 Nanterre. La marque, le design complet, les éléments graphiques originaux de Foot01.com ont été déposés auprès de l'INPI. »
- **Statut lecture automatisée** : Mentions légales **silencieuses** sur la lecture automatisée.

---

## SRC_049 — Maxifoot - Matchs & Actualites Ligue 1

- **Catégorie d'audience** : `media_site_tipster_connu` (`media_sportif`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.maxifoot.fr/foot-matchs_ligue1.htm (HTTP 200)`
  - `http://rss.maxifoot.com/football-general.xml (HTTP 200)`
  - `https://www.maxifoot.fr/robots.txt (HTTP 200)`
  - `https://www.maxifoot.fr/infoslegales.html (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`http://rss.maxifoot.com/football-general.xml`, ex. `Mon, 26 Oct 2026 15:43:48 +0100` : *Strasbourg : un souci émotionnel pour Oliveira*) + page HTML de résultats/matchs Ligue 1 (`https://www.maxifoot.fr/foot-matchs_ligue1.htm`).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`) et L2-L16 — `/foot-matchs_ligue1.htm` et le flux RSS `http://rss.maxifoot.com/football-general.xml` sont autorisés (seul `/club-l1/` est exclu en L8).
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Disallow: *.htm?fb_comment_id=*
  L3: Disallow: /facebook.php
  L4: Disallow: /adds/adclick.php
  L5: Disallow: /sondage/
  L6: Disallow: /NewsPlus/
  L7: Disallow: /club-l2/
  L8: Disallow: /club-l1/
  L9: Disallow: /resultat-l2/
  L15: Disallow: /article-*.htm$
  L16: Disallow: /vote-sondage/
  ```
- **Clause CGU / Mentions légales consultée (`https://www.maxifoot.fr/infoslegales.html`)** :
  > « Information légales - Privacy policies : Le présent site est la propriété de la société ADVIMEDIA SARL, inscrite au registre du commerce et des sociétés de Créteil sous le numéro RCS Creteil B 488 147 893, et son siège social au 139 avenue d'Italie 75013 PARIS. [...] La structure générale, ainsi que les textes, composant ce site sont la propriété de la société ADVIMEDIA et ses partenaires. Toute représentation totale ou partielle de ce site ou d'un ou plusieurs de ces composants, par quelque procédé que ce soit, sans autorisation expresse de la société MAXIFOOT est interdite et constituerait une contrefaçon sanctionnée par les articles L.335-2 et suivants du Code de la propriété intellectuelle. »
- **Statut lecture automatisée** : Clause de droit d'auteur classique (et rappel Loi Informatique et Libertés sur les données personnelles) ; mentions légales **silencieuses** sur la lecture automatisée des publications sportives.

---

## SRC_050 — Foot-National - Rubrique Ligue 1

- **Catégorie d'audience** : `media_site_tipster_connu` (`media_sportif`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.foot-national.com/ligue-1.html (HTTP 200)`
  - `https://www.foot-national.com/rss/ligue-1.html (HTTP 200)`
  - `https://www.foot-national.com/robots.txt (HTTP 200)`
  - `https://www.foot-national.com/mentions.html (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 dédié Ligue 1 (`https://www.foot-national.com/rss/ligue-1.html`, ex. `Mon, 26 Oct 2026 08:23:00 +0100` : *OM : Bruno Genesio rétrograde un Minot en équipe réserve*, *PSG - OL : les compositions probables du choc*) + page HTML (`https://www.foot-national.com/ligue-1.html`).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`) et L2-L6 (`Disallow: /cron/`, `/newsletter/`, `/ajax/`, `/photo/`) — `/ligue-1.html` et `/rss/ligue-1.html` sont autorisés.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Disallow: /cron/
  L3: Disallow: /newsletter/
  L4: Disallow: /ajax/
  L5: Disallow: /photo/article/
  L6: Disallow: /photo/theque/
  L8: Sitemap: https://www.foot-national.com/sitemap.xml
  ```
- **Clause CGU / Mentions légales consultée (`https://www.foot-national.com/mentions.html`)** :
  > « Informations légales : En vertu de l'article 6 de la loi n°2004-575 du 21 juin 2004 pour la confiance dans l'économie numérique (LCEN), il est précisé aux utilisateurs des sites suivants : [...] https://www.foot-national.com [...] l'identité des différents intervenants dans le cadre de leur réalisation et de leur suivi : Editeur du Site : La société HORIZON MEDIA Société par Actions Simplifiée au capital de 92.710 €uros, Siège social : 70, rue Rivay, à Levallois-Perret (92300), RCS de Nanterre sous le numéro 452 172 786 [...] Hébergeur du Site : La société OVH [...] Référence du document : Version du 15/04/2025. »
- **Statut lecture automatisée** : Mentions légales LCEN **silencieuses** sur la lecture automatisée.

---

## SRC_051 — Onze Mondial - Ligue 1 & Paris Sportifs

- **Catégorie d'audience** : `media_site_tipster_connu` (`media_sportif`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.onzemondial.com/ligue-1 (HTTP 200)`
  - `https://www.onzemondial.com/rss/france.html (HTTP 200)`
  - `https://www.onzemondial.com/robots.txt (HTTP 200)`
  - `https://www.onzemondial.com/mentions.html (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`https://www.onzemondial.com/rss/france.html`, ex. `Mon, 26 Oct 2026 15:31:00 +0100` : *Lille - Lens : les Sang et Or interdisent leurs supporters de se déplacer pour le derby du Nord*) + page de rubrique Ligue 1 (`https://www.onzemondial.com/ligue-1`).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`) et L2-L6 (`Disallow: /cron/`, `/newsletter/`, `/ajax/`, `/photo/`) — `/ligue-1` et `/rss/france.html` sont autorisés.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Disallow: /cron/
  L3: Disallow: /newsletter/
  L4: Disallow: /ajax/
  L5: Disallow: /photo/article/
  L6: Disallow: /photo/theque/
  L8: Sitemap: https://www.onzemondial.com/sitemap.xml
  ```
- **Clause CGU / Mentions légales consultée (`https://www.onzemondial.com/mentions.html`)** :
  > « Informations légales : En vertu de l'article 6 de la loi n°2004-575 du 21 juin 2004 pour la confiance dans l'économie numérique (LCEN), il est précisé aux utilisateurs des sites suivants : [...] https://www.onzemondial.com [...] Editeur du Site : La société HORIZON MEDIA Société par Actions Simplifiée au capital de 92.710 €uros, Siège social : 70, rue Rivay, à Levallois-Perret (92300) RCS de Nanterre sous le numéro 452 172 786 [...] Hébergeur du Site : La société OVH [...] Référence du document : Version du 15/04/2025. »
- **Statut lecture automatisée** : Mentions légales LCEN **silencieuses** sur la lecture automatisée.

---

## SRC_052 — LiveFoot - Rubrique Ligue 1

- **Catégorie d'audience** : `media_site_tipster_connu` (`media_sportif`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.livefoot.fr/france/ligue1/ligue1.php (HTTP 200)`
  - `https://www.livefoot.fr/sitemap-news.xml (HTTP 200)`
  - `https://www.livefoot.fr/robots.txt (HTTP 200)`
  - `https://www.livefoot.fr/mentions-legales.php (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux XML Google News (`https://www.livefoot.fr/sitemap-news.xml`, ex. `2026-10-26T09:00:59+01:00` : *ASSE : Quand Ian Cathro fait une « José Mourinho » !*, `2026-10-26T08:00:59+01:00` : *FC Nantes : Vendre le club plutôt que de virer Franck Kita ?*) + page de liste Ligue 1 (`https://www.livefoot.fr/france/ligue1/ligue1.php`).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`Sitemap: https://www.livefoot.fr/sitemap-news.xml`), L3 (`User-agent: *`) et L4 (`Disallow: /clic_v2.php`) — `/france/ligue1/ligue1.php` et `/sitemap-news.xml` sont autorisés.
- **Extrait de `robots.txt`** :
  ```text
  L1: Sitemap: https://www.livefoot.fr/sitemap-news.xml
  L3: User-agent: *
  L4: Disallow: /clic_v2.php
  L6: User-agent: ia_archiver
  L7: Disallow: /
  ```
- **Clause CGU / Mentions légales consultée (`https://www.livefoot.fr/mentions-legales.php`)** :
  > « INFORMATION CONCERNANT L'UTILISATION DES COOKIES : Lors de la consultation du site, des informations sont susceptibles d'être enregistrées dans des fichiers "Cookies" installés dans votre ordinateur, tablette ou téléphone mobile. Cette page permet de comprendre ce qu'est un Cookie, à quoi il sert et comment on peut le paramétrer. »
- **Statut lecture automatisée** : Mentions légales **silencieuses** sur la lecture automatisée.

---

## SRC_053 — Football365 - Rubrique Ligue 1

- **Catégorie d'audience** : `media_site_tipster_connu` (`media_sportif`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.football365.fr/france/ligue-1 (HTTP 200)`
  - `https://www.football365.fr/feed (HTTP 200)`
  - `https://www.football365.fr/robots.txt (HTTP 200)`
  - `https://www.football365.fr/mentions-legales-football-365 (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`https://www.football365.fr/feed`, ex. `Mon, 26 Oct 2026 14:38:54 +0000`) + page de rubrique Ligue 1 (`https://www.football365.fr/france/ligue-1`, articles Ligue 1 datés).
- **Ligne(s) de `robots.txt` consultée(s)** : L5 (`User-agent: *`) et L6-L21 — `/france/ligue-1` et le flux principal `/feed` sont autorisés (seuls les flux d'articles unitaires `/*.html/feed` sont exclus en L16).
- **Extrait de `robots.txt`** :
  ```text
  L3: Sitemap: https://www.football365.fr/sitemap-news.xml
  L5: User-agent: *
  L6: Disallow: /*/xmlrpc.php
  L7: Disallow: /wp-*.php
  L8: Disallow: /*/trackback/
  L16: Disallow: /*.html/feed
  L20: Disallow: /wp-login.php
  L21: Disallow: /wp-content/plugins/
  ```
- **Clause CGU / Mentions légales consultée (`https://www.football365.fr/mentions-legales-football-365`)** :
  > « MENTIONS LEGALES DU SITE https://www.football365.fr/ (le « Site ») — EDITEUR : AU FEMININ Société par actions simplifiée unipersonnelle au capital social de 1 941 758 € Siège social : 8 rue Barthélémy Danjou, 92100 Boulogne-Billancourt RCS : 423 780 113 R.C.S NANTERRE [...] PROPRIETE INTELLECTUELLE : L’intégralité des pages, textes, images, graphiques, animations, vidéos, sons et autres œuvres ainsi que leurs arrangements représentés sur le Site sont protégés par droit d’auteur ou d’autres droits de protection prévus par la loi sont déposés par le Groupe Reworld Media. Sauf accord explicite, aucune licence n’est accordée au titre du présent Site. Il est interdit de copier, diffuser ou modifier tout ou partie du contenu du présent Site à des fins commerciales ou autre et d’en permettre l’accès à des tiers sans l’autorisation préalable écrite de l’Editeur. »
- **Statut lecture automatisée** : Clause de propriété intellectuelle classique ; mentions légales **silencieuses** sur la lecture automatisée.

---

## SRC_054 — Pronor - Blog & Analyses Pronostics Ligue 1

- **Catégorie d'audience** : `petit_auteur_inconnu` (`blog_amateur`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.pronor.fr/blog-actualite-paris-sportifs/ (HTTP 200)`
  - `https://www.pronor.fr/feed/ (HTTP 200)`
  - `https://www.pronor.fr/robots.txt (HTTP 200)`
  - `https://www.pronor.fr/mentions-legales/ (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`https://www.pronor.fr/feed/`, ex. `Sun, 25 Oct 2026 20:15:49 +0000` : *PSG – Olympique Lyon : pronostic et analyse du match*) + page de blog HTML datée (`https://www.pronor.fr/blog-actualite-paris-sportifs/`).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`), L4 (`Disallow: /wp-admin/`) et L16 (`Sitemap`) — `/blog-actualite-paris-sportifs/` et `/feed/` sont autorisés.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L3: # WordPress
  L4: Disallow: /wp-admin/
  L5: Allow: /wp-admin/admin-ajax.php
  L6: Disallow: /wp-login.php
  L8: # WooCommerce
  L9: Disallow: /wp-content/uploads/wc-logs/
  L16: Sitemap: https://www.pronor.fr/sitemap_index.xml
  ```
- **Clause CGU / Mentions légales consultée (`https://www.pronor.fr/mentions-legales/`)** :
  > « RAISON SOCIALE : Pronor : maître en paris sportif, 34 Avenue des Champs Élysées, 75008 Paris – FRANCE, N°Siret : 88366122500010 [...] PROPRIÉTÉ INTELLECTUELLE : Tout le contenu du présent site https://pronor.fr, incluant, de façon non limitative, les graphismes, images, textes, vidéos, animations, sons, logos, gifs et icônes ainsi que leur mise en forme sont la propriété exclusive de la société à l’exception des marques, logos ou contenus appartenant à d’autres sociétés partenaires ou auteurs. Toute reproduction, distribution, modification, adaptation, retransmission ou publication, même partielle, de ces différents éléments est strictement interdite sans l’accord exprès par écrit de Pronor. »
- **Statut lecture automatisée** : Clause de propriété intellectuelle standard ; mentions légales **silencieuses** sur la lecture automatisée.

---

## SRC_055 — Ligue1Pro - Concours Gratuit de Pronostics Ligue 1

- **Catégorie d'audience** : `petit_auteur_inconnu` (`blog_amateur`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.ligue1pro.com/index.php?page=prono (HTTP 200)`
  - `https://www.ligue1pro.com/robots.txt (HTTP 200)`
  - `https://www.ligue1pro.com/index.php?page=team-reglement (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Page HTML publique de pronostics et résultats par journée de Ligue 1 (`https://www.ligue1pro.com/index.php?page=prono`, affichant la journée courante de Ligue 1 2026-2027 et les classements communautaires).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`), L2 (`Disallow: /private/`) et L3 (`Disallow: /config/`) — `/index.php?page=prono` est autorisé.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Disallow: /private/
  L3: Disallow: /config/
  ```
- **Clause CGU / Mentions légales consultée (`https://www.ligue1pro.com/index.php?page=team-reglement`)** :
  > « Fonctionnement : Un Championnat comprenant plusieurs divisions. Chaque Division est composée de 12 Equipes. [...] Objectif : Terminer 1er de la 1ère Division à l'issue de la 34ème journée de Ligue 1 ou terminer dans les 3 premiers de ta division pour monter en division supérieure [...] Ligue1Pro 2026 - Concours Gratuit de pronostic football. »
- **Statut lecture automatisée** : Règlement communautaire sans restriction d'accès automatisé ; CGU **silencieuses** sur la lecture automatisée.

---

## SRC_056 — ForumTFC - Concours Pronostics & Foot Francais

- **Catégorie d'audience** : `petit_auteur_inconnu` (`forum_public`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.forumtfc.net/topic/49574-pronostic-tfc-20262027/ (HTTP 200)`
  - `https://www.forumtfc.net/robots.txt (HTTP 200)`
  - `https://www.forumtfc.net/terms/ (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Fil et forum publics de pronostics Ligue 1 / TFC saison 2026/2027 (`https://www.forumtfc.net/topic/49574-pronostic-tfc-20262027/`, 14 pages de messages horodatés).
- **Ligne(s) de `robots.txt` consultée(s)** : L2 (`User-Agent: *`) et L4-L26 — les sujets publics `/topic/` et sections `/forum/` sont autorisés.
- **Extrait de `robots.txt`** :
  ```text
  L1: # Rules for Invision Community (https://invisioncommunity.com)
  L2: User-Agent: *
  L4: Disallow: /startTopic/
  L5: Disallow: /discover/unread/
  L12: Disallow: /search/
  L15: Disallow: /register/
  L17: Disallow: /login/
  ```
- **Clause CGU / Mentions légales consultée (`https://www.forumtfc.net/terms/`)** :
  > « Conditions d’inscription : Veuillez prendre un moment pour lire ces règles. Rappelez-vous que nous ne sommes pas responsables des messages postés. [...] Vous acceptez, par votre utilisation de ce service, que vous n’utiliserez pas ce site pour écrire des messages qui seraient sciemment faux et/ou diffamatoires [...] Vous acceptez de ne poster aucun contenu sous copyright, sauf si le droit d’auteur est détenu par vous ou par ce site. »
- **Statut lecture automatisée** : Règles de modération de forum Invision Community ; CGU **silencieuses** sur la lecture automatisée.

---

## SRC_057 — ASM-VIZU - Forum AS Monaco & Pronostics Ligue 1 Vizu

- **Catégorie d'audience** : `petit_auteur_inconnu` (`forum_public`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.asm-vizu.net/forum/divers/fvpa/1830854-ligue-1-vizu-2026-2027-8%C3%A8me-journ%C3%A9e-avant-le-23-10-20h45 (HTTP 200)`
  - `https://www.asm-vizu.net/robots.txt (HTTP 200)`
  - `https://www.asm-vizu.net/terms-of-service (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Sujets et messages publics horodatés du concours de pronostics « Ligue 1 - Vizu 2026-2027 » par journée (`https://www.asm-vizu.net/forum/divers/fvpa/1830854-ligue-1-vizu-2026-2027-8%C3%A8me-journ%C3%A9e-avant-le-23-10-20h45`).
- **Ligne(s) de `robots.txt` consultée(s)** : L30 (`User-agent: *`), L31 (`Content-Signal: search=yes,ai-train=no,use=reference`) et L32 (`Allow: /`) — l'accès et l'usage de référence sont autorisés (seul l'entraînement de modèles IA `ai-train` est refusé).
- **Extrait de `robots.txt`** :
  ```text
  L30: User-agent: *
  L31: Content-Signal: search=yes,ai-train=no,use=reference
  L32: Allow: /
  ```
- **Clause CGU / Mentions légales consultée (`https://www.asm-vizu.net/terms-of-service`)** :
  > « Règles du forum : L'inscription à ce forum est gratuite ! Nous insistons sur le fait que vous devez respecter les règles détaillées ci-dessous. Bien que les administrateurs et les modérateurs de ASM-VIZU.net - Forums de l'AS Monaco essaient d'écarter tout message répréhensible de ce forum, il leur est impossible de contrôler tous les messages. Ceux-ci expriment uniquement les opinions de leur auteur. [...] En acceptant ces règles, vous vous engagez à n'écrire aucun message à caractère obscène, vulgaire, discriminatoire, menaçant, diffamatoire, injurieux ou contraire aux lois et règlements en vigueur. »
- **Statut lecture automatisée** : CGU vBulletin **silencieuses** sur la lecture automatisée.

---

## SRC_058 — Forum Le Gruppetto - Section Football & Pronostics

- **Catégorie d'audience** : `petit_auteur_inconnu` (`forum_public`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://legruppetto.fr/forum/viewforum.php?f=21 (HTTP 200)`
  - `https://legruppetto.fr/forum/feed.php?f=21 (HTTP 200)`
  - `https://legruppetto.fr/robots.txt (HTTP 200)`
  - `https://legruppetto.fr/forum/ucp.php?mode=terms (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux Atom public de la section Football (`https://legruppetto.fr/forum/feed.php?f=21`, ex. `2026-10-26T11:35:03+01:00`) + page de liste de sujets horodatés (`https://legruppetto.fr/forum/viewforum.php?f=21`, sous-titre : *Matchs en direct, débats, analyses, Ligues 1 & 2*). Note : la section Pronostics du forum (`f=27`) est également publique.
- **Ligne(s) de `robots.txt` consultée(s)** : L3 (`User-agent: *`) et L4 (`Disallow:` vide) — l'intégralité du forum et de ses flux Atom `feed.php` est autorisée.
- **Extrait de `robots.txt`** :
  ```text
  L1: # START YOAST BLOCK
  L2: # ---------------------------
  L3: User-agent: *
  L4: Disallow:
  L6: Sitemap: https://legruppetto.fr/sitemap_index.xml
  L7: # ---------------------------
  L8: # END YOAST BLOCK
  ```
- **Clause CGU / Mentions légales consultée (`https://legruppetto.fr/forum/ucp.php?mode=terms`)** :
  > « Le Gruppetto - Conditions d’utilisation : En accédant à « Le Gruppetto » (désigné ci-après par « nous », « notre », « nos », « Le Gruppetto », « https://legruppetto.fr/forum »), vous acceptez d’être légalement responsable des conditions suivantes. [...] Nos forums sont développés par phpBB [...] Vous acceptez de ne pas publier de contenu abusif, obscène, vulgaire, diffamatoire, choquant, menaçant, à caractère sexuel ou tout autre contenu qui peut transgresser les lois de votre pays [...] »
- **Statut lecture automatisée** : CGU standard phpBB **silencieuses** sur la lecture automatisée.

---

## SRC_059 — Forum Info-Stades - Section Ligue 1

- **Catégorie d'audience** : `petit_auteur_inconnu` (`forum_public`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.info-stades.fr/forum/viewforum.php?f=1 (HTTP 200)`
  - `https://www.info-stades.fr/robots.txt (HTTP 200)`
  - `https://www.info-stades.fr/forum/ucp.php?mode=terms (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Page de liste de sujets publics de la section Ligue 1 (`https://www.info-stades.fr/forum/viewforum.php?f=1`, 21 sujets par club/stade de Ligue 1 avec messages datés).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`) et L2 (`Crawl-delay: 10`) — aucun `Disallow`, collecte autorisée avec un délai minimal de 10 secondes entre requêtes.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Crawl-delay: 10
  ```
- **Clause CGU / Mentions légales consultée (`https://www.info-stades.fr/forum/ucp.php?mode=terms`)** :
  > « Forum Stades et Supporters - Conditions d’utilisation : En accédant à « Forum Stades et Supporters » (désigné ci-après par « nous », « notre », « nos », « Forum Stades et Supporters » et « https://www.info-stades.fr/forum »), vous acceptez d’être légalement responsable des conditions suivantes. [...] Vous acceptez de ne publier aucun contenu à caractère abusif, obscène, vulgaire, diffamatoire, choquant, menaçant, pornographique, etc. »
- **Statut lecture automatisée** : CGU standard phpBB **silencieuses** sur la lecture automatisée.

---

## SRC_060 — Forum Hex@gones (Supporters OL) - Section Duel-Pronos

- **Catégorie d'audience** : `petit_auteur_inconnu` (`forum_public`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.hexagones.org/forums/forum/27-duel-pronos/ (HTTP 200)`
  - `https://www.hexagones.org/robots.txt (HTTP 200)`
  - `https://www.hexagones.org/terms/ (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Section publique « Duel-pronos » du forum de l'association de supporters lyonnais Hex@gones (`https://www.hexagones.org/forums/forum/27-duel-pronos/`, sujets de pronostics Ligue 1 datés par journée).
- **Ligne(s) de `robots.txt` consultée(s)** : L2 (`User-Agent: *`) et L4-L26 — `/forums/forum/27-duel-pronos/` et les sujets associés ne figurent dans aucun `Disallow`.
- **Extrait de `robots.txt`** :
  ```text
  L1: # Rules for Invision Community (https://invisioncommunity.com)
  L2: User-Agent: *
  L4: Disallow: /startTopic/
  L5: Disallow: /discover/unread/
  L12: Disallow: /search/
  L14: Disallow: /register/
  L16: Disallow: /login/
  ```
- **Clause CGU / Mentions légales consultée (`https://www.hexagones.org/terms/`)** :
  > « Conditions d’inscription : Veuillez prendre un moment pour lire ces règles. Rappelez-vous que nous ne sommes pas responsables des messages postés. [...] Vous acceptez, par votre utilisation de ce service, que vous n’utiliserez pas ce site pour écrire des messages qui seraient sciemment faux et/ou diffamatoires [...] Vous acceptez de ne poster aucun contenu sous copyright, sauf si le droit d’auteur est détenu par vous ou par ce site. [...] Hex@gones - Association de loi 1901 déclarée en préfecture du Rhône. »
- **Statut lecture automatisée** : Conditions d'utilisation Invision Community **silencieuses** sur la lecture automatisée.

---

## SRC_061 — LesViolets.com - Site Independant Supporters Toulouse FC

- **Catégorie d'audience** : `petit_auteur_inconnu` (`blog_amateur`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.lesviolets.com/calendrier-ligue-1 (HTTP 200)`
  - `https://www.lesviolets.com/actu/rss (HTTP 200)`
  - `https://www.lesviolets.com/robots.txt (HTTP 200)`
  - `https://www.lesviolets.com/mentions-legales (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`https://www.lesviolets.com/actu/rss`, ex. `Mon, 26 Oct 2026 13:44:00 GMT`) + page calendrier/résultats Ligue 1 (`https://www.lesviolets.com/calendrier-ligue-1`).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-Agent: *`) et L2 (`Allow: /`) — tout le site est explicitement autorisé.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-Agent: *
  L2: Allow: /
  L3: Sitemap: https://www.lesviolets.com/sitemap.xml
  L4: Sitemap: https://www.lesviolets.com/google-news.xml
  ```
- **Clause CGU / Mentions légales consultée (`https://www.lesviolets.com/mentions-legales`)** :
  > « Mentions légales : Conformément aux dispositions de la loi n° 2004-575 du 21 juin 2004 pour la confiance en l'économie numérique, il est précisé aux utilisateurs du site LesViolets.Com l'identité des différents intervenants dans le cadre de sa réalisation et de son suivi. Edition du site : Le présent site, accessible à l’URL www.lesviolets.com (le « Site »), est édité par : JB, de nationalité Française (France), Hébergement : Le Site est hébergé par la société Scaleway [...] Directeur de publication : Le Directeur de la publication du Site est JBJ. »
- **Statut lecture automatisée** : Mentions légales d'auteur indépendant (personne physique) **silencieuses** sur la lecture automatisée.

---

## SRC_062 — CulturePSG - Media Independant PSG & Ligue 1

- **Catégorie d'audience** : `petit_auteur_inconnu` (`blog_amateur`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.culturepsg.com/news/ligue1 (HTTP 200)`
  - `https://www.culturepsg.com/news?rss (HTTP 200)`
  - `https://www.culturepsg.com/robots.txt (HTTP 200)`
  - `https://www.culturepsg.com/mentionslegales (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`https://www.culturepsg.com/news?rss`, ex. `Mon, 26 Oct 2026 13:49:00 GMT`) + page de liste HTML dédiée Ligue 1 (`https://www.culturepsg.com/news/ligue1`, ex. `26 oct. 2026 : 4 places et un grand 8 pour le PSG face à l'OL ?`).
- **Ligne(s) de `robots.txt` consultée(s)** : L30 (`User-agent: *`), L31 (`Content-Signal: search=yes,ai-train=no,use=reference`) et L32 (`Allow: /`) — accès autorisé pour la collecte et la référence (hors entraînement de modèles IA).
- **Extrait de `robots.txt`** :
  ```text
  L30: User-agent: *
  L31: Content-Signal: search=yes,ai-train=no,use=reference
  L32: Allow: /
  ```
- **Clause CGU / Mentions légales consultée (`https://www.culturepsg.com/mentionslegales`)** :
  > « Mentions Légales : 1. Entreprise : Dénomination / Raison sociale : Philippe Goguet — Catégorie professionnelle : Sole trader — Nom commercial : Philippe Goguet [...] 2. Création du site et responsable de la publication : Dénomination / Raison sociale : Philippe Goguet [...] 3. Hebergement du site : Dénomination / Raison sociale OVH. »
- **Statut lecture automatisée** : Mentions légales d'entrepreneur individuel **silencieuses** sur la lecture automatisée.

---

## SRC_063 — MassaliaLive - Blog & Notes Communautaires OM / Ligue 1

- **Catégorie d'audience** : `petit_auteur_inconnu` (`blog_amateur`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `http://www.massalialive.com/ (HTTP 200)`
  - `http://www.massalialive.com/feed (HTTP 200)`
  - `http://www.massalialive.com/robots.txt (HTTP 200)`
  - `http://www.massalialive.com/mentions-legales (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`http://www.massalialive.com/feed`, ex. `Sun, 25 Oct 2026 19:16:43 +0000` : *J 8 | OM (4-3) HAC : ouf !*) + page d'accueil et liste de comptes-rendus Ligue 1 (`http://www.massalialive.com/`).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`) et L2-L12 (`Disallow: /forum/...`) — la racine `/`, les articles `/compte-rendu/` et le flux `/feed` sont autorisés.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Disallow: /forum/viewtopic.php
  L3: Disallow: /forum/viewforum.php
  L4: Disallow: /forum/index.php?
  L5: Disallow: /forum/posting.php
  L6: Disallow: /forum/search.php?
  ```
- **Clause CGU / Mentions légales consultée (`http://www.massalialive.com/mentions-legales`)** :
  > « Mentions légales : Hébergeur : OVH – 2 rue Kellermann – 59100 Roubaix — Utilisation des cookies — Politique de confidentialité — © Tous Droits Réservés MassaliaLive.com »
- **Statut lecture automatisée** : Mentions légales minimalistes **silencieuses** sur la lecture automatisée.

---

## SRC_064 — AllezParis.fr - Blog Independant Supporters PSG Ligue 1

- **Catégorie d'audience** : `petit_auteur_inconnu` (`blog_amateur`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://allezparis.fr/ligue-1/ (HTTP 200)`
  - `https://allezparis.fr/feed/ (HTTP 200)`
  - `https://allezparis.fr/robots.txt (HTTP 200)`
  - `https://allezparis.fr/mentions-legales/ (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`https://allezparis.fr/feed/`, ex. `Mon, 26 Oct 2026 15:34:00 +0100` : *Marquinhos et Kvaratskhelia choisissent le PSG plutôt que le Ballon d'Or*) + page de rubrique Ligue 1 (`https://allezparis.fr/ligue-1/`).
- **Ligne(s) de `robots.txt` consultée(s)** : L1 (`User-agent: *`) et L2-L4 (`Disallow: /admin/`, `/recherche`, `/api/`) — `/ligue-1/` et `/feed/` sont autorisés.
- **Extrait de `robots.txt`** :
  ```text
  L1: User-agent: *
  L2: Disallow: /admin/
  L3: Disallow: /recherche
  L4: Disallow: /api/
  L6: Sitemap: https://allezparis.fr/sitemap.xml
  L7: Sitemap: https://allezparis.fr/news-sitemap.xml
  ```
- **Clause CGU / Mentions légales consultée (`https://allezparis.fr/mentions-legales/`)** :
  > « Éditeur du site : Le site AllezParis (allezparis.fr) est édité par : Mr Le Roux Guillaume, Adresse : France, 50050901300057 [...] Propriété intellectuelle : L'ensemble des contenus présents sur AllezParis (textes, articles, mise en page, éléments graphiques) est protégé par le droit d'auteur. Toute reproduction, même partielle, est interdite sans autorisation écrite préalable. [...] AllezParis est un média indépendant, sans lien officiel avec le Paris Saint-Germain Football Club. »
- **Statut lecture automatisée** : Clause de droit d'auteur classique d'éditeur indépendant ; mentions légales **silencieuses** sur la lecture automatisée.

---

## SRC_065 — Jeunesfooteux - Blog Independant Actu & Matchs Ligue 1

- **Catégorie d'audience** : `petit_auteur_inconnu` (`blog_amateur`, langue `fr`)
- **Date de vérification** : `2026-10-26`
- **URLs ouvertes** :
  - `https://www.jeunesfooteux.com/categorie/ligue-1 (HTTP 200)`
  - `https://www.jeunesfooteux.com/feed/ (HTTP 200)`
  - `https://www.jeunesfooteux.com/robots.txt (HTTP 200)`
  - `https://www.jeunesfooteux.com/mentions-legales/ (HTTP 200)`
- **Flux RSS/Atom ou page de liste avec publications datées** : Flux RSS 2.0 public (`https://www.jeunesfooteux.com/feed/`, ex. `Mon, 26 Oct 2026 11:30:17 +0000` : *Rennes leader provisoire de la Ligue 1, Camara rappelle la prudence*) + page de liste Ligue 1 (`https://www.jeunesfooteux.com/categorie/ligue-1` avec articles datés `26 octobre 2026`, `25 octobre 2026`, etc.).
- **Ligne(s) de `robots.txt` consultée(s)** : L5 (`User-agent: *`), L6 (`Disallow:`) et L7-L10 (`Disallow: /go/`, `/visit/`, `/search/`, `/?s=`) — `/categorie/ligue-1` et `/feed/` sont autorisés.
- **Extrait de `robots.txt`** :
  ```text
  L1: Sitemap: https://www.jeunesfooteux.com/news-sitemap.xml
  L3: # START YOAST BLOCK
  L5: User-agent: *
  L6: Disallow:
  L7: Disallow: /go/
  L8: Disallow: /visit/
  L9: Disallow: /search/
  L10: Disallow: /?s=
  L12: Sitemap: https://www.jeunesfooteux.com/sitemap_index.xml
  ```
- **Clause CGU / Mentions légales consultée (`https://www.jeunesfooteux.com/mentions-legales/`)** :
  > « ÉDITEUR : Le site www.jeunesfooteux.com est la propriété exclusive de EI Frédéric Le Lay FLL Media, qui l’édite. FLL Media EI Frédéric Le Lay au capital de 100 €, 22 rue Victor Hugo 62153 Souchez, numéro 51114710000024 [...] PROPRIÉTÉ INTELLECTUELLE ET CONTREFAÇONS : Toute reproduction, représentation, modification, publication, adaptation totale ou partielle des éléments du site, quel que soit le moyen ou le procédé utilisé, est interdite, sauf autorisation écrite préalable. »
- **Statut lecture automatisée** : Clause de droit d'auteur classique d'entrepreneur individuel ; mentions légales **silencieuses** sur la lecture automatisée.

---
