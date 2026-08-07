# P0 E1B Five-League Capability Canary V1

## Verdict

```text
E1B_FIVE_LEAGUE_CANARY_MEASURED
E2_CANDIDATE_SET_READY
NEXT_VERY_HIGH_MISSION_STARTS_AT_E2
PASS_AND_HOLD
```

This is a technical canary over ten finished fixtures. It is not a scientific
readiness declaration. No Capability V2 status was promoted to `READY_STRICT`
or `READY_RECONSTRUCTED`, and E2 was not executed.

## Authority and scope

- source main: `b76ac9213853a52f058b33ef3cf4964798f40256`;
- successful workflow: GitHub Actions run `31177349967`, head
  `87d36538ee7773aca1e7a803832fba595b42b605`;
- corrected selection hash:
  `8e3ef9e5e44ef26ef4fd37d884b3290504f2b167b1fceeec669e0ed8684deb22`;
- season: 2024 in all five competitions;
- source access: one exact inventory GET, ten exact receipt GETs and ten exact
  payload GETs in the successful run;
- no LIST, HEAD, prefix scan, provider fallback, SQL or write path.

The first technical run `31176390241` failed closed after one inventory GET,
before any receipt or payload GET, because one stored hash had been transcribed
incorrectly. The corrected selection matched all ten inventory objects on all
eight pinned fields before the final run.

## Frozen fixtures

| Competition | Fixture | Kickoff UTC | Match |
|---|---:|---|---|
| Premier League | 1208033 | 2024-08-24 11:30 | Brighton — Manchester United |
| Premier League | 1208034 | 2024-08-24 14:00 | Crystal Palace — West Ham |
| Ligue 1 | 1213756 | 2024-08-23 18:45 | Paris Saint Germain — Montpellier |
| Ligue 1 | 1213763 | 2024-08-24 15:00 | Lyon — Monaco |
| Bundesliga | 1223990 | 2024-08-30 18:30 | Union Berlin — FC St. Pauli |
| Bundesliga | 1223985 | 2024-08-31 13:30 | VfB Stuttgart — FSV Mainz 05 |
| Serie A | 1223611 | 2024-08-24 16:30 | Parma — AC Milan |
| Serie A | 1223614 | 2024-08-24 16:30 | Udinese — Lazio |
| Liga | 1208504 | 2024-08-23 17:00 | Celta Vigo — Valencia |
| Liga | 1208507 | 2024-08-23 19:30 | Sevilla — Villarreal |

The deterministic order is competition ID, season, kickoff and fixture ID.
Display names are provider-proven identities, never positional IDs rendered as
names.

## Capability result

| Class | Capabilities |
|---|---|
| Measured | TEAM, EVENTS, TEAM_STATISTICS, PLAYER_STATISTICS, DISCIPLINE_GENERIC |
| Measured partial | PLAYER, LINEUP, FORMATION, CALENDAR |
| Blocked by temporality | TEAM_FORM, PLAYER_FORM, STARTER_BASELINE, FATIGUE |
| Blocked by source | STANDINGS |
| Not evaluated | INJURY_CONFIRMED, SUSPENSION_CONFIRMED, ABSENCE_GENERIC |
| Not applicable / local stop | ABSENCE_CAUSE_EXACT |

The E2 candidate set is `TEAM`, `PLAYER`, `LINEUP`, `FORMATION`, `EVENTS`,
`TEAM_STATISTICS`, `PLAYER_STATISTICS`, `DISCIPLINE_GENERIC` and `CALENDAR`.
This is an execution proposal for a larger bounded measurement, not readiness.

## Cross-league observations

| Competition | Player slots | Prior player evidence | Events | Team-stat rows | Player-stat rows | Cards |
|---|---:|---:|---:|---:|---:|---:|
| Premier League | 80/80 | 44/44 | 29 | 72 | 80/80 | 5 |
| Ligue 1 | 80/80 | 41/44 | 38 | 72 | 80/80 | 11 |
| Bundesliga | 80/80 | 43/44 | 37 | 72 | 80/80 | 10 |
| Serie A | 89/89 | 44/44 | 34 | 72 | 89/89 | 9 |
| Liga | 91/91 | 43/44 | 41 | 72 | 91/91 | 11 |

Event and discipline counts have no invented expected denominator. Team
statistics use unique fixture-team buckets; player statistics use unique
fixture-team-player identities. Form, starters and fatigue remain blocked by
strict-as-of temporality even when post-match records are present.

## UNKNOWN and immutable E1A evidence

`UNKNOWN` is retained as a first-class value. No implicit conversion to false,
zero, injury or suspension occurred. The new E1B absence read count is zero.

The historical E1A partition remains exactly:

```text
3036 = 2681 injury-confirmed + 206 suspension-confirmed + 149 UNKNOWN
ABSENCE_CAUSE_EXACT = STOPPED_LOCAL_CAMPAIGN
```

The 149 historical unknowns are recorded once in the E1A partition and UNKNOWN
profile. They are not projected into the five E1B league rows.

## Costs and replay

Successful run:

- 21 logical GETs: 1 inventory + 10 receipts + 10 payloads;
- 1,107,479 bytes read;
- 15.667988 seconds of measured read-and-build time;
- physical requests: `UNKNOWN`;
- 0 cache hits, provider calls, R2 writes/deletes, SQL queries, odds credits,
  deployments, publications, real bets or promotions.

Mission total across both attempts is 22 logical GETs: the successful 21 plus
the failed attempt's single bootstrap GET. Its byte count was not emitted before
the fail-closed stop and remains unknown.

The two in-memory generations were byte-identical and used zero additional R2
GETs. The corrected committed report hashes are recorded in
`e1b-replay-verification-v1.json`.

## Artifacts

- `reports/evidence/e1b/e1b-selection-manifest-v1.json`
- `reports/evidence/e1b/e1b-measurement-v1.json`
- `reports/evidence/e1b/e1b-capability-matrix-v1.json`
- `reports/evidence/e1b/e1b-league-comparison-v1.json`
- `reports/evidence/e1b/e1b-unknown-profile-v1.json`
- `reports/evidence/e1b/e1b-replay-verification-v1.json`
- `reports/evidence/e1b/e1b-costs-v1.json`
- `reports/evidence/e1b/e1b-dashboard-contract-v1.json`

No raw payload is tracked. The dashboard contract is data-only; no frontend or
deployment was produced.
