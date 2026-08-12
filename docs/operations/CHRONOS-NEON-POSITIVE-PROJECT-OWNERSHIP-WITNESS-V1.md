# Chronos Neon Positive Project Ownership Witness V1

This contract changes only the ordering of GET-only identity discovery when
`NEON_PROJECT_ID` is absent. It does not create that variable, modify a secret,
wake or suspend a compute, create a branch, execute SQL during development, or
authorize migration `0014`.

## Official Neon contract

The implementation is grounded in the current official Neon API reference and
OpenAPI specification:

- `GET /projects` lists projects and returns the next project cursor as
  `pagination.cursor`:
  <https://api-docs.neon.tech/reference/listprojects>.
- `GET /projects/{project_id}` returns scoped project details, including the
  project ID and owner information:
  <https://api-docs.neon.tech/reference/getproject>.
- `GET /projects/{project_id}/endpoints` lists endpoints belonging to one
  project:
  <https://api-docs.neon.tech/reference/listprojectendpoints>.
- `GET /projects/{project_id}/endpoints/{endpoint_id}` retrieves an endpoint
  under that same project scope:
  <https://api-docs.neon.tech/reference/getprojectendpoint>.
- `GET /projects/{project_id}/branches` uses its distinct
  `pagination.next` continuation contract:
  <https://api-docs.neon.tech/reference/listprojectbranches>.
- `GET /projects/{project_id}/branches/{branch_id}/endpoints` lists endpoints
  under the project and branch scopes and documents at most one read-write
  endpoint per branch:
  <https://api-docs.neon.tech/reference/listprojectbranchendpoints>.
- The release OpenAPI specification defines `Endpoint.project_id`,
  `Endpoint.branch_id`, `Endpoint.host`, `Endpoint.type`, `current_state`,
  `pooler_enabled`, and `disabled`:
  <https://neon.com/api_spec/release/v2.json>.

These sources establish scoped resource relationships. They do not establish
global endpoint-host uniqueness across every project accessible to an API key,
so the code makes no such claim.

## Candidate-first proof

For each validated project page, the preflight validates the project IDs,
owner IDs, duplicate prohibition, empty `unavailable_project_ids`, and project
pagination structure. It then lists the endpoint inventory for every project on
that page, in response order, before considering the next project cursor.

An endpoint becomes a candidate only when its case-normalized host equals the
already validated DSN host exactly and its project, endpoint, and branch IDs are
valid and concordant. It must be `read_write`, disabled must be false, and the
inventory must describe a non-pooled endpoint. Names, timestamps, regions,
partial hosts, and list position are never selection signals.

Zero matches permit cursor continuation. A repeated cursor still fails with
`project_cursor_cycle`. More than one exact candidate on the current page fails
with `positive_endpoint_match_not_unique`. If exactly one candidate exists, no
later project page is requested; the preflight instead requires all of these
positive witnesses:

1. endpoint detail under the same project, with matching endpoint, project,
   branch, and host, and an active, enabled, non-pooled read-write state;
2. project detail with the same project ID and owner relationship;
3. exactly one matching, ready or active default branch;
4. branch-scoped endpoint inventory containing the same endpoint ID, host,
   branch, and read-write type.

Only that complete chain yields
`POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN` and
`NEON_PROJECT_IDENTITY_PROVEN`, using identity path
`POSITIVE_ENDPOINT_WITNESS`.

## Honest completeness and budgets

A successful early witness reports
`project_inventory_exhaustive=false` and
`identity_proof_mode=POSITIVE_OWNERSHIP`. The report never labels an unrequested
continuation as exhausted.

`MAX_NEON_GETS` remains 25 and automatic retry remains disabled. The worst-case
reserved positive suffix is 6 GETs: one endpoint detail, one project detail, up
to three branch pages, and one branch-endpoint inventory. With at most three
project pages, at most 16 candidate endpoint inventories fit inside the hard
ceiling. Any response requiring more proof fails before GET 26.

## Reviews and effect boundary

DP5 finds no hidden external effect: every pre-SQL operation is a Neon control
plane GET, endpoint start/suspend routes do not exist in the client, and SQL is
unreachable until endpoint detail proves `current_state=active`.

DP6 accepts the witness because the DSN host is bound through two independent
scoped API relationships: project to endpoint detail, and project to branch to
branch endpoint. This proves ownership without claiming account-wide negative
uniqueness.

C4 verifies that page position, partial hosts, mismatched endpoint/project/
branch fields, missing default status, and branch-endpoint disagreement all
fail closed; a no-match cursor cycle cannot be ignored; incomplete project
pagination is reported honestly; and reports contain only SHA-256 identity
fingerprints. P0 and P1 are zero.

Before merge, Neon GET, Neon mutation, production SQL, R2, provider, purchase,
secret update, variable update, and migration counters must all remain zero.
After merge and green quiescent `main`, the manual read-only preflight may be
dispatched exactly once for the exact new main SHA. Even a GO verdict only
authorizes a later, separate migration decision.
