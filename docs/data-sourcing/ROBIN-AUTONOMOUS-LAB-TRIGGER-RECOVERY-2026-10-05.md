# Robin — reprise autonome du déclenchement (2026-10-05)

## Autorité propriétaire

Le complément propriétaire reçu le 5 octobre 2026 autorise C0, unique writer Git,
à poursuivre la mission `ROBIN_AUTONOMOUS_LAB_20261004` pendant la nuit et à
remplacer le déclenchement natif `schedule` comme horloge primaire lorsqu'il ne
matérialise pas de run. Le résultat reste une collecte automatique indépendante
du poste du propriétaire, durablement comptabilisée, relue depuis R2 et rendue
consultable sans pari, achat, backfill, promotion scientifique ni nouveau
fournisseur.

Cette autorité est un overlay append-only. Elle ne modifie ni les anciennes
autorisations, ni les anciennes preuves, ni les données historiques. Elle ne
réinitialise aucun compteur ou budget.

## Faits à la coupure

- Le workflow établi `321915839` n'a matérialisé aucun nouveau run pendant la
  fenêtre supplémentaire de trente minutes close le 4 octobre 2026 à 23:29:21Z.
- L'ancien workflow `374470410` a matérialisé tardivement le run naturel
  `37231859661`, démarré à 20:22:46Z. Son artifact normalisé a été conservé et
  vérifié, mais il contient zéro nouvelle capture et un tableau historique
  explicitement `CARRY_FORWARD_STALE`.
- Les cinq branches de ce run ont échoué avant transport avec le code expurgé
  `RECURRING_DNS_RESOLUTION_EXPIRED`. Aucune requête fournisseur nouvelle n'a été
  émise par ce run.
- La comptabilité conservatrice cumulée devient 21 requêtes et 44 crédits
  fournisseur : 16/34 historiques plus la réservation ambiguë 5/10. Le débit
  fournisseur réel du run échoué est non mesuré. Les crédits IA sont non mesurés.

## Mécanisme autorisé

Le workflow établi reste l'unique circuit fournisseur actif. Il peut recevoir un
`workflow_dispatch` auto-émis avec son `GITHUB_TOKEN`. Avant tout bootstrap, C0
crée puis relit l'environnement exact `robin-autonomous-relay-v1`, limité à la
branche `main`, sans secret, avec un wait timer d'une minute pour la sonde puis de
soixante minutes pour la collecte récurrente. Un seed manuel est uniquement un
bootstrap diagnostique et ne prouve jamais l'autonomie.

Avant d'activer la collecte, deux sauts automatiques distincts doivent être
observés sans secret, sans accès R2 et sans appel fournisseur. Les jobs de
contrôle bootstrap, relay et watchdog portent seuls `actions: write`, sans secret
fournisseur ni R2; le job de collecte reste séparé avec accès en lecture aux
Actions et au contenu. Le relais arme son successeur avant toute collecte.
Le `schedule` natif devient un watchdog sans secret fournisseur ni R2. Sous sa
concurrence de contrôle unique, il ne réarme qu'un relais identique et seulement
si aucun run relay n'est queued ou in progress. L'idempotence des
créneaux R2 de deux heures et la comptabilité compare-and-swap restent
obligatoires, notamment si un événement ancien arrive tardivement.

Le runtime peut corriger le défaut d'ordre temporel DNS confirmé et les autres
défauts directement rencontrés, tout en conservant TLS, les délais, la fermeture
finale, les diagnostics expurgés, les données et l'historique des échecs.

## Bornes

- Les plafonds parent restent 140 requêtes / 280 crédits fournisseur sur 24 h et
  4 000 requêtes / 8 000 crédits sur 30 jours glissants.
- Toute tentative de transport est comptée avant émission et le head R2 est relu
  avant admission. Une branche indisponible n'arrête pas les autres.
- Le travail actif supplémentaire est limité à trois heures, attente passive
  exclue. Un point de passage est préparé pour le 5 octobre 2026 à 08:00 Europe/Paris.
- Les verrous scientifiques et de sécurité restent inchangés. La stabilité de
  vingt-quatre heures reste à observer tant que la durée n'est pas écoulée.

## Critère de passage

Le mode collecte n'est activé qu'après une décision Council append-only
`PASS_AND_SCALE` fondée sur les deux sauts provider-free, une revue indépendante
consolidée, les contrôles obligatoires et la lecture du head comptable.
Les métriques réelles ultérieures doivent être liées à des claim IDs append-only.
