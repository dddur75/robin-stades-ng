"""Pure read-only Neon and PostgreSQL preflight for a future Chronos migration.

The command emits a sanitized report. It never creates a Neon resource, never
executes Alembic, and never submits SQL outside an explicitly read-only
transaction. Expected NO-GO outcomes are successful observations, not retries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qsl, urlencode, urlparse

import psycopg
import requests
from psycopg.rows import dict_row

from robin.chronos_production import (
    EXPECTED_BEFORE_REVISION,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    DirectPostgresTarget,
    libpq_environment_variable_names,
    validate_data_torrent_authority,
    validate_direct_postgres_url,
)

NEON_API = "https://console.neon.tech/api/v2"
EXPECTED_REVISION = EXPECTED_BEFORE_REVISION
REPORT_SCHEMA = "chronos-neon-pure-readonly-preflight-v4"
GO_VERDICT = "CHRONOS_NEON_MIGRATION_READY_FOR_SEPARATE_AUTHORIZATION"
NO_GO_VERDICT = "CHRONOS_NEON_MIGRATION_NOT_AUTHORIZED"
MAX_NEON_GETS = 25
PROJECT_PAGE_LIMIT = 400
MAX_PROJECT_PAGES = 3
MAX_BRANCH_PAGES = 3
MAX_MEMBER_PAGES = 3
MAX_BRANCH_PAGE = 10_000
POSITIVE_WITNESS_GET_RESERVE = 1 + 1 + MAX_BRANCH_PAGES + 1
OWNER_SCOPE_GET_RESERVE = 2
MAX_PROJECTS_FOR_ENDPOINT_DISCOVERY = (
    MAX_NEON_GETS - MAX_PROJECT_PAGES - POSITIVE_WITNESS_GET_RESERVE - OWNER_SCOPE_GET_RESERVE
) // 2
MAX_PROJECT_ITEMS = MAX_PROJECTS_FOR_ENDPOINT_DISCOVERY
MAX_BRANCH_ITEMS = MAX_BRANCH_PAGE * MAX_BRANCH_PAGES
MAX_SQL_STATEMENTS = 25
EXPECTED_STATEMENT_TIMEOUT_MS = 15_000
EXPECTED_LOCK_TIMEOUT_MS = 3_000
SUPPORTED_NEON_POSTGRESQL_MAJORS = frozenset({14, 15, 16, 17, 18, 19})
SUPPORTED_CHRONOS_POSTGRESQL_MAJORS = frozenset({16})
BOOTSTRAP_AUTHORITY = "chronos_bootstrap_authority"
READONLY_STARTUP_OPTIONS = (
    "-c default_transaction_read_only=on "
    "-c statement_timeout=15000 -c lock_timeout=3000 "
    "-c search_path=pg_catalog"
)

NO_GO_REASONS = frozenset(
    {
        "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        "DIRECT_ENDPOINT_NOT_PROVEN",
        "UNEXPECTED_DATABASE_REVISION",
        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
        "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
        "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE",
        "ENDPOINT_STATE_UNSUPPORTED",
        "RECOVERY_BRANCH_NOT_FEASIBLE",
        "PURCHASE_REQUIRED",
        "SECRET_MISSING",
    }
)

SQL_STATEMENTS: tuple[str, ...] = (
    "BEGIN READ ONLY",
    "SHOW default_transaction_read_only",
    "SHOW transaction_read_only",
    "SHOW statement_timeout",
    "SHOW lock_timeout",
    "SHOW search_path",
    "SELECT pg_catalog.current_database(), SESSION_USER AS session_user, "
    "CURRENT_USER AS current_user, "
    "pg_catalog.current_setting('server_version') AS postgresql_version, "
    "pg_catalog.current_setting('server_version_num') AS postgresql_version_num",
    "SELECT ssl FROM pg_catalog.pg_stat_ssl WHERE pid=pg_catalog.pg_backend_pid()",
    "WITH actor AS MATERIALIZED (SELECT r.oid AS role_oid,r.rolsuper "
    "FROM pg_catalog.pg_roles r WHERE r.rolname=current_user), "
    "targets AS MATERIALIZED (SELECT a.*,n.oid AS schema_oid,"
    "n.nspowner AS schema_owner_oid,CASE WHEN schema_owner.rolname="
    "'pg_database_owner' THEN current_db.datdba ELSE n.nspowner END AS "
    "effective_schema_owner_oid,n.nspacl AS schema_acl,c.oid AS table_oid,"
    "c.relowner AS table_owner_oid,CASE WHEN table_owner.rolname="
    "'pg_database_owner' THEN current_db.datdba ELSE c.relowner END AS "
    "effective_table_owner_oid,c.relacl AS table_acl,(c.oid IS NOT NULL "
    "AND c.relkind='r' AND c.relpersistence='p' AND NOT c.relispartition "
    "AND c.relam=(SELECT am.oid FROM pg_catalog.pg_am am "
    "WHERE am.amname='heap' AND am.amtype='t') "
    "AND c.reloftype=0 AND c.reloptions IS NULL AND c.reltoastrelid=0 "
    "AND c.relreplident='d' AND c.reltablespace=0 AND c.relnatts=1 "
    "AND NOT c.relhasrules AND NOT c.relhastriggers "
    "AND NOT c.relhassubclass "
    "AND NOT c.relrowsecurity AND NOT c.relforcerowsecurity "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_rewrite rw "
    "WHERE rw.ev_class=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger tg "
    "WHERE tg.tgrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_inherits i "
    "WHERE i.inhparent=c.oid OR i.inhrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_policy pol "
    "WHERE pol.polrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_publication_tables pub "
    "WHERE pub.schemaname='public' AND pub.tablename='alembic_version') "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_subscription_rel subrel "
    "WHERE subrel.srrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend dep "
    "WHERE dep.objsubid=0 "
    "AND dep.refclassid='pg_catalog.pg_extension'::pg_catalog.regclass "
    "AND dep.deptype='e' AND ((dep.classid="
    "'pg_catalog.pg_class'::pg_catalog.regclass AND dep.objid=c.oid) OR "
    "(dep.classid='pg_catalog.pg_namespace'::pg_catalog.regclass "
    "AND dep.objid=n.oid) OR "
    "(dep.classid='pg_catalog.pg_type'::pg_catalog.regclass AND dep.objid IN "
    "(c.reltype,(SELECT row_type.typarray FROM pg_catalog.pg_type row_type "
    "WHERE row_type.oid=c.reltype))))) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend auto_dep "
    "JOIN pg_catalog.pg_index auto_idx ON auto_idx.indexrelid=auto_dep.objid "
    "WHERE auto_dep.objsubid=0 "
    "AND auto_dep.refclassid='pg_catalog.pg_extension'::pg_catalog.regclass "
    "AND auto_dep.deptype='x' "
    "AND auto_dep.classid='pg_catalog.pg_class'::pg_catalog.regclass "
    "AND auto_idx.indrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_statistic_ext stx "
    "WHERE stx.stxrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_event_trigger evt "
    "WHERE evt.evtenabled<>'D') "
    "AND (SELECT pg_catalog.count(*) FROM pg_catalog.pg_attribute col "
    "WHERE col.attrelid=c.oid AND col.attnum>0 AND NOT col.attisdropped)=1 "
    "AND att.attnum=1 AND NOT att.attisdropped AND att.attnotnull "
    "AND att.attgenerated='' AND att.attidentity='' AND att.atttypid IN "
    "('pg_catalog.varchar'::pg_catalog.regtype) AND att.atttypmod=36 "
    "AND att.attcollation=(SELECT typcollation FROM pg_catalog.pg_type "
    "WHERE oid='pg_catalog.varchar'::pg_catalog.regtype) "
    "AND att.attstorage=(SELECT typstorage FROM pg_catalog.pg_type "
    "WHERE oid='pg_catalog.varchar'::pg_catalog.regtype) "
    "AND att.attcompression='' AND att.attstattarget=-1 "
    "AND att.attoptions IS NULL AND NOT att.atthasmissing "
    "AND att.attmissingval IS NULL AND NOT att.atthasdef "
    "AND att.attfdwoptions IS NULL AND att.attislocal "
    "AND att.attinhcount=0 AND att.attndims=0 "
    "AND pg_catalog.cardinality(coalesce("
    "att.attacl,'{}'::pg_catalog.aclitem[]))=0 "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_attrdef ad "
    "WHERE ad.adrelid=c.oid) "
    "AND (SELECT pg_catalog.count(*) FROM pg_catalog.pg_constraint con "
    "WHERE con.conrelid=c.oid)=1 "
    "AND EXISTS (SELECT 1 FROM pg_catalog.pg_constraint con "
    "JOIN pg_catalog.pg_index idx ON idx.indexrelid=con.conindid "
    "JOIN pg_catalog.pg_class idx_class ON idx_class.oid=idx.indexrelid "
    "JOIN pg_catalog.pg_am idx_am ON idx_am.oid=idx_class.relam "
    "JOIN pg_catalog.pg_opclass opclass ON opclass.oid=idx.indclass[0] "
    "JOIN pg_catalog.pg_namespace opclass_ns "
    "ON opclass_ns.oid=opclass.opcnamespace "
    "WHERE con.conrelid=c.oid AND con.conname='alembic_version_pkc' "
    "AND con.contype='p' AND con.conkey=ARRAY[att.attnum]::pg_catalog.int2[] "
    "AND NOT con.condeferrable AND NOT con.condeferred AND con.convalidated "
    "AND con.conparentid=0 AND con.coninhcount=0 AND con.conislocal "
    "AND con.connoinherit AND idx.indrelid=c.oid AND idx.indisunique "
    "AND idx.indisprimary AND idx.indisvalid AND idx.indisready "
    "AND idx.indislive AND idx.indpred IS NULL AND idx.indexprs IS NULL "
    "AND NOT idx.indisclustered AND NOT idx.indcheckxmin "
    "AND NOT idx.indnullsnotdistinct "
    "AND idx.indnatts=1 AND idx.indnkeyatts=1 "
    "AND idx.indkey[0]=att.attnum AND idx.indcollation[0]=att.attcollation "
    "AND idx_class.relname='alembic_version_pkc' "
    "AND idx_class.relnamespace=n.oid AND idx_class.relowner=c.relowner "
    "AND idx_class.relkind='i' AND idx_class.relpersistence='p' "
    "AND NOT idx_class.relispartition AND idx_class.reloptions IS NULL "
    "AND idx_class.reltablespace=0 AND idx_am.amname='btree' "
    "AND idx_am.amtype='i' AND opclass.opcmethod=idx_am.oid "
    "AND opclass.opcname='text_ops' AND opclass.opcdefault "
    "AND opclass_ns.nspname='pg_catalog') "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint incoming "
    "WHERE incoming.confrelid=c.oid AND incoming.conrelid<>c.oid) "
    "AND (SELECT pg_catalog.count(*) FROM pg_catalog.pg_index ix "
    "WHERE ix.indrelid=c.oid)=1 "
    "AND NOT EXISTS (WITH RECURSIVE global_writer_descendants(member) AS ("
    "SELECT membership.member FROM pg_catalog.pg_auth_members membership "
    "JOIN pg_catalog.pg_roles global_writer "
    "ON global_writer.oid=membership.roleid "
    "WHERE global_writer.rolname='pg_write_all_data' UNION SELECT "
    "nested_membership.member FROM pg_catalog.pg_auth_members "
    "nested_membership JOIN global_writer_descendants descendants "
    "ON nested_membership.roleid=descendants.member) SELECT 1 FROM "
    "global_writer_descendants descendants JOIN pg_catalog.pg_roles "
    "member_role ON member_role.oid=descendants.member WHERE "
    "descendants.member<>a.role_oid AND member_role.rolcanlogin) "
    "AND NOT EXISTS (WITH RECURSIVE protected_descendants(member) AS ("
    "SELECT membership.member FROM pg_catalog.pg_auth_members membership "
    "WHERE membership.roleid IN (a.role_oid,n.nspowner,CASE WHEN "
    "schema_owner.rolname='pg_database_owner' THEN current_db.datdba "
    "ELSE n.nspowner END,c.relowner,CASE WHEN table_owner.rolname="
    "'pg_database_owner' THEN current_db.datdba ELSE c.relowner END,"
    "(SELECT platform_role.oid FROM pg_catalog.pg_roles platform_role "
    "WHERE platform_role.rolname='neon_superuser')) UNION SELECT "
    "nested_membership.member FROM pg_catalog.pg_auth_members "
    "nested_membership JOIN protected_descendants descendants "
    "ON nested_membership.roleid=descendants.member) SELECT 1 FROM "
    "protected_descendants descendants JOIN pg_catalog.pg_roles member_role "
    "ON member_role.oid=descendants.member WHERE descendants.member<>a.role_oid "
    "AND member_role.rolcanlogin) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.aclexplode("
    "coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) acl "
    "LEFT JOIN pg_catalog.pg_roles platform_grantee "
    "ON platform_grantee.oid=acl.grantee "
    "WHERE acl.grantee<>a.role_oid AND acl.grantee<>c.relowner AND NOT ("
    "platform_grantee.rolname='neon_superuser' "
    "AND NOT platform_grantee.rolcanlogin "
    "AND pg_catalog.pg_has_role(a.role_oid,platform_grantee.oid,'MEMBER') "
    "AND NOT EXISTS (WITH RECURSIVE platform_descendants(member) AS ("
    "SELECT platform_membership.member FROM pg_catalog.pg_auth_members "
    "platform_membership WHERE platform_membership.roleid=platform_grantee.oid "
    "UNION SELECT nested_membership.member FROM pg_catalog.pg_auth_members "
    "nested_membership JOIN platform_descendants descendants "
    "ON nested_membership.roleid=descendants.member) SELECT 1 FROM "
    "platform_descendants WHERE member<>a.role_oid) "
    "AND acl.privilege_type IN ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE',"
    "'REFERENCES','TRIGGER') AND acl.is_grantable)) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.aclexplode("
    "coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) acl "
    "WHERE acl.privilege_type='CREATE' AND acl.grantee<>a.role_oid "
    "AND acl.grantee<>n.nspowner)) AS table_safe "
    "FROM actor a LEFT JOIN pg_catalog.pg_namespace n ON n.nspname='public' "
    "LEFT JOIN pg_catalog.pg_roles schema_owner ON schema_owner.oid=n.nspowner "
    "LEFT JOIN pg_catalog.pg_database current_db ON "
    "current_db.datname=pg_catalog.current_database() "
    "LEFT JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid "
    "AND c.relname='alembic_version' LEFT JOIN pg_catalog.pg_roles table_owner "
    "ON table_owner.oid=c.relowner LEFT JOIN pg_catalog.pg_attribute att "
    "ON att.attrelid=c.oid AND att.attname='version_num') SELECT "
    "schema_oid,table_oid,schema_oid IS NOT NULL AS public_schema_exists, "
    "table_safe AS alembic_version_is_plain_permanent_table, "
    "CASE WHEN schema_oid IS NULL THEN false WHEN rolsuper THEN true "
    "WHEN schema_owner_oid=role_oid OR pg_catalog.pg_has_role("
    "role_oid,schema_owner_oid,'SET') THEN true ELSE EXISTS (SELECT 1 FROM "
    "pg_catalog.aclexplode(coalesce(schema_acl,pg_catalog.acldefault("
    "'n',schema_owner_oid))) acl WHERE acl.grantee=role_oid "
    "AND acl.privilege_type='USAGE' AND acl.is_grantable) END "
    "AS schema_usage_grantable, CASE WHEN schema_oid IS NULL THEN false "
    "WHEN rolsuper THEN true WHEN schema_owner_oid=role_oid OR "
    "pg_catalog.pg_has_role(role_oid,schema_owner_oid,'SET') THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(schema_acl,"
    "pg_catalog.acldefault('n',schema_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='CREATE' "
    "AND acl.is_grantable) END AS schema_create_grantable, "
    "CASE WHEN NOT table_safe THEN false WHEN rolsuper THEN "
    "effective_table_owner_oid=role_oid WHEN effective_table_owner_oid="
    "role_oid THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(table_acl,"
    "pg_catalog.acldefault('r',table_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='SELECT' "
    "AND acl.is_grantable) END AS table_select_grantable, "
    "CASE WHEN NOT table_safe THEN false WHEN rolsuper THEN "
    "effective_table_owner_oid=role_oid WHEN effective_table_owner_oid="
    "role_oid THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(table_acl,"
    "pg_catalog.acldefault('r',table_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='INSERT' "
    "AND acl.is_grantable) END AS table_insert_grantable, "
    "CASE WHEN NOT table_safe THEN false WHEN rolsuper THEN "
    "effective_table_owner_oid=role_oid WHEN effective_table_owner_oid="
    "role_oid THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(table_acl,"
    "pg_catalog.acldefault('r',table_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='UPDATE' "
    "AND acl.is_grantable) END AS table_update_grantable, "
    "CASE WHEN NOT table_safe THEN false WHEN rolsuper THEN "
    "effective_table_owner_oid=role_oid WHEN effective_table_owner_oid="
    "role_oid THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(table_acl,"
    "pg_catalog.acldefault('r',table_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='DELETE' "
    "AND acl.is_grantable) END AS table_delete_grantable, "
    "NOT EXISTS (WITH RECURSIVE authority_descendants(member) AS ("
    "SELECT membership.member FROM pg_catalog.pg_auth_members membership "
    "WHERE membership.roleid IN (targets.role_oid,targets.schema_owner_oid,"
    "targets.effective_schema_owner_oid,targets.table_owner_oid,"
    "targets.effective_table_owner_oid) UNION SELECT nested_membership.member FROM "
    "pg_catalog.pg_auth_members nested_membership JOIN authority_descendants "
    "descendants ON nested_membership.roleid=descendants.member) SELECT 1 "
    "FROM authority_descendants WHERE member<>targets.role_oid) "
    "AS authority_role_memberships_clean FROM targets",
    "LOCK TABLE ONLY public.alembic_version IN SHARE MODE",
    "WITH actor AS MATERIALIZED (SELECT r.oid AS role_oid,r.rolsuper "
    "FROM pg_catalog.pg_roles r WHERE r.rolname=CURRENT_USER), "
    "targets AS MATERIALIZED (SELECT a.*,n.oid AS schema_oid,"
    "n.nspowner AS schema_owner_oid,CASE WHEN schema_owner.rolname="
    "'pg_database_owner' THEN current_db.datdba ELSE n.nspowner END AS "
    "effective_schema_owner_oid,n.nspacl AS schema_acl,c.oid AS table_oid,"
    "c.relowner AS table_owner_oid,CASE WHEN table_owner.rolname="
    "'pg_database_owner' THEN current_db.datdba ELSE c.relowner END AS "
    "effective_table_owner_oid,c.relacl AS table_acl,(c.oid IS NOT NULL "
    "AND c.relkind='r' AND c.relpersistence='p' AND NOT c.relispartition "
    "AND c.relam=(SELECT am.oid FROM pg_catalog.pg_am am "
    "WHERE am.amname='heap' AND am.amtype='t') "
    "AND c.reloftype=0 AND c.reloptions IS NULL AND c.reltoastrelid=0 "
    "AND c.relreplident='d' AND c.reltablespace=0 AND c.relnatts=1 "
    "AND NOT c.relhasrules AND NOT c.relhastriggers "
    "AND NOT c.relhassubclass "
    "AND NOT c.relrowsecurity AND NOT c.relforcerowsecurity "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_rewrite rw "
    "WHERE rw.ev_class=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger tg "
    "WHERE tg.tgrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_inherits i "
    "WHERE i.inhparent=c.oid OR i.inhrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_policy pol "
    "WHERE pol.polrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_publication_tables pub "
    "WHERE pub.schemaname='public' AND pub.tablename='alembic_version') "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_subscription_rel subrel "
    "WHERE subrel.srrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend dep "
    "WHERE dep.objsubid=0 "
    "AND dep.refclassid='pg_catalog.pg_extension'::pg_catalog.regclass "
    "AND dep.deptype='e' AND ((dep.classid="
    "'pg_catalog.pg_class'::pg_catalog.regclass AND dep.objid=c.oid) OR "
    "(dep.classid='pg_catalog.pg_namespace'::pg_catalog.regclass "
    "AND dep.objid=n.oid) OR "
    "(dep.classid='pg_catalog.pg_type'::pg_catalog.regclass AND dep.objid IN "
    "(c.reltype,(SELECT row_type.typarray FROM pg_catalog.pg_type row_type "
    "WHERE row_type.oid=c.reltype))))) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend auto_dep "
    "JOIN pg_catalog.pg_index auto_idx ON auto_idx.indexrelid=auto_dep.objid "
    "WHERE auto_dep.objsubid=0 "
    "AND auto_dep.refclassid='pg_catalog.pg_extension'::pg_catalog.regclass "
    "AND auto_dep.deptype='x' "
    "AND auto_dep.classid='pg_catalog.pg_class'::pg_catalog.regclass "
    "AND auto_idx.indrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_statistic_ext stx "
    "WHERE stx.stxrelid=c.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_event_trigger evt "
    "WHERE evt.evtenabled<>'D') "
    "AND (SELECT pg_catalog.count(*) FROM pg_catalog.pg_attribute col "
    "WHERE col.attrelid=c.oid AND col.attnum>0 AND NOT col.attisdropped)=1 "
    "AND att.attnum=1 AND NOT att.attisdropped AND att.attnotnull "
    "AND att.attgenerated='' AND att.attidentity='' AND att.atttypid IN "
    "('pg_catalog.varchar'::pg_catalog.regtype) AND att.atttypmod=36 "
    "AND att.attcollation=(SELECT typcollation FROM pg_catalog.pg_type "
    "WHERE oid='pg_catalog.varchar'::pg_catalog.regtype) "
    "AND att.attstorage=(SELECT typstorage FROM pg_catalog.pg_type "
    "WHERE oid='pg_catalog.varchar'::pg_catalog.regtype) "
    "AND att.attcompression='' AND att.attstattarget=-1 "
    "AND att.attoptions IS NULL AND NOT att.atthasmissing "
    "AND att.attmissingval IS NULL AND NOT att.atthasdef "
    "AND att.attfdwoptions IS NULL AND att.attislocal "
    "AND att.attinhcount=0 AND att.attndims=0 "
    "AND pg_catalog.cardinality(coalesce("
    "att.attacl,'{}'::pg_catalog.aclitem[]))=0 "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_attrdef ad "
    "WHERE ad.adrelid=c.oid) "
    "AND (SELECT pg_catalog.count(*) FROM pg_catalog.pg_constraint con "
    "WHERE con.conrelid=c.oid)=1 "
    "AND EXISTS (SELECT 1 FROM pg_catalog.pg_constraint con "
    "JOIN pg_catalog.pg_index idx ON idx.indexrelid=con.conindid "
    "JOIN pg_catalog.pg_class idx_class ON idx_class.oid=idx.indexrelid "
    "JOIN pg_catalog.pg_am idx_am ON idx_am.oid=idx_class.relam "
    "JOIN pg_catalog.pg_opclass opclass ON opclass.oid=idx.indclass[0] "
    "JOIN pg_catalog.pg_namespace opclass_ns "
    "ON opclass_ns.oid=opclass.opcnamespace "
    "WHERE con.conrelid=c.oid AND con.conname='alembic_version_pkc' "
    "AND con.contype='p' AND con.conkey=ARRAY[att.attnum]::pg_catalog.int2[] "
    "AND NOT con.condeferrable AND NOT con.condeferred AND con.convalidated "
    "AND con.conparentid=0 AND con.coninhcount=0 AND con.conislocal "
    "AND con.connoinherit AND idx.indrelid=c.oid AND idx.indisunique "
    "AND idx.indisprimary AND idx.indisvalid AND idx.indisready "
    "AND idx.indislive AND idx.indpred IS NULL AND idx.indexprs IS NULL "
    "AND NOT idx.indisclustered AND NOT idx.indcheckxmin "
    "AND NOT idx.indnullsnotdistinct "
    "AND idx.indnatts=1 AND idx.indnkeyatts=1 "
    "AND idx.indkey[0]=att.attnum AND idx.indcollation[0]=att.attcollation "
    "AND idx_class.relname='alembic_version_pkc' "
    "AND idx_class.relnamespace=n.oid AND idx_class.relowner=c.relowner "
    "AND idx_class.relkind='i' AND idx_class.relpersistence='p' "
    "AND NOT idx_class.relispartition AND idx_class.reloptions IS NULL "
    "AND idx_class.reltablespace=0 AND idx_am.amname='btree' "
    "AND idx_am.amtype='i' AND opclass.opcmethod=idx_am.oid "
    "AND opclass.opcname='text_ops' AND opclass.opcdefault "
    "AND opclass_ns.nspname='pg_catalog') "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint incoming "
    "WHERE incoming.confrelid=c.oid AND incoming.conrelid<>c.oid) "
    "AND (SELECT pg_catalog.count(*) FROM pg_catalog.pg_index ix "
    "WHERE ix.indrelid=c.oid)=1 "
    "AND NOT EXISTS (WITH RECURSIVE global_writer_descendants(member) AS ("
    "SELECT membership.member FROM pg_catalog.pg_auth_members membership "
    "JOIN pg_catalog.pg_roles global_writer "
    "ON global_writer.oid=membership.roleid "
    "WHERE global_writer.rolname='pg_write_all_data' UNION SELECT "
    "nested_membership.member FROM pg_catalog.pg_auth_members "
    "nested_membership JOIN global_writer_descendants descendants "
    "ON nested_membership.roleid=descendants.member) SELECT 1 FROM "
    "global_writer_descendants descendants JOIN pg_catalog.pg_roles "
    "member_role ON member_role.oid=descendants.member WHERE "
    "descendants.member<>a.role_oid AND member_role.rolcanlogin) "
    "AND NOT EXISTS (WITH RECURSIVE protected_descendants(member) AS ("
    "SELECT membership.member FROM pg_catalog.pg_auth_members membership "
    "WHERE membership.roleid IN (a.role_oid,n.nspowner,CASE WHEN "
    "schema_owner.rolname='pg_database_owner' THEN current_db.datdba "
    "ELSE n.nspowner END,c.relowner,CASE WHEN table_owner.rolname="
    "'pg_database_owner' THEN current_db.datdba ELSE c.relowner END,"
    "(SELECT platform_role.oid FROM pg_catalog.pg_roles platform_role "
    "WHERE platform_role.rolname='neon_superuser')) UNION SELECT "
    "nested_membership.member FROM pg_catalog.pg_auth_members "
    "nested_membership JOIN protected_descendants descendants "
    "ON nested_membership.roleid=descendants.member) SELECT 1 FROM "
    "protected_descendants descendants JOIN pg_catalog.pg_roles member_role "
    "ON member_role.oid=descendants.member WHERE descendants.member<>a.role_oid "
    "AND member_role.rolcanlogin) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.aclexplode("
    "coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) acl "
    "LEFT JOIN pg_catalog.pg_roles platform_grantee "
    "ON platform_grantee.oid=acl.grantee "
    "WHERE acl.grantee<>a.role_oid AND acl.grantee<>c.relowner AND NOT ("
    "platform_grantee.rolname='neon_superuser' "
    "AND NOT platform_grantee.rolcanlogin "
    "AND pg_catalog.pg_has_role(a.role_oid,platform_grantee.oid,'MEMBER') "
    "AND NOT EXISTS (WITH RECURSIVE platform_descendants(member) AS ("
    "SELECT platform_membership.member FROM pg_catalog.pg_auth_members "
    "platform_membership WHERE platform_membership.roleid=platform_grantee.oid "
    "UNION SELECT nested_membership.member FROM pg_catalog.pg_auth_members "
    "nested_membership JOIN platform_descendants descendants "
    "ON nested_membership.roleid=descendants.member) SELECT 1 FROM "
    "platform_descendants WHERE member<>a.role_oid) "
    "AND acl.privilege_type IN ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE',"
    "'REFERENCES','TRIGGER') AND acl.is_grantable)) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.aclexplode("
    "coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) acl "
    "WHERE acl.privilege_type='CREATE' AND acl.grantee<>a.role_oid "
    "AND acl.grantee<>n.nspowner)) AS table_safe "
    "FROM actor a LEFT JOIN pg_catalog.pg_namespace n ON n.nspname='public' "
    "LEFT JOIN pg_catalog.pg_roles schema_owner ON schema_owner.oid=n.nspowner "
    "LEFT JOIN pg_catalog.pg_database current_db ON "
    "current_db.datname=pg_catalog.current_database() "
    "LEFT JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid "
    "AND c.relname='alembic_version' LEFT JOIN pg_catalog.pg_roles table_owner "
    "ON table_owner.oid=c.relowner LEFT JOIN pg_catalog.pg_attribute att "
    "ON att.attrelid=c.oid AND att.attname='version_num') SELECT "
    "schema_oid,table_oid,schema_oid IS NOT NULL AS public_schema_exists, "
    "table_safe AS alembic_version_is_plain_permanent_table, "
    "CASE WHEN schema_oid IS NULL THEN false WHEN rolsuper THEN true "
    "WHEN schema_owner_oid=role_oid OR pg_catalog.pg_has_role("
    "role_oid,schema_owner_oid,'SET') THEN true ELSE EXISTS (SELECT 1 FROM "
    "pg_catalog.aclexplode(coalesce(schema_acl,pg_catalog.acldefault("
    "'n',schema_owner_oid))) acl WHERE acl.grantee=role_oid "
    "AND acl.privilege_type='USAGE' AND acl.is_grantable) END "
    "AS schema_usage_grantable, CASE WHEN schema_oid IS NULL THEN false "
    "WHEN rolsuper THEN true WHEN schema_owner_oid=role_oid OR "
    "pg_catalog.pg_has_role(role_oid,schema_owner_oid,'SET') THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(schema_acl,"
    "pg_catalog.acldefault('n',schema_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='CREATE' "
    "AND acl.is_grantable) END AS schema_create_grantable, "
    "CASE WHEN NOT table_safe THEN false WHEN rolsuper THEN "
    "effective_table_owner_oid=role_oid WHEN effective_table_owner_oid="
    "role_oid THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(table_acl,"
    "pg_catalog.acldefault('r',table_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='SELECT' "
    "AND acl.is_grantable) END AS table_select_grantable, "
    "CASE WHEN NOT table_safe THEN false WHEN rolsuper THEN "
    "effective_table_owner_oid=role_oid WHEN effective_table_owner_oid="
    "role_oid THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(table_acl,"
    "pg_catalog.acldefault('r',table_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='INSERT' "
    "AND acl.is_grantable) END AS table_insert_grantable, "
    "CASE WHEN NOT table_safe THEN false WHEN rolsuper THEN "
    "effective_table_owner_oid=role_oid WHEN effective_table_owner_oid="
    "role_oid THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(table_acl,"
    "pg_catalog.acldefault('r',table_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='UPDATE' "
    "AND acl.is_grantable) END AS table_update_grantable, "
    "CASE WHEN NOT table_safe THEN false WHEN rolsuper THEN "
    "effective_table_owner_oid=role_oid WHEN effective_table_owner_oid="
    "role_oid THEN true "
    "ELSE EXISTS (SELECT 1 FROM pg_catalog.aclexplode(coalesce(table_acl,"
    "pg_catalog.acldefault('r',table_owner_oid))) acl "
    "WHERE acl.grantee=role_oid AND acl.privilege_type='DELETE' "
    "AND acl.is_grantable) END AS table_delete_grantable, "
    "NOT EXISTS (WITH RECURSIVE authority_descendants(member) AS ("
    "SELECT membership.member FROM pg_catalog.pg_auth_members membership "
    "WHERE membership.roleid IN (targets.role_oid,targets.schema_owner_oid,"
    "targets.effective_schema_owner_oid,targets.table_owner_oid,"
    "targets.effective_table_owner_oid) UNION SELECT nested_membership.member FROM "
    "pg_catalog.pg_auth_members nested_membership JOIN authority_descendants "
    "descendants ON nested_membership.roleid=descendants.member) SELECT 1 "
    "FROM authority_descendants WHERE member<>targets.role_oid) "
    "AS authority_role_memberships_clean FROM targets",
    "SELECT version_num FROM ONLY public.alembic_version ORDER BY version_num",
    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
    "rolreplication, rolbypassrls FROM pg_catalog.pg_roles "
    "WHERE rolname=current_user",
    "SELECT count(*) = 1 AND bool_and(rolpassword IS NULL) IS NOT NULL AS visible "
    "FROM pg_catalog.pg_authid WHERE rolname=current_user",
    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
    "rolreplication, rolbypassrls FROM pg_catalog.pg_roles "
    "WHERE rolname LIKE 'chronos_%' ORDER BY rolname",
    "SELECT granted.rolname AS granted_role, member.rolname AS member_role, "
    "grantor.rolname AS grantor_role, m.admin_option "
    "FROM pg_catalog.pg_auth_members m "
    "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
    "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
    "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
    "WHERE granted.rolname LIKE 'chronos_%' "
    "OR member.rolname LIKE 'chronos_%' ORDER BY 1,2,3",
    "SELECT 'relation' AS object_type, n.nspname AS schema_name, "
    "c.relname AS object_name, owner.rolname AS owner_role, "
    "pg_catalog.cardinality(coalesce(c.relacl,'{}'::aclitem[])) AS acl_entry_count "
    "FROM pg_catalog.pg_class c "
    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
    "JOIN pg_catalog.pg_roles owner ON owner.oid=c.relowner "
    "WHERE n.nspname='public' AND (c.relname LIKE 'chronos_%' "
    "OR c.relname IN ('uq_chronos_authority_run_revision',"
    "'uq_chronos_event_operation_type','uq_chronos_event_operation_sequence',"
    "'uq_chronos_event_authority_sequence','uq_chronos_event_previous_hash')) "
    "UNION ALL SELECT 'function', n.nspname, p.proname, owner.rolname, "
    "pg_catalog.cardinality(coalesce(p.proacl,'{}'::aclitem[])) "
    "FROM pg_catalog.pg_proc p "
    "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
    "JOIN pg_catalog.pg_roles owner ON owner.oid=p.proowner "
    "WHERE n.nspname='public' AND p.proname LIKE 'chronos_%' "
    "UNION ALL SELECT 'type', n.nspname, t.typname, owner.rolname, "
    "pg_catalog.cardinality(coalesce(t.typacl,'{}'::aclitem[])) "
    "FROM pg_catalog.pg_type t "
    "JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
    "JOIN pg_catalog.pg_roles owner ON owner.oid=t.typowner "
    "WHERE n.nspname='public' AND t.typname LIKE 'chronos_%' "
    "AND t.typrelid=0 "
    "ORDER BY 1,2,3",
    "ROLLBACK",
)

SQL_BEGIN_READ_ONLY = 0
SQL_DEFAULT_TRANSACTION_READ_ONLY = 1
SQL_TRANSACTION_READ_ONLY = 2
SQL_STATEMENT_TIMEOUT = 3
SQL_LOCK_TIMEOUT = 4
SQL_SEARCH_PATH = 5
SQL_IDENTITY = 6
SQL_SSL = 7
SQL_TARGET_CLASSIFICATION_BEFORE_LOCK = 8
SQL_LOCK_ALEMBIC_VERSION = 9
SQL_TARGET_CLASSIFICATION_AFTER_LOCK = 10
SQL_REVISION = 11
SQL_LIFECYCLE_ADMIN = 12
SQL_PRIVILEGED_CATALOG = 13
SQL_CHRONOS_ROLES = 14
SQL_CHRONOS_MEMBERSHIPS = 15
SQL_CHRONOS_OBJECTS = 16
SQL_ROLLBACK = 17

_SAFE_ID = re.compile(r"^[a-z0-9-]{1,60}$")
_HEX_SHA = re.compile(r"^[0-9a-f]{40}$")
_PAGINATION_SEMANTIC_TOKENS = (
    "cursor",
    "next",
    "prev",
    "continu",
    "trunc",
    "complete",
    "remain",
    "has_more",
    "more",
    "after",
    "before",
    "pagin",
    "page",
    "offset",
    "limit",
    "sort",
    "order",
    "link",
)


class _DuplicateJsonKey(ValueError):
    """Raised when an external JSON response contains an ambiguous object."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise _DuplicateJsonKey(key)
        document[key] = value
    return document


class JsonGetSession(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: int,
        allow_redirects: bool,
    ) -> requests.Response: ...


@dataclass(frozen=True, slots=True)
class GateChecks:
    secrets_present: bool
    project_identity_verified: bool
    production_branch_verified: bool
    direct_endpoint_verified: bool
    ssl_verified: bool
    expected_revision_verified: bool
    bootstrap_authority_plausible: bool
    recovery_branch_feasible: bool
    purchase_required: bool
    github_queue_empty: bool
    github_in_progress_empty: bool
    github_dispatch_unique: bool


@dataclass(frozen=True, slots=True)
class GateDecision:
    verdict: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class NeonObservation:
    identity_path: str
    identity_verdict: str
    project_id: str
    project_name: str
    region: str
    branch_id: str
    branch_name: str
    branch_default: bool
    branch_parent_id: str | None
    endpoint_id: str
    endpoint_host: str
    endpoint_state: str
    branch_state: str
    owner_id: str
    owner_branch_count: int
    branch_limit: int
    history_retention_seconds: int
    postgresql_major: int
    project_pages_read: int
    projects_observed: int
    endpoint_projects_inspected: int
    api_get_count: int
    suspend_timeout_seconds: int = -1
    project_inventory_exhaustive: bool = False
    endpoint_detail_reads: int = 0
    project_detail_reads: int = 0
    branch_pages_read: int = 0
    branch_endpoint_reads: int = 0
    cursor_continuation_requested: bool = False
    cursor_cycle_encountered: bool = False
    positive_witness_checks: tuple[str, ...] = ()
    branch_capacity_proven: bool = False
    autoscaling_limit_max_cu: float | None = None
    owner_scope_verdict: str = "OWNER_SCOPE_NOT_PROVEN"
    branch_count_reads: int = 0
    subscription_type: str = "UNKNOWN"
    billing_plan: str = "UNKNOWN"
    target_project_branch_count: int = 0
    bill_free_branch_capacity_proven: bool = False


@dataclass(slots=True)
class IdentityAudit:
    identity_path: str
    project_pages_read: int = 0
    projects_observed: int = 0
    endpoint_projects_inspected: int = 0
    project_id: str | None = None
    endpoint_id: str | None = None
    branch_id: str | None = None
    project_inventory_exhaustive: bool = False
    endpoint_detail_reads: int = 0
    project_detail_reads: int = 0
    branch_pages_read: int = 0
    branch_endpoint_reads: int = 0
    cursor_continuation_requested: bool = False
    cursor_cycle_encountered: bool = False
    positive_witness_checks: list[str] = field(default_factory=list)
    project_cursor_fingerprints: set[str] = field(default_factory=set)
    branch_cursor_fingerprints: set[str] = field(default_factory=set)
    project_ids: list[str] = field(default_factory=list)
    owner_scope_verdict: str = "OWNER_SCOPE_NOT_PROVEN"
    owner_scope_proven: bool = False
    owner_id: str | None = None
    account_branch_limit: int | None = None
    owner_branch_count: int = 0
    branch_count_reads: int = 0
    branch_counts_by_project: dict[str, int] = field(default_factory=dict)
    billing_plan: str | None = None
    owner_scope_get_count: int = 0

    def sanitized(self, *, api_get_count: int, gate: str | None = None) -> dict[str, object]:
        evidence: dict[str, object] = {
            "identity_path": self.identity_path,
            "identity_proof_mode": (
                "POSITIVE_OWNERSHIP"
                if self.identity_path == "POSITIVE_ENDPOINT_WITNESS"
                else self.identity_path
            ),
            "project_identity_verdict": "NEON_PROJECT_IDENTITY_NOT_PROVEN",
            "project_pages_read": self.project_pages_read,
            "projects_observed": self.projects_observed,
            "endpoint_projects_inspected": self.endpoint_projects_inspected,
            "project_inventory_exhaustive": self.project_inventory_exhaustive,
            "endpoint_detail_reads": self.endpoint_detail_reads,
            "project_detail_reads": self.project_detail_reads,
            "branch_pages_read": self.branch_pages_read,
            "branch_endpoint_reads": self.branch_endpoint_reads,
            "cursor_continuation_requested": self.cursor_continuation_requested,
            "cursor_cycle_encountered": self.cursor_cycle_encountered,
            "positive_witness_checks": list(self.positive_witness_checks),
            "owner_scope_verdict": self.owner_scope_verdict,
            "owner_scope_proven": self.owner_scope_proven,
            "branch_count_reads": self.branch_count_reads,
            "api_get_count": api_get_count,
        }
        if self.project_id is not None:
            evidence["project_id_sha256"] = _fingerprint(self.project_id)
        if self.endpoint_id is not None:
            evidence["endpoint_id_sha256"] = _fingerprint(self.endpoint_id)
        if self.branch_id is not None:
            evidence["branch_id_sha256"] = _fingerprint(self.branch_id)
        if self.owner_id is not None:
            evidence["owner_id_sha256"] = _fingerprint(self.owner_id)
        return evidence


@dataclass(frozen=True, slots=True)
class DatabaseObservation:
    database_name: str
    session_user: str
    current_user: str
    postgresql_version: str
    ssl: bool
    revision: str
    revision_count: int
    default_transaction_read_only: bool
    transaction_read_only: bool
    statement_timeout_ms: int
    lock_timeout_ms: int
    lifecycle_admin_can_login: bool
    lifecycle_admin_superuser: bool
    lifecycle_admin_createrole: bool
    privileged_catalog_visible: bool
    chronos_roles: tuple[dict[str, object], ...]
    chronos_memberships: tuple[dict[str, object], ...]
    chronos_objects: tuple[dict[str, object], ...]
    sql_statement_count: int
    postgresql_version_num: int = 0
    bootstrap_grantable_capabilities: tuple[str, ...] = ()
    sql_read_count: int = 0
    bootstrap_targets_valid: bool = False
    sql_statement_completed_count: int = 0
    sql_read_attempt_count: int = 0


@dataclass(slots=True)
class DatabaseInspectionAudit:
    """Effect counters that survive partial or failed read-only inspection."""

    sql_statement_count: int = 0
    sql_statement_completed_count: int = 0
    sql_read_count: int = 0
    sql_read_attempt_count: int = 0
    sql_write_count: int = 0
    begin_read_only_attempted: int = 0
    begin_read_only_completed: int = 0
    rollback_attempted: int = 0
    rollback_completed: int = 0
    connection_attempt_count: int = 0
    connection_success_count: int = 0
    connection_close_completed: bool | None = None
    default_transaction_read_only: bool | None = None
    transaction_read_only: bool | None = None
    statement_timeout_ms: int | None = None
    lock_timeout_ms: int | None = None
    search_path_pg_catalog: bool | None = None
    database_target_verified: bool | None = None
    principal_target_verified: bool | None = None
    postgresql_version_num: int | None = None
    postgresql_major_verified: bool | None = None
    ssl_verified: bool | None = None
    alembic_target_safe: bool | None = None
    revision: str | None = None
    revision_count: int | None = None
    bootstrap_authority_capabilities_proven: bool | None = None
    privileged_catalog_visible: bool | None = None
    chronos_roles_clean: bool | None = None
    chronos_memberships_clean: bool | None = None
    chronos_objects_clean: bool | None = None
    inspection_failure_class: str = "NOT_OBSERVED"

    def before_execute(self, statement: str) -> None:
        self.sql_statement_count += 1
        if statement.lstrip().upper().startswith(("SHOW ", "SELECT ", "WITH ")):
            self.sql_read_attempt_count += 1
        if statement == "BEGIN READ ONLY":
            self.begin_read_only_attempted += 1
        if statement == "ROLLBACK":
            self.rollback_attempted += 1

    def after_execute(self, statement: str) -> None:
        self.sql_statement_completed_count += 1
        if statement.lstrip().upper().startswith(("SHOW ", "SELECT ", "WITH ")):
            self.sql_read_count += 1
        if statement == "BEGIN READ ONLY":
            self.begin_read_only_completed += 1
        if statement == "ROLLBACK":
            self.rollback_completed += 1

    def effects(self) -> dict[str, int]:
        return {
            "postgresql_connection_attempts": self.connection_attempt_count,
            "postgresql_connection_successes": self.connection_success_count,
            "postgresql_retries": 0,
            "sql_statement_count": self.sql_statement_count,
            "sql_statement_completed_count": self.sql_statement_completed_count,
            "sql_read_attempt_count": self.sql_read_attempt_count,
            "sql_read_count": self.sql_read_count,
            "sql_write_count": self.sql_write_count,
            "begin_read_only_attempted": self.begin_read_only_attempted,
            "begin_read_only_completed": self.begin_read_only_completed,
            "rollback_attempted": self.rollback_attempted,
            "rollback_completed": self.rollback_completed,
        }

    def sanitized_evidence(self) -> dict[str, object]:
        """Return only bounded, identity-free observations acquired so far."""

        known_revisions = {
            "0012_universal_genome_v2",
            EXPECTED_REVISION,
            "0014_chronos_control_plane_v2",
        }
        revision_class = "NOT_OBSERVED"
        if self.revision_count is not None:
            revision_class = (
                self.revision
                if self.revision_count == 1 and self.revision in known_revisions
                else "OTHER_OR_NON_SINGLETON"
            )
        return {
            "connection_established": self.connection_success_count == 1,
            "connection_close_completed": self.connection_close_completed,
            "default_transaction_read_only": self.default_transaction_read_only,
            "transaction_read_only": self.transaction_read_only,
            "statement_timeout_ms": self.statement_timeout_ms,
            "lock_timeout_ms": self.lock_timeout_ms,
            "search_path_pg_catalog": self.search_path_pg_catalog,
            "database_target_verified": self.database_target_verified,
            "principal_target_verified": self.principal_target_verified,
            "postgresql_version_num": self.postgresql_version_num,
            "postgresql_major_verified": self.postgresql_major_verified,
            "ssl_verified": self.ssl_verified,
            "alembic_target_safe": self.alembic_target_safe,
            "revision_class": revision_class,
            "revision_count": self.revision_count,
            "bootstrap_authority_capabilities_proven": (
                self.bootstrap_authority_capabilities_proven
            ),
            "privileged_catalog_visible": self.privileged_catalog_visible,
            "chronos_roles_clean": self.chronos_roles_clean,
            "chronos_memberships_clean": self.chronos_memberships_clean,
            "chronos_objects_clean": self.chronos_objects_clean,
            "inspection_failure_class": self.inspection_failure_class,
        }


class PreflightNoGo(RuntimeError):
    """Sanitized expected refusal with an approved reason code."""

    def __init__(
        self,
        reason: str,
        gate: str,
        *,
        dsn_security_profile: Mapping[str, object] | None = None,
        sanitized_evidence: Mapping[str, object] | None = None,
        sanitized_postgresql_evidence: Mapping[str, object] | None = None,
        effect_counts: Mapping[str, int] | None = None,
    ) -> None:
        if reason not in NO_GO_REASONS:
            raise ValueError("INVALID_NO_GO_REASON")
        super().__init__(reason)
        self.reason = reason
        self.gate = gate
        self.dsn_security_profile = dsn_security_profile
        self.sanitized_evidence = sanitized_evidence
        self.sanitized_postgresql_evidence = sanitized_postgresql_evidence
        self.effect_counts = dict(effect_counts or {})


def evaluate_checks(checks: GateChecks) -> GateDecision:
    """Apply the approved deterministic GO/NO-GO priority."""

    priority = (
        (not checks.secrets_present, "SECRET_MISSING"),
        (not checks.project_identity_verified, "NEON_PROJECT_IDENTITY_AMBIGUOUS"),
        (not checks.production_branch_verified, "NEON_PRODUCTION_BRANCH_AMBIGUOUS"),
        (
            not checks.direct_endpoint_verified or not checks.ssl_verified,
            "DIRECT_ENDPOINT_NOT_PROVEN",
        ),
        (not checks.expected_revision_verified, "UNEXPECTED_DATABASE_REVISION"),
        (
            not checks.bootstrap_authority_plausible,
            "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
        ),
        (checks.purchase_required, "PURCHASE_REQUIRED"),
        (
            not checks.recovery_branch_feasible
            or not checks.github_queue_empty
            or not checks.github_in_progress_empty
            or not checks.github_dispatch_unique,
            "RECOVERY_BRANCH_NOT_FEASIBLE",
        ),
    )
    for failed, reason in priority:
        if failed:
            return GateDecision(NO_GO_VERDICT, reason)
    return GateDecision(GO_VERDICT, None)


def failed_gate(checks: GateChecks) -> str | None:
    """Return the first stable diagnostic gate using decision priority."""

    ordered = (
        (not checks.project_identity_verified, "project_identity_not_proven"),
        (not checks.production_branch_verified, "production_branch_not_proven"),
        (not checks.direct_endpoint_verified, "direct_endpoint_not_proven"),
        (not checks.ssl_verified, "ssl_not_proven"),
        (not checks.expected_revision_verified, "unexpected_database_revision"),
        (not checks.bootstrap_authority_plausible, "bootstrap_authority_insufficient"),
        (checks.purchase_required, "purchase_required"),
        (not checks.recovery_branch_feasible, "recovery_branch_not_feasible"),
        (not checks.github_queue_empty, "github_actions_queue_not_empty"),
        (not checks.github_in_progress_empty, "github_actions_in_progress_not_empty"),
        (not checks.github_dispatch_unique, "exact_main_dispatch_not_unique"),
    )
    return next((gate for failed, gate in ordered if failed), None)


def _required_context(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise PreflightNoGo("SECRET_MISSING", f"missing:{name}")
    return value


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_pooler_host(host: str) -> bool:
    return host.split(".", 1)[0].endswith("-pooler")


def _safe_identifier(value: object, *, gate: str = "unsafe_identifier") -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    return value


def _required_sensitive_context(name: str) -> str:
    value = _required_context(name)
    if len(value.strip()) < 8:
        raise PreflightNoGo("SECRET_MISSING", "sensitive_value_too_short")
    return value


def _positive_integer_context(name: str) -> int:
    value = _required_context(name)
    if not value.isdecimal():
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", f"invalid:{name}")
    parsed = int(value)
    if parsed < 1:
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", f"invalid:{name}")
    return parsed


def _contains_continuation_semantics(value: object) -> bool:
    """Find continuation-bearing keys in an otherwise unknown JSON subtree."""

    pending = [value]
    containers_seen = 0
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping):
            containers_seen += 1
            if containers_seen > 10_000:
                return True
            for raw_key, nested in current.items():
                if not isinstance(raw_key, str):
                    return True
                key = raw_key.lower()
                if any(token in key for token in _PAGINATION_SEMANTIC_TOKENS):
                    return True
                pending.append(nested)
        elif isinstance(current, list):
            containers_seen += 1
            if containers_seen > 10_000:
                return True
            pending.extend(current)
    return False


def _reject_unknown_pagination_semantics(
    pagination: Mapping[str, object],
    *,
    known: frozenset[str],
    reason: str,
    gate: str,
) -> None:
    """Allow unrelated metadata while refusing unknown continuation semantics."""

    for raw_key, nested in pagination.items():
        if not isinstance(raw_key, str):
            raise PreflightNoGo(reason, gate)
        if raw_key in known:
            continue
        key = raw_key.lower()
        if (
            key in known
            or any(token in key for token in _PAGINATION_SEMANTIC_TOKENS)
            or _contains_continuation_semantics(nested)
        ):
            raise PreflightNoGo(reason, gate)


def _reject_top_level_continuation_semantics(
    document: Mapping[str, object],
    *,
    allowed: frozenset[str],
    reason: str,
    gate: str,
) -> None:
    for raw_key, nested in document.items():
        if not isinstance(raw_key, str):
            raise PreflightNoGo(reason, gate)
        if raw_key in allowed:
            continue
        key = raw_key.lower()
        if (
            key in allowed
            or any(token in key for token in _PAGINATION_SEMANTIC_TOKENS)
            or _contains_continuation_semantics(nested)
        ):
            raise PreflightNoGo(reason, gate)


def _finite_json(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite_json(nested) for key, nested in value.items())
    if isinstance(value, list):
        return all(_finite_json(item) for item in value)
    return value is None or isinstance(value, (bool, int, str))


def _dict_list(document: Mapping[str, Any], key: str, reason: str) -> list[dict[str, Any]]:
    value = document.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PreflightNoGo(reason, f"invalid_neon_response:{key}")
    return [cast(dict[str, Any], item) for item in value]


class NeonReadOnlyClient:
    """GET-only Neon API client with a hard request ceiling and no retries."""

    def __init__(
        self,
        api_key: str,
        *,
        session: JsonGetSession | None = None,
    ) -> None:
        if not api_key:
            raise PreflightNoGo("SECRET_MISSING", "missing:NEON_API_KEY")
        self._api_key = api_key
        self._session: JsonGetSession
        if session is None:
            isolated_session = requests.Session()
            isolated_session.trust_env = False
            self._session = isolated_session
        else:
            self._session = session
        self.get_count = 0

    def require_get_budget(self, required: int, gate: str) -> None:
        """Prove that a complete planned suffix still fits before a GET."""

        if required < 1 or self.get_count + required > MAX_NEON_GETS:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)

    def get(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        route_allowed = (
            path.startswith("/projects")
            or path == "/auth"
            or path == "/users/me"
            or path == "/users/me/organizations"
            or re.fullmatch(r"/organizations/[a-z0-9-]{1,60}", path) is not None
            or re.fullmatch(r"/organizations/[a-z0-9-]{1,60}/members", path) is not None
        )
        if not route_allowed or ".." in path or "?" in path or "#" in path:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_route_forbidden")
        if self.get_count >= MAX_NEON_GETS:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_get_budget_exhausted")
        try:
            validate_data_torrent_authority()
        except ChronosProductionError:
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE", "mission_authority_inactive"
            ) from None
        self.get_count += 1
        request_url = NEON_API + path
        if query:
            request_url += "?" + urlencode(query, doseq=False, safe="")
        try:
            response = self._session.get(
                request_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                timeout=30,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_api_unavailable") from None
        if not 200 <= response.status_code < 300:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                f"neon_api_http_{response.status_code}",
            )
        try:
            document = response.json(object_pairs_hook=_unique_json_object)
        except (TypeError, ValueError):
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_api_invalid_json"
            ) from None
        if not isinstance(document, dict):
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_api_invalid_document")
        if not _finite_json(document):
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "neon_api_non_finite_or_non_json_value",
            )
        return cast(dict[str, Any], document)


def _project_details(document: Mapping[str, Any]) -> dict[str, Any]:
    project = document.get("project")
    if not isinstance(project, dict):
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_details_missing")
    return cast(dict[str, Any], project)


def _project_owner_identity(
    project: Mapping[str, Any],
    *,
    expected_organization_id: str | None,
    gate: str,
) -> str:
    """Bind current org identity while preserving a present legacy owner ID."""

    owner_id = project.get("owner_id")
    if not isinstance(owner_id, str) or not owner_id:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    if "org_id" in project:
        org_id = project["org_id"]
        if (
            not isinstance(org_id, str)
            or not org_id
            or _SAFE_ID.fullmatch(org_id) is None
            or (expected_organization_id is not None and org_id != expected_organization_id)
        ):
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    elif expected_organization_id is not None and owner_id != expected_organization_id:
        # Current payloads can carry a distinct legacy owner_id together with the
        # authoritative org_id.  If org_id is absent, owner_id is the only
        # ownership field and must itself bind to the selected organization.
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    return owner_id


def _branch_state(branch: Mapping[str, Any]) -> str:
    state = branch.get("current_state")
    if not isinstance(state, str) or not state:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "production_branch_state_missing")
    if branch.get("pending_state") is not None:
        raise PreflightNoGo(
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
            "production_branch_transitioning",
        )
    return state


def _project_page_cursor(document: Mapping[str, Any]) -> str | None:
    """Parse the List projects Pagination contract (`pagination.cursor`)."""

    _reject_top_level_continuation_semantics(
        document,
        allowed=frozenset(
            {
                "projects",
                "unavailable_project_ids",
                "applications",
                "integrations",
                "pagination",
            }
        ),
        reason="NEON_PROJECT_IDENTITY_AMBIGUOUS",
        gate="project_pagination_invalid",
    )
    if "pagination" not in document:
        return None
    pagination = document["pagination"]
    if not isinstance(pagination, dict):
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_pagination_invalid")
    _reject_unknown_pagination_semantics(
        pagination,
        known=frozenset({"cursor"}),
        reason="NEON_PROJECT_IDENTITY_AMBIGUOUS",
        gate="project_pagination_invalid",
    )
    if "cursor" not in pagination:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_pagination_invalid")
    cursor = pagination["cursor"]
    if not isinstance(cursor, str) or not cursor:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_pagination_invalid")
    return cursor


def _list_projects_bounded(
    client: NeonReadOnlyClient,
    audit: IdentityAudit,
) -> list[dict[str, Any]]:
    """Enumerate a complete project inventory without partial endpoint scans."""

    projects: list[dict[str, Any]] = []
    owned_project_ids: list[str] = []
    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    cursor: str | None = None
    while True:
        if audit.project_pages_read >= MAX_PROJECT_PAGES:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_pagination_invalid")
        client.require_get_budget(
            1 + len(owned_project_ids) + 1 + MAX_BRANCH_PAGES,
            "project_identity_discovery_budget_exceeded",
        )
        query: dict[str, object] = {"limit": PROJECT_PAGE_LIMIT}
        if audit.owner_scope_verdict == "PERSONAL_ADMIN_ORGANIZATION_PROVEN":
            query["org_id"] = audit.owner_id
        if cursor is not None:
            query["cursor"] = cursor
        document = client.get("/projects", query=query)
        audit.project_pages_read += 1
        page = _dict_list(
            document,
            "projects",
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        )
        unavailable = document.get("unavailable_project_ids", [])
        if not isinstance(unavailable, list) or unavailable:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_inventory_incomplete")
        page_ids: list[str] = []
        for project in page:
            project_id = _safe_identifier(project.get("id", ""), gate="project_pagination_invalid")
            _project_owner_identity(
                project,
                expected_organization_id=cast(str, audit.owner_id),
                gate="project_inventory_incomplete",
            )
            page_ids.append(project_id)
        next_cursor = _project_page_cursor(document)
        # Neon cursors identify the last returned item; the API can echo the
        # previous cursor on the empty terminal page.  The official SDK also
        # terminates on an empty item set even when a cursor remains present.
        if not page_ids:
            break
        page_fingerprint = _fingerprint("\x00".join(page_ids))
        if page_fingerprint in seen_pages:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_pagination_invalid")
        seen_pages.add(page_fingerprint)
        for project, project_id in zip(page, page_ids, strict=True):
            if project_id in seen_ids:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "project_inventory_duplicate_id",
                )
            seen_ids.add(project_id)
            projects.append(project)
            owned_project_ids.append(project_id)
        audit.projects_observed = len(projects)
        if len(owned_project_ids) > _owner_project_item_limit(audit):
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_identity_discovery_budget_exceeded",
            )
        if next_cursor is None:
            break
        cursor_fingerprint = _fingerprint(next_cursor)
        if cursor_fingerprint in audit.project_cursor_fingerprints:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_cursor_cycle")
        audit.project_cursor_fingerprints.add(cursor_fingerprint)
        cursor = next_cursor
    audit.project_ids.extend(owned_project_ids)
    audit.project_inventory_exhaustive = True
    client.require_get_budget(
        len(owned_project_ids) + 1 + MAX_BRANCH_PAGES,
        "project_identity_discovery_budget_exceeded",
    )
    return projects


def _branch_page_cursor(
    document: Mapping[str, Any],
    audit: IdentityAudit,
) -> str | None:
    """Parse only the List branches CursorPagination (`pagination.next`)."""

    _reject_top_level_continuation_semantics(
        document,
        allowed=frozenset({"branches", "annotations", "pagination"}),
        reason="NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        gate="branch_inventory_truncated",
    )
    if "pagination" not in document:
        return None
    pagination = document["pagination"]
    if not isinstance(pagination, dict):
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    _reject_unknown_pagination_semantics(
        pagination,
        known=frozenset({"next", "previous", "sort_by", "sort_order"}),
        reason="NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        gate="branch_inventory_truncated",
    )
    if pagination.get("sort_by", "updated_at") != "updated_at":
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    if pagination.get("sort_order", "asc") != "asc":
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    previous = pagination.get("previous")
    if previous is not None:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    if "next" not in pagination or pagination["next"] is None:
        return None
    cursor = pagination["next"]
    if not isinstance(cursor, str) or not cursor:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    fingerprint = _fingerprint(cursor)
    if fingerprint in audit.branch_cursor_fingerprints:
        audit.cursor_cycle_encountered = True
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    audit.branch_cursor_fingerprints.add(fingerprint)
    return cursor


def _list_branches_bounded(
    client: NeonReadOnlyClient,
    project_id: str,
    audit: IdentityAudit,
    *,
    reserve_after: int,
) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    cursor: str | None = None
    pages = 0
    while True:
        if pages >= MAX_BRANCH_PAGES:
            raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
        client.require_get_budget(1 + reserve_after, "neon_get_budget_exhausted")
        query: dict[str, object] = {
            "limit": MAX_BRANCH_PAGE,
            "sort_by": "updated_at",
            "sort_order": "asc",
            "include_deleted": "false",
        }
        if cursor is not None:
            query["cursor"] = cursor
        document = client.get(f"/projects/{project_id}/branches", query=query)
        pages += 1
        audit.branch_pages_read += 1
        page = _dict_list(
            document,
            "branches",
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        )
        page_ids = [
            _safe_identifier(branch.get("id", ""), gate="branch_inventory_truncated")
            for branch in page
        ]
        page_fingerprint = _fingerprint("\x00".join(page_ids))
        if page_fingerprint in seen_pages:
            raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
        seen_pages.add(page_fingerprint)
        for branch, branch_id in zip(page, page_ids, strict=True):
            if branch.get("project_id") != project_id:
                raise PreflightNoGo(
                    "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
                    "branch_project_mismatch",
                )
            if not isinstance(branch.get("default"), bool):
                raise PreflightNoGo(
                    "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
                    "branch_default_contract_invalid",
                )
            _branch_state(branch)
            parent_id = branch.get("parent_id")
            if parent_id is not None:
                _safe_identifier(parent_id, gate="branch_parent_contract_invalid")
            if branch_id in seen_ids:
                raise PreflightNoGo(
                    "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
                    "branch_inventory_truncated",
                )
            seen_ids.add(branch_id)
            branches.append(branch)
        if len(branches) > MAX_BRANCH_ITEMS:
            raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
        cursor = _branch_page_cursor(document, audit)
        if cursor is None:
            if sum(branch.get("default") is True for branch in branches) != 1:
                raise PreflightNoGo(
                    "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
                    "default_branch_not_unique",
                )
            return branches
        audit.cursor_continuation_requested = True


def _validated_project_detail(
    document: Mapping[str, Any],
    project_id: str,
    *,
    expected_owner_id: str | None,
    expected_organization_id: str,
    gate: str,
) -> dict[str, Any]:
    project = _project_details(document)
    if project.get("id") != project_id:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    owner_id = _project_owner_identity(
        project,
        expected_organization_id=expected_organization_id,
        gate=gate,
    )
    owner = project.get("owner")
    if not isinstance(owner, dict) or (
        expected_owner_id is not None and owner_id != expected_owner_id
    ):
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    return project


def _project_endpoints(
    document: Mapping[str, Any],
    project_id: str,
    *,
    expected_branch_id: str | None = None,
    gate: str,
) -> list[dict[str, Any]]:
    _reject_top_level_continuation_semantics(
        document,
        allowed=frozenset({"endpoints"}),
        reason="NEON_PROJECT_IDENTITY_AMBIGUOUS",
        gate="endpoint_inventory_pagination_ambiguous",
    )
    if "pagination" in document:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "endpoint_inventory_pagination_ambiguous"
        )
    endpoints = _dict_list(
        document,
        "endpoints",
        "NEON_PROJECT_IDENTITY_AMBIGUOUS",
    )
    seen_endpoint_ids: set[str] = set()
    for endpoint in endpoints:
        endpoint_id = _safe_identifier(endpoint.get("id", ""), gate=gate)
        if endpoint_id in seen_endpoint_ids:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
        seen_endpoint_ids.add(endpoint_id)
        branch_id = _safe_identifier(endpoint.get("branch_id", ""), gate=gate)
        if expected_branch_id is not None and branch_id != expected_branch_id:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
        if endpoint.get("project_id") != project_id:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
        if not isinstance(endpoint.get("host"), str):
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    return endpoints


def _bounded_int(
    value: object,
    *,
    minimum: int,
    reason: str,
    gate: str,
) -> int:
    if isinstance(value, bool):
        raise PreflightNoGo(reason, gate)
    if not isinstance(value, int):
        raise PreflightNoGo(reason, gate)
    parsed = value
    if parsed < minimum:
        raise PreflightNoGo(reason, gate)
    return parsed


def _positive_endpoint_candidate(
    endpoint: Mapping[str, Any],
    *,
    project_id: str,
    target: DirectPostgresTarget,
) -> bool:
    """Return an exact scoped candidate, failing closed on an invalid exact match."""

    raw_host = endpoint.get("host")
    if not isinstance(raw_host, str):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "positive_endpoint_candidate_invalid"
        )
    endpoint_host = raw_host.lower()
    if endpoint_host != target.host:
        return False
    valid = (
        endpoint.get("project_id") == project_id
        and endpoint.get("type") == "read_write"
        and not _is_pooler_host(endpoint_host)
        and endpoint.get("disabled") is False
    )
    if not valid:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "positive_endpoint_candidate_invalid",
        )
    return True


def _owner_project_item_limit(audit: IdentityAudit) -> int:
    if audit.owner_scope_get_count <= 0:
        return MAX_PROJECT_ITEMS
    return max(
        0,
        (
            MAX_NEON_GETS
            - MAX_PROJECT_PAGES
            - POSITIVE_WITNESS_GET_RESERVE
            - audit.owner_scope_get_count
        )
        // 2,
    )


def _prove_owner_scope(client: NeonReadOnlyClient, audit: IdentityAudit) -> None:
    configured_organization = os.getenv("NEON_ORG_ID", "").strip()
    if configured_organization and len(configured_organization) < 8:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "configured_organization_scope_mismatch",
        )
    configured_organization_id = (
        _safe_identifier(
            configured_organization,
            gate="configured_organization_scope_mismatch",
        )
        if configured_organization
        else None
    )
    auth = client.get("/auth")
    method = auth.get("auth_method")
    account_id_value = auth.get("account_id")
    if not isinstance(account_id_value, str) or not account_id_value:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_auth_scope_invalid")
    account_id = account_id_value
    if method == "api_key_org":
        organization_id = _safe_identifier(account_id, gate="neon_auth_scope_invalid")
        if configured_organization_id is not None and configured_organization_id != organization_id:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "configured_organization_scope_mismatch",
            )
        try:
            organization = client.get(f"/organizations/{organization_id}")
        except PreflightNoGo as error:
            if error.gate not in {"neon_api_http_403", "neon_api_http_404"}:
                raise
            audit.owner_scope_verdict = "PROJECT_SCOPED_ORGANIZATION_KEY"
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE",
                "project_scoped_api_key_owner_capacity_unproven",
            ) from None
        if organization.get("id") != account_id:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "neon_owner_scope_identity_mismatch",
            )
        plan = organization.get("plan")
        if plan not in {"free", "launch", "scale"}:
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE",
                "purchase_requirement_ambiguous",
            )
        audit.billing_plan = cast(str, plan)
        audit.owner_id = organization_id
        audit.owner_scope_verdict = "ORGANIZATION_WIDE_API_KEY"
        audit.owner_scope_proven = True
        audit.owner_scope_get_count = client.get_count
        return
    if method == "api_key_user":
        user = client.get("/users/me")
        if user.get("id") != account_id:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "neon_owner_scope_identity_mismatch",
            )
        organization_document = client.get("/users/me/organizations")
        _reject_top_level_continuation_semantics(
            organization_document,
            allowed=frozenset({"organizations"}),
            reason="NEON_PROJECT_IDENTITY_AMBIGUOUS",
            gate="user_organization_scope_ambiguous",
        )
        organizations = _dict_list(
            organization_document,
            "organizations",
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        )
        organization_ids = [
            _safe_identifier(
                organization.get("id", ""),
                gate="user_organization_scope_ambiguous",
            )
            for organization in organizations
        ]
        if len(set(organization_ids)) != len(organization_ids):
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "user_organization_scope_ambiguous",
            )
        if configured_organization_id is None:
            if len(organizations) != 1:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "user_organization_scope_ambiguous",
                )
            organization = organizations[0]
            organization_id = organization_ids[0]
        else:
            matching_organizations = [
                organization
                for organization, organization_id in zip(
                    organizations, organization_ids, strict=True
                )
                if organization_id == configured_organization_id
            ]
            if len(matching_organizations) != 1:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "configured_organization_scope_mismatch",
                )
            organization = matching_organizations[0]
            organization_id = configured_organization_id
        plan = organization.get("plan")
        if plan not in {"free", "launch", "scale"}:
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE",
                "purchase_requirement_ambiguous",
            )
        member_cursor: str | None = None
        seen_member_cursors: set[str] = set()
        for member_page in range(MAX_MEMBER_PAGES):
            client.require_get_budget(
                1,
                "personal_api_key_owner_capacity_unproven",
            )
            member_query: dict[str, object] = {
                "limit": 500,
                "sort_by": "role",
                "sort_order": "asc",
            }
            if member_cursor is not None:
                member_query["cursor"] = member_cursor
            members = client.get(
                f"/organizations/{organization_id}/members",
                query=member_query,
            )
            _reject_top_level_continuation_semantics(
                members,
                allowed=frozenset({"members", "pagination"}),
                reason="RECOVERY_BRANCH_NOT_FEASIBLE",
                gate="personal_api_key_owner_capacity_unproven",
            )
            pagination = members.get("pagination", {})
            if not isinstance(pagination, dict):
                raise PreflightNoGo(
                    "RECOVERY_BRANCH_NOT_FEASIBLE",
                    "personal_api_key_owner_capacity_unproven",
                )
            _reject_unknown_pagination_semantics(
                pagination,
                known=frozenset({"next", "sort_by", "sort_order"}),
                reason="RECOVERY_BRANCH_NOT_FEASIBLE",
                gate="personal_api_key_owner_capacity_unproven",
            )
            if (
                pagination.get("sort_by", "role") != "role"
                or pagination.get("sort_order", "asc") != "asc"
            ):
                raise PreflightNoGo(
                    "RECOVERY_BRANCH_NOT_FEASIBLE",
                    "personal_api_key_owner_capacity_unproven",
                )
            next_cursor = pagination.get("next")
            if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor):
                raise PreflightNoGo(
                    "RECOVERY_BRANCH_NOT_FEASIBLE",
                    "personal_api_key_owner_capacity_unproven",
                )
            membership_rows = _dict_list(
                members,
                "members",
                "RECOVERY_BRANCH_NOT_FEASIBLE",
            )
            matching_memberships: list[Mapping[str, Any]] = []
            for row in membership_rows:
                member = row.get("member")
                if (
                    not isinstance(member, dict)
                    or not isinstance(member.get("user_id"), str)
                    or not isinstance(member.get("org_id"), str)
                    or not isinstance(member.get("role"), str)
                ):
                    raise PreflightNoGo(
                        "RECOVERY_BRANCH_NOT_FEASIBLE",
                        "personal_api_key_owner_capacity_unproven",
                    )
                if member.get("user_id") == account_id:
                    matching_memberships.append(member)
            if matching_memberships:
                if (
                    len(matching_memberships) != 1
                    or matching_memberships[0].get("org_id") != organization_id
                    or matching_memberships[0].get("role") != "admin"
                ):
                    raise PreflightNoGo(
                        "RECOVERY_BRANCH_NOT_FEASIBLE",
                        "personal_api_key_owner_capacity_unproven",
                    )
                break
            if next_cursor is None or member_page + 1 >= MAX_MEMBER_PAGES:
                raise PreflightNoGo(
                    "RECOVERY_BRANCH_NOT_FEASIBLE",
                    "personal_api_key_owner_capacity_unproven",
                )
            cursor_fingerprint = _fingerprint(next_cursor)
            if cursor_fingerprint in seen_member_cursors:
                raise PreflightNoGo(
                    "RECOVERY_BRANCH_NOT_FEASIBLE",
                    "personal_api_key_owner_capacity_unproven",
                )
            seen_member_cursors.add(cursor_fingerprint)
            member_cursor = next_cursor
        audit.billing_plan = cast(str, plan)
        audit.owner_id = organization_id
        audit.owner_scope_verdict = "PERSONAL_ADMIN_ORGANIZATION_PROVEN"
        audit.owner_scope_proven = True
        audit.owner_scope_get_count = client.get_count
        return
    raise PreflightNoGo(
        "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        "neon_api_credential_scope_unsupported",
    )


def _count_owner_branches(client: NeonReadOnlyClient, audit: IdentityAudit) -> None:
    if not audit.owner_scope_proven:
        return
    total = 0
    for project_id in audit.project_ids:
        document = client.get(f"/projects/{project_id}/branches/count")
        _reject_top_level_continuation_semantics(
            document,
            allowed=frozenset({"count"}),
            reason="RECOVERY_BRANCH_NOT_FEASIBLE",
            gate="branch_count_contract_invalid",
        )
        branch_count = _bounded_int(
            document.get("count"),
            minimum=0,
            reason="RECOVERY_BRANCH_NOT_FEASIBLE",
            gate="branch_count_contract_invalid",
        )
        audit.branch_counts_by_project[project_id] = branch_count
        total += branch_count
        audit.branch_count_reads += 1
    audit.owner_branch_count = total


def _progressive_positive_candidate(
    client: NeonReadOnlyClient,
    target: DirectPostgresTarget,
    audit: IdentityAudit,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Inspect each page's project endpoints before requesting another page."""

    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    cursor: str | None = None
    match: (
        tuple[
            dict[str, Any],
            dict[str, Any],
            list[dict[str, Any]],
        ]
        | None
    ) = None
    while True:
        if audit.project_pages_read >= MAX_PROJECT_PAGES:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_pagination_invalid",
            )
        item_limit = _owner_project_item_limit(audit)
        remaining_capacity = item_limit - len(audit.project_ids)
        client.require_get_budget(
            1 + (2 * remaining_capacity) + POSITIVE_WITNESS_GET_RESERVE,
            "project_identity_discovery_budget_exceeded",
        )
        query: dict[str, object] = {"limit": PROJECT_PAGE_LIMIT}
        if audit.owner_scope_verdict == "PERSONAL_ADMIN_ORGANIZATION_PROVEN":
            query["org_id"] = audit.owner_id
        if cursor is not None:
            query["cursor"] = cursor
        document = client.get("/projects", query=query)
        audit.project_pages_read += 1
        page = _dict_list(
            document,
            "projects",
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        )
        unavailable = document.get("unavailable_project_ids", [])
        if not isinstance(unavailable, list) or unavailable:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_inventory_incomplete",
            )
        page_ids: list[str] = []
        page_seen_ids: set[str] = set()
        for project in page:
            project_id = _safe_identifier(project.get("id", ""), gate="project_pagination_invalid")
            _project_owner_identity(
                project,
                expected_organization_id=cast(str, audit.owner_id),
                gate="project_inventory_incomplete",
            )
            if project_id in seen_ids or project_id in page_seen_ids:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "project_inventory_duplicate_id",
                )
            page_ids.append(project_id)
            page_seen_ids.add(project_id)
        page_fingerprint = _fingerprint("\x00".join(page_ids))
        repeated_page = page_fingerprint in seen_pages
        seen_ids.update(page_ids)
        owned_on_page = list(zip(page, page_ids, strict=True))
        audit.project_ids.extend(project_id for _, project_id in owned_on_page)
        audit.projects_observed = len(seen_ids)
        if len(audit.project_ids) > item_limit:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_identity_discovery_budget_exceeded",
            )
        next_cursor = _project_page_cursor(document)
        # A successful empty page is the authoritative end of the walk even
        # when Neon echoes the cursor that marked the preceding last item.
        # Nonempty cursor repetition remains a fail-closed cycle below.
        if not page_ids:
            audit.project_inventory_exhaustive = True
            client.require_get_budget(
                len(audit.project_ids) + POSITIVE_WITNESS_GET_RESERVE,
                "project_identity_discovery_budget_exceeded",
            )
            _count_owner_branches(client, audit)
            if match is not None:
                return match
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "dsn_endpoint_match_missing",
            )
        for index, (project, project_id) in enumerate(owned_on_page):
            remaining_on_page = len(owned_on_page) - index
            client.require_get_budget(
                remaining_on_page + len(audit.project_ids) + POSITIVE_WITNESS_GET_RESERVE,
                "project_identity_discovery_budget_exceeded",
            )
            endpoints = _project_endpoints(
                client.get(f"/projects/{project_id}/endpoints"),
                project_id,
                gate="project_inventory_incomplete",
            )
            audit.endpoint_projects_inspected += 1
            for endpoint in endpoints:
                if _positive_endpoint_candidate(
                    endpoint,
                    project_id=project_id,
                    target=target,
                ):
                    if match is not None:
                        raise PreflightNoGo(
                            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                            "positive_endpoint_match_not_unique",
                        )
                    match = (project, endpoint, endpoints)
        if next_cursor is None:
            if repeated_page:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "project_pagination_invalid",
                )
            seen_pages.add(page_fingerprint)
            audit.project_inventory_exhaustive = True
            client.require_get_budget(
                len(audit.project_ids) + POSITIVE_WITNESS_GET_RESERVE,
                "project_identity_discovery_budget_exceeded",
            )
            _count_owner_branches(client, audit)
            if match is not None:
                return match
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "dsn_endpoint_match_missing",
            )
        cursor_fingerprint = _fingerprint(next_cursor)
        if cursor_fingerprint in audit.project_cursor_fingerprints:
            audit.cursor_cycle_encountered = True
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_cursor_cycle",
            )
        if repeated_page:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_pagination_invalid",
            )
        seen_pages.add(page_fingerprint)
        audit.project_cursor_fingerprints.add(cursor_fingerprint)
        audit.cursor_continuation_requested = True
        cursor = next_cursor


def _endpoint_detail(
    document: Mapping[str, Any],
    *,
    project_id: str,
    candidate: Mapping[str, Any],
    target: DirectPostgresTarget,
    allow_idle: bool = False,
) -> dict[str, Any]:
    endpoint = document.get("endpoint")
    if not isinstance(endpoint, dict):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "endpoint_detail_missing",
        )
    detailed = cast(dict[str, Any], endpoint)
    _safe_identifier(detailed.get("id", ""), gate="endpoint_detail_invalid")
    _safe_identifier(detailed.get("project_id", ""), gate="endpoint_detail_invalid")
    _safe_identifier(detailed.get("branch_id", ""), gate="endpoint_detail_invalid")
    if not isinstance(detailed.get("host"), str):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "endpoint_detail_invalid",
        )
    accepted_states = {"active", "idle"} if allow_idle else {"active"}
    raw_current_state = detailed.get("current_state")
    if not isinstance(raw_current_state, str):
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "endpoint_detail_state_invalid")
    current_state = raw_current_state
    pending_state = detailed.get("pending_state")
    if allow_idle and current_state not in accepted_states:
        raise PreflightNoGo(
            "ENDPOINT_STATE_UNSUPPORTED",
            "endpoint_state_unsupported",
        )
    comparisons = (
        (detailed.get("id") == candidate.get("id"), "endpoint_detail_id_mismatch"),
        (
            detailed.get("project_id") == project_id,
            "endpoint_detail_project_mismatch",
        ),
        (
            detailed.get("branch_id") == candidate.get("branch_id"),
            "endpoint_detail_branch_mismatch",
        ),
        (
            str(detailed.get("host", "")).lower() == target.host,
            "endpoint_detail_host_mismatch",
        ),
        (detailed.get("type") == "read_write", "endpoint_detail_type_mismatch"),
        (current_state in accepted_states, "endpoint_detail_not_active"),
        (detailed.get("disabled") is False, "endpoint_detail_disabled"),
        (
            not _is_pooler_host(str(detailed.get("host", "")).lower()),
            "endpoint_detail_pooled",
        ),
        (pending_state is None, "endpoint_detail_transitioning"),
    )
    for passed, gate in comparisons:
        if not passed:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    return detailed


def _positive_ownership_witness(
    client: NeonReadOnlyClient,
    target: DirectPostgresTarget,
    audit: IdentityAudit,
    project_summary: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    allow_idle: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    project_id = _safe_identifier(project_summary.get("id", ""), gate="project_pagination_invalid")
    endpoint_id = _safe_identifier(
        candidate.get("id", ""), gate="positive_endpoint_candidate_invalid"
    )
    branch_id = _safe_identifier(
        candidate.get("branch_id", ""), gate="positive_endpoint_candidate_invalid"
    )
    client.require_get_budget(
        POSITIVE_WITNESS_GET_RESERVE,
        "project_identity_discovery_budget_exceeded",
    )
    endpoint_document = client.get(f"/projects/{project_id}/endpoints/{endpoint_id}")
    audit.endpoint_detail_reads += 1
    detailed_endpoint = _endpoint_detail(
        endpoint_document,
        project_id=project_id,
        candidate=candidate,
        target=target,
        allow_idle=allow_idle,
    )
    audit.positive_witness_checks.append("ENDPOINT_DETAIL_CONCORDANT")

    project_document = client.get(f"/projects/{project_id}")
    audit.project_detail_reads += 1
    detailed_project = _validated_project_detail(
        project_document,
        project_id,
        expected_owner_id=str(project_summary["owner_id"]),
        expected_organization_id=cast(str, audit.owner_id),
        gate="project_detail_id_or_owner_mismatch",
    )
    audit.positive_witness_checks.append("PROJECT_DETAIL_CONCORDANT")

    branches = _list_branches_bounded(
        client,
        project_id,
        audit,
        reserve_after=1,
    )
    branch_matches = [branch for branch in branches if branch.get("id") == branch_id]
    if len(branch_matches) != 1:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "branch_relationship_missing",
        )
    branch = branch_matches[0]
    default_branches = [item for item in branches if item.get("default") is True]
    if len(default_branches) != 1 or default_branches[0].get("id") != branch_id:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "default_branch_not_unique")
    if str(branch.get("project_id", "")) != project_id:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "branch_project_mismatch",
        )
    if branch.get("default") is not True:
        raise PreflightNoGo(
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
            "dsn_branch_is_not_default",
        )
    if _branch_state(branch) != "ready":
        raise PreflightNoGo(
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
            "production_branch_not_ready",
        )
    audit.positive_witness_checks.append("DEFAULT_BRANCH_RELATIONSHIP_CONCORDANT")

    branch_endpoint_document = client.get(f"/projects/{project_id}/branches/{branch_id}/endpoints")
    audit.branch_endpoint_reads += 1
    branch_endpoints = _project_endpoints(
        branch_endpoint_document,
        project_id,
        expected_branch_id=branch_id,
        gate="branch_endpoint_confirmation_mismatch",
    )
    confirmations = [item for item in branch_endpoints if item.get("id") == endpoint_id]
    if len(confirmations) != 1:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "branch_endpoint_confirmation_mismatch",
        )
    confirmation = confirmations[0]
    if (
        confirmation.get("branch_id") != branch_id
        or str(confirmation.get("host", "")).lower() != target.host
        or confirmation.get("type") != "read_write"
        or confirmation.get("disabled") is not False
        or _is_pooler_host(str(confirmation.get("host", "")).lower())
    ):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "branch_endpoint_confirmation_mismatch",
        )
    audit.positive_witness_checks.append("BRANCH_ENDPOINT_CONCORDANT")
    return detailed_project, branches, detailed_endpoint


def _assert_project_endpoint_branches(
    endpoints: Sequence[Mapping[str, Any]],
    branches: Sequence[Mapping[str, Any]],
) -> None:
    """Bind every project endpoint row to the exhaustive branch inventory."""

    branch_ids = {str(branch.get("id", "")) for branch in branches}
    if any(str(endpoint.get("branch_id", "")) not in branch_ids for endpoint in endpoints):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "branch_endpoint_confirmation_mismatch",
        )


def _resolve_neon_identity(
    client: NeonReadOnlyClient,
    target: DirectPostgresTarget,
    *,
    allow_idle: bool = False,
) -> NeonObservation:
    configured = os.getenv("NEON_PROJECT_ID", "").strip()
    if configured and len(configured) < 8:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "configured_project_invalid",
        )
    audit = IdentityAudit(
        identity_path=("CONFIGURED_PROJECT_ID" if configured else "BOUNDED_DISCOVERY")
    )
    try:
        configured_project_id = (
            _safe_identifier(configured, gate="configured_project_invalid") if configured else None
        )
        _prove_owner_scope(client, audit)
        if configured_project_id is not None:
            project_id = configured_project_id
            audit.project_id = project_id
            projects = _list_projects_bounded(client, audit)
            configured_summaries = [
                project for project in projects if project.get("id") == project_id
            ]
            if len(configured_summaries) != 1:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "configured_project_not_accessible",
                )
            client.require_get_budget(
                1 + len(audit.project_ids) + POSITIVE_WITNESS_GET_RESERVE,
                "neon_get_budget_exhausted",
            )
            endpoints = _project_endpoints(
                client.get(f"/projects/{project_id}/endpoints"),
                project_id,
                gate="configured_project_endpoint_missing",
            )
            audit.endpoint_projects_inspected = 1
            _count_owner_branches(client, audit)
            matches = [
                endpoint for endpoint in endpoints if str(endpoint["host"]).lower() == target.host
            ]
            if not matches:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "configured_project_endpoint_missing",
                )
            if len(matches) != 1:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "configured_project_endpoint_not_unique",
                )
            endpoint = matches[0]
            audit.positive_witness_checks.extend(
                [
                    "EXACT_DSN_HOST_MATCH",
                    "PROJECT_SCOPED_ENDPOINT_INVENTORY",
                ]
            )
            detailed, branches, endpoint = _positive_ownership_witness(
                client,
                target,
                audit,
                configured_summaries[0],
                endpoint,
                allow_idle=allow_idle,
            )
            _assert_project_endpoint_branches(endpoints, branches)
            identity_verdict = "CONFIGURED_PROJECT_IDENTITY_PROVEN"
        else:
            audit.identity_path = "POSITIVE_ENDPOINT_WITNESS"
            project, candidate, project_endpoints = _progressive_positive_candidate(
                client, target, audit
            )
            audit.project_id = _safe_identifier(project.get("id", ""))
            audit.endpoint_id = _safe_identifier(candidate.get("id", ""))
            audit.branch_id = _safe_identifier(candidate.get("branch_id", ""))
            audit.positive_witness_checks.extend(
                [
                    "EXACT_DSN_HOST_MATCH",
                    "PROJECT_SCOPED_ENDPOINT_INVENTORY",
                ]
            )
            detailed, branches, endpoint = _positive_ownership_witness(
                client,
                target,
                audit,
                project,
                candidate,
                allow_idle=allow_idle,
            )
            _assert_project_endpoint_branches(project_endpoints, branches)
            identity_verdict = "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
        return _finalize_neon_identity(
            client=client,
            target=target,
            audit=audit,
            identity_verdict=identity_verdict,
            detailed=detailed,
            branches=branches,
            endpoint=endpoint,
            allow_idle=allow_idle,
        )
    except PreflightNoGo as error:
        if error.sanitized_evidence is not None:
            raise
        raise PreflightNoGo(
            error.reason,
            error.gate,
            sanitized_evidence=audit.sanitized(
                api_get_count=client.get_count,
                gate=error.gate,
            ),
        ) from None


def _finalize_neon_identity(
    *,
    client: NeonReadOnlyClient,
    target: DirectPostgresTarget,
    audit: IdentityAudit,
    identity_verdict: str,
    detailed: Mapping[str, Any],
    branches: Sequence[Mapping[str, Any]],
    endpoint: Mapping[str, Any],
    allow_idle: bool = False,
) -> NeonObservation:
    project_id = _safe_identifier(detailed.get("id", ""))
    branches_by_id = {
        str(branch.get("id", "")): branch
        for branch in branches
        if isinstance(branch.get("id"), str)
    }
    branch = branches_by_id.get(str(endpoint.get("branch_id", "")))
    if branch is None:
        gate = (
            "configured_project_endpoint_missing"
            if audit.identity_path == "CONFIGURED_PROJECT_ID"
            else "dsn_endpoint_match_missing"
        )
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    branch_id = _safe_identifier(branch.get("id", ""))
    endpoint_id = _safe_identifier(endpoint.get("id", ""))
    audit.project_id = project_id
    audit.branch_id = branch_id
    audit.endpoint_id = endpoint_id
    endpoint_host = str(endpoint.get("host", "")).lower()
    branch_name = str(branch.get("name", ""))
    branch_default_value = branch.get("default")
    if not isinstance(branch_default_value, bool):
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_default_contract_invalid")
    branch_default = branch_default_value
    project_name = str(detailed.get("name", ""))
    endpoint_state_value = endpoint.get("current_state")
    if not isinstance(endpoint_state_value, str):
        raise PreflightNoGo("DIRECT_ENDPOINT_NOT_PROVEN", "endpoint_state_contract_invalid")
    endpoint_state = endpoint_state_value
    branch_state = _branch_state(branch)
    accepted_states = {"active", "idle"} if allow_idle else {"active"}
    pending_state = endpoint.get("pending_state")
    if allow_idle and endpoint_state not in accepted_states:
        raise PreflightNoGo(
            "ENDPOINT_STATE_UNSUPPORTED",
            "endpoint_state_unsupported",
        )
    endpoint_execution_state_accepted = endpoint_state == "active" or (
        allow_idle and endpoint_state == "idle"
    )
    direct = (
        endpoint_host == target.host
        and endpoint_host.endswith(".neon.tech")
        and not _is_pooler_host(endpoint_host)
        and endpoint.get("type") == "read_write"
        and endpoint_execution_state_accepted
        and endpoint.get("disabled") is False
        and pending_state is None
        and endpoint.get("project_id") == project_id
    )
    if not direct:
        raise PreflightNoGo("DIRECT_ENDPOINT_NOT_PROVEN", "endpoint_not_direct")
    if branch_state != "ready":
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "production_branch_not_ready")
    if not branch_default:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "dsn_branch_is_not_default")
    owner = detailed.get("owner")
    if not isinstance(owner, dict):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "branch_limit_contract_missing")
    branch_limit = _bounded_int(
        owner.get("branches_limit"),
        minimum=1,
        reason="RECOVERY_BRANCH_NOT_FEASIBLE",
        gate="branch_limit_contract_invalid",
    )
    subscription_type = owner.get("subscription_type")
    if not isinstance(subscription_type, str):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "subscription_type_contract_missing",
        )
    subscription_plan = {
        "free_v2": "free",
        "free_v3": "free",
        "launch": "launch",
        "launch_v3": "launch",
        "scale": "scale",
        "scale_v3": "scale",
    }
    billing_plan = audit.billing_plan
    if billing_plan not in {"free", "launch", "scale"}:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "purchase_requirement_ambiguous",
        )
    if subscription_type != "UNKNOWN" and (
        subscription_type not in subscription_plan
        or subscription_plan[subscription_type] != billing_plan
    ):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "billing_plan_subscription_contradiction",
        )
    free_branch_allowances = {"free": 10, "launch": 10, "scale": 25}
    counted_target_branches = audit.branch_counts_by_project.get(project_id)
    if counted_target_branches is None:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "target_project_branch_count_not_proven",
        )
    if counted_target_branches != len(branches):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "branch_count_inventory_contradiction",
        )
    target_project_branch_count = counted_target_branches
    bill_free_branch_capacity_proven = (
        target_project_branch_count + 1 <= free_branch_allowances[billing_plan]
    )
    if audit.account_branch_limit is not None and audit.account_branch_limit != branch_limit:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "account_branch_limit_contradiction",
        )
    effective_permission = detailed.get("effective_project_permission")
    if effective_permission is not None and effective_permission != "ADMIN":
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "project_permission_insufficient_for_recovery",
        )
    history_retention_seconds = _bounded_int(
        detailed.get("history_retention_seconds"),
        minimum=0,
        reason="RECOVERY_BRANCH_NOT_FEASIBLE",
        gate="history_retention_contract_invalid",
    )
    postgresql_major = _bounded_int(
        detailed.get("pg_version"),
        minimum=min(SUPPORTED_NEON_POSTGRESQL_MAJORS),
        reason="DIRECT_ENDPOINT_NOT_PROVEN",
        gate="project_postgresql_version_contract_invalid",
    )
    if postgresql_major not in SUPPORTED_NEON_POSTGRESQL_MAJORS:
        raise PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            "project_postgresql_version_unsupported",
        )
    if postgresql_major not in SUPPORTED_CHRONOS_POSTGRESQL_MAJORS:
        raise PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            "chronos_postgresql_version_not_certified",
        )
    parent = branch.get("parent_id")
    parent_id = (
        None
        if parent is None
        else _safe_identifier(parent, gate="production_branch_parent_invalid")
    )
    if parent_id is not None:
        raise PreflightNoGo(
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
            "production_branch_parent_unexpected",
        )
    region = str(endpoint.get("region_id", detailed.get("region_id", "")))
    project_region = str(detailed.get("region_id", ""))
    endpoint_region = str(endpoint.get("region_id", ""))
    if project_region and endpoint_region and project_region != endpoint_region:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "project_endpoint_region_mismatch",
        )
    suspend_timeout = endpoint.get("suspend_timeout_seconds")
    autoscaling_limit = endpoint.get("autoscaling_limit_max_cu")
    if (
        isinstance(autoscaling_limit, bool)
        or not isinstance(autoscaling_limit, (int, float))
        or not math.isfinite(float(autoscaling_limit))
        or autoscaling_limit < 0.25
    ):
        raise PreflightNoGo(
            "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
            "autoscaling_limit_contract_invalid",
        )
    if allow_idle:
        if isinstance(suspend_timeout, bool) or not isinstance(suspend_timeout, int):
            raise PreflightNoGo(
                "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
                "suspend_timeout_contract_invalid",
            )
        if suspend_timeout < -1 or suspend_timeout > 604_800 or 0 < suspend_timeout < 60:
            raise PreflightNoGo(
                "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
                "suspend_timeout_contract_invalid",
            )
    elif isinstance(suspend_timeout, bool) or not isinstance(suspend_timeout, int):
        suspend_timeout = -1
    return NeonObservation(
        identity_path=audit.identity_path,
        identity_verdict=identity_verdict,
        project_id=project_id,
        project_name=project_name,
        region=region,
        branch_id=branch_id,
        branch_name=branch_name,
        branch_default=branch_default,
        branch_parent_id=parent_id,
        endpoint_id=endpoint_id,
        endpoint_host=endpoint_host,
        endpoint_state=endpoint_state,
        suspend_timeout_seconds=suspend_timeout,
        branch_state=branch_state,
        owner_id=str(audit.owner_id),
        owner_branch_count=audit.owner_branch_count,
        branch_limit=branch_limit,
        history_retention_seconds=history_retention_seconds,
        postgresql_major=postgresql_major,
        project_pages_read=audit.project_pages_read,
        projects_observed=audit.projects_observed,
        endpoint_projects_inspected=audit.endpoint_projects_inspected,
        api_get_count=client.get_count,
        project_inventory_exhaustive=audit.project_inventory_exhaustive,
        endpoint_detail_reads=audit.endpoint_detail_reads,
        project_detail_reads=audit.project_detail_reads,
        branch_pages_read=audit.branch_pages_read,
        branch_endpoint_reads=audit.branch_endpoint_reads,
        cursor_continuation_requested=audit.cursor_continuation_requested,
        cursor_cycle_encountered=audit.cursor_cycle_encountered,
        positive_witness_checks=tuple(audit.positive_witness_checks),
        branch_capacity_proven=(
            audit.owner_scope_proven
            and audit.project_inventory_exhaustive
            and bool(audit.project_ids)
            and audit.branch_count_reads == len(audit.project_ids)
        ),
        autoscaling_limit_max_cu=float(autoscaling_limit),
        owner_scope_verdict=audit.owner_scope_verdict,
        branch_count_reads=audit.branch_count_reads,
        subscription_type=subscription_type,
        billing_plan=billing_plan,
        target_project_branch_count=target_project_branch_count,
        bill_free_branch_capacity_proven=bill_free_branch_capacity_proven,
    )


def resolve_neon_identity_readonly(
    api_key: str,
    target: DirectPostgresTarget,
    *,
    allow_idle: bool = False,
) -> NeonObservation:
    """Resolve a Neon identity through the bounded, GET-only proof path."""

    return _resolve_neon_identity(
        NeonReadOnlyClient(api_key),
        target,
        allow_idle=allow_idle,
    )


def require_neon_recovery_feasibility(neon: NeonObservation) -> None:
    """Fail closed unless one recovery branch is proven feasible without purchase."""

    if not neon.branch_capacity_proven:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "branch_capacity_ambiguous",
        )
    if neon.owner_branch_count + 1 > neon.branch_limit:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "branch_capacity_exhausted",
        )
    if not neon.bill_free_branch_capacity_proven:
        raise PreflightNoGo("PURCHASE_REQUIRED", "purchase_required")
    if neon.history_retention_seconds <= 0 or neon.branch_id == "" or neon.branch_state != "ready":
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            "recovery_branch_not_feasible",
        )


def _milliseconds(value: object) -> int:
    text = str(value).strip().lower()
    units = (("ms", 1), ("s", 1_000), ("min", 60_000))
    for suffix, multiplier in units:
        if text.endswith(suffix):
            number = text[: -len(suffix)].strip()
            try:
                return int(float(number) * multiplier)
            except (OverflowError, ValueError):
                break
    raise PreflightNoGo("DIRECT_ENDPOINT_NOT_PROVEN", "timeout_setting_invalid")


def _validated_psycopg_url(database_url: str) -> tuple[str, DirectPostgresTarget]:
    """Return a psycopg DSN accepted by the shared canonical validator."""

    try:
        target = validate_direct_postgres_url(database_url)
    except ChronosProductionError as error:
        parameter_gates = {
            "CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN",
            "CHRONOS_CHANNEL_BINDING_REQUIRED",
        }
        raise PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            (
                "database_url_parameters_forbidden"
                if str(error) in parameter_gates
                else "direct_database_url_invalid"
            ),
            dsn_security_profile=_invalid_dsn_security_profile(database_url),
        ) from None
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return normalized, target


def _reject_libpq_environment() -> None:
    """Prevent ambient libpq variables from changing the validated URI target."""

    names = libpq_environment_variable_names()
    if names:
        raise PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            "libpq_environment_forbidden",
            sanitized_evidence={
                "libpq_environment_variable_count": len(names),
                "libpq_environment_name_hashes": [_fingerprint(name) for name in names],
            },
        )


def _target_dsn_security_profile(
    target: DirectPostgresTarget,
) -> dict[str, object]:
    query_keys = ["sslmode"]
    query_keys.append("channel_binding")
    return {
        "contract_verdict": "NEON_BOOTSTRAP_DSN_MATCHES_CURRENT_SECURE_CONTRACT",
        "query_keys": sorted(query_keys),
        "sslmode": target.sslmode,
        "channel_binding": target.channel_binding,
        "port": target.port,
        "ambient_libpq_environment_count": 0,
        "unexpected_parameter_count": 0,
        "unexpected_parameter_name_hashes": [],
    }


def _invalid_dsn_security_profile(database_url: str) -> dict[str, object]:
    """Describe only reviewed keys; hash every unreviewed query-key name."""

    try:
        parsed = urlparse(database_url)
        query_items = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
    except (TypeError, UnicodeError, ValueError):
        return {
            "contract_verdict": ("NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT"),
            "query_parse": "INVALID",
            "unexpected_parameter_count": 0,
            "unexpected_parameter_name_hashes": [],
        }
    reviewed_keys = frozenset({"sslmode", "channel_binding"})
    unexpected = [key for key, _ in query_items if key not in reviewed_keys]
    profile: dict[str, object] = {
        "contract_verdict": ("NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT"),
        "reviewed_query_keys": sorted({key for key, _ in query_items if key in reviewed_keys}),
        "unexpected_parameter_count": len(unexpected),
        "unexpected_parameter_name_hashes": sorted(_fingerprint(key) for key in unexpected),
    }
    values: dict[str, list[str]] = {}
    for key, value in query_items:
        if key in reviewed_keys:
            values.setdefault(key, []).append(value)
    ssl_values = values.get("sslmode", [])
    if len(ssl_values) == 1 and ssl_values[0] in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        profile["sslmode"] = ssl_values[0]
    binding_values = values.get("channel_binding", [])
    if len(binding_values) == 1 and binding_values[0] == "require":
        profile["channel_binding"] = "require"
    return profile


def _one(cursor: psycopg.Cursor[dict[str, Any]]) -> dict[str, Any]:
    row = cursor.fetchone()
    if row is None:
        raise PreflightNoGo("DIRECT_ENDPOINT_NOT_PROVEN", "postgresql_row_missing")
    return row


def _execute_readonly(
    cursor: psycopg.Cursor[dict[str, Any]],
    statement: str,
    audit: DatabaseInspectionAudit,
) -> None:
    audit.before_execute(statement)
    try:
        validate_data_torrent_authority()
        cursor.execute(statement)
    except Exception:
        audit.inspection_failure_class = (
            "ROLLBACK_EXCEPTION"
            if statement == SQL_STATEMENTS[SQL_ROLLBACK]
            else "SQL_EXECUTION_EXCEPTION"
        )
        raise
    audit.after_execute(statement)


def _read_revisions(
    cursor: psycopg.Cursor[dict[str, Any]],
    audit: DatabaseInspectionAudit | None = None,
) -> tuple[str, ...]:
    try:
        if audit is None:
            cursor.execute(SQL_STATEMENTS[SQL_REVISION])
        else:
            _execute_readonly(cursor, SQL_STATEMENTS[SQL_REVISION], audit)
        return tuple(str(row["version_num"]) for row in cursor.fetchall())
    except Exception:
        raise PreflightNoGo(
            "UNEXPECTED_DATABASE_REVISION", "alembic_revision_unavailable"
        ) from None


def _read_authority_inventory(
    cursor: psycopg.Cursor[dict[str, Any]],
    audit: DatabaseInspectionAudit | None = None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    try:
        if audit is None:
            cursor.execute(SQL_STATEMENTS[SQL_LIFECYCLE_ADMIN])
        else:
            _execute_readonly(cursor, SQL_STATEMENTS[SQL_LIFECYCLE_ADMIN], audit)
        lifecycle_admin = _one(cursor)
        if audit is None:
            cursor.execute(SQL_STATEMENTS[SQL_PRIVILEGED_CATALOG])
        else:
            _execute_readonly(cursor, SQL_STATEMENTS[SQL_PRIVILEGED_CATALOG], audit)
        catalog = _one(cursor)
        if audit is None:
            cursor.execute(SQL_STATEMENTS[SQL_CHRONOS_ROLES])
        else:
            _execute_readonly(cursor, SQL_STATEMENTS[SQL_CHRONOS_ROLES], audit)
        roles = tuple(cast(dict[str, object], row) for row in cursor.fetchall())
        if audit is None:
            cursor.execute(SQL_STATEMENTS[SQL_CHRONOS_MEMBERSHIPS])
        else:
            _execute_readonly(cursor, SQL_STATEMENTS[SQL_CHRONOS_MEMBERSHIPS], audit)
        memberships = tuple(cast(dict[str, object], row) for row in cursor.fetchall())
        if audit is None:
            cursor.execute(SQL_STATEMENTS[SQL_CHRONOS_OBJECTS])
        else:
            _execute_readonly(cursor, SQL_STATEMENTS[SQL_CHRONOS_OBJECTS], audit)
        objects = tuple(cast(dict[str, object], row) for row in cursor.fetchall())
        return lifecycle_admin, catalog, roles, memberships, objects
    except Exception:
        raise PreflightNoGo(
            "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
            "bootstrap_authority_inspection_failed",
        ) from None


def _inspect_database(
    database_url: str,
    *,
    expected_postgresql_major: int,
    expected_revisions: tuple[str, ...] = (EXPECTED_REVISION,),
    before_connect: Callable[[], None] | None = None,
    after_connect: Callable[[], None] | None = None,
    inspection_audit: DatabaseInspectionAudit | None = None,
) -> DatabaseObservation:
    audit = inspection_audit or DatabaseInspectionAudit()
    safe_database_url, target = _validated_psycopg_url(database_url)
    connection: psycopg.Connection[dict[str, Any]] | None = None
    pending_error: PreflightNoGo | None = None
    default_read_only = ""
    transaction_read_only = ""
    statement_timeout_ms = 0
    lock_timeout_ms = 0
    search_path = ""
    database_name: object = None
    session_user: object = None
    current_user: object = None
    version: object = None
    version_num = 0
    ssl_row: dict[str, Any] = {}
    revisions: tuple[str, ...] = ()
    lifecycle_admin: dict[str, Any] = {}
    catalog: dict[str, Any] = {}
    roles: tuple[dict[str, object], ...] = ()
    memberships: tuple[dict[str, object], ...] = ()
    objects: tuple[dict[str, object], ...] = ()
    capabilities: dict[str, Any] = {}
    capability_names = (
        "schema_usage_grantable",
        "schema_create_grantable",
        "table_select_grantable",
        "table_insert_grantable",
        "table_update_grantable",
        "table_delete_grantable",
        "authority_role_memberships_clean",
    )
    try:
        _reject_libpq_environment()
        if before_connect is not None:
            before_connect()
        try:
            validate_data_torrent_authority()
        except ChronosProductionError:
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE", "mission_authority_inactive"
            ) from None
        audit.connection_attempt_count += 1
        connection = psycopg.connect(
            safe_database_url,
            host=target.host,
            port=target.port,
            dbname=target.database,
            user=target.username,
            autocommit=True,
            sslmode=target.sslmode,
            channel_binding=target.channel_binding,
            connect_timeout=10,
            options=READONLY_STARTUP_OPTIONS,
            row_factory=dict_row,
        )
        audit.connection_success_count += 1
        if after_connect is not None:
            after_connect()
        with connection.cursor() as cursor:
            inspection_error: Exception | None = None
            try:
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_BEGIN_READ_ONLY], audit)
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_DEFAULT_TRANSACTION_READ_ONLY], audit)
                default_read_only = str(_one(cursor)["default_transaction_read_only"])
                audit.default_transaction_read_only = default_read_only == "on"
                if default_read_only != "on":
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "default_transaction_read_only_not_enforced",
                    )
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_TRANSACTION_READ_ONLY], audit)
                transaction_read_only = str(_one(cursor)["transaction_read_only"])
                audit.transaction_read_only = transaction_read_only == "on"
                if transaction_read_only != "on":
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "transaction_read_only_not_enforced",
                    )
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_STATEMENT_TIMEOUT], audit)
                statement_timeout_ms = _milliseconds(next(iter(_one(cursor).values())))
                audit.statement_timeout_ms = statement_timeout_ms
                if statement_timeout_ms != EXPECTED_STATEMENT_TIMEOUT_MS:
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "statement_timeout_not_enforced",
                    )
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_LOCK_TIMEOUT], audit)
                lock_timeout_ms = _milliseconds(next(iter(_one(cursor).values())))
                audit.lock_timeout_ms = lock_timeout_ms
                if lock_timeout_ms != EXPECTED_LOCK_TIMEOUT_MS:
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "lock_timeout_not_enforced",
                    )
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_SEARCH_PATH], audit)
                search_path = str(next(iter(_one(cursor).values())))
                audit.search_path_pg_catalog = search_path == "pg_catalog"
                if search_path != "pg_catalog":
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "search_path_not_enforced",
                    )
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_IDENTITY], audit)
                identity = _one(cursor)
                database_name = identity.get("current_database")
                session_user = identity.get("session_user")
                current_user = identity.get("current_user")
                version = identity.get("postgresql_version")
                version_num_value = identity.get("postgresql_version_num")
                if not all(
                    isinstance(value, str)
                    for value in (
                        database_name,
                        session_user,
                        current_user,
                        version,
                        version_num_value,
                    )
                ):
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "postgresql_identity_contract_invalid",
                    )
                try:
                    version_num = int(cast(str, version_num_value))
                except ValueError:
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "postgresql_version_contract_invalid",
                    ) from None
                audit.database_target_verified = database_name == target.database
                audit.principal_target_verified = (
                    session_user == target.username and current_user == session_user
                )
                audit.postgresql_version_num = version_num
                audit.postgresql_major_verified = version_num // 10000 == expected_postgresql_major
                if not audit.database_target_verified or not audit.principal_target_verified:
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "postgresql_target_identity_mismatch",
                    )
                if version_num // 10000 != expected_postgresql_major:
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "postgresql_major_version_mismatch",
                    )
                if cast(str, current_user).startswith("chronos_"):
                    raise PreflightNoGo(
                        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
                        "lifecycle_admin_role_forbidden",
                    )
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_SSL], audit)
                ssl_row = _one(cursor)
                audit.ssl_verified = ssl_row.get("ssl") is True
                if ssl_row.get("ssl") is not True:
                    raise PreflightNoGo(
                        "DIRECT_ENDPOINT_NOT_PROVEN",
                        "ssl_not_proven",
                    )

                # Catalog-only proof precedes the first read of a user object.
                _execute_readonly(
                    cursor,
                    SQL_STATEMENTS[SQL_TARGET_CLASSIFICATION_BEFORE_LOCK],
                    audit,
                )
                capabilities = _one(cursor)
                targets_valid = (
                    capabilities.get("public_schema_exists") is True
                    and capabilities.get("alembic_version_is_plain_permanent_table") is True
                )
                audit.alembic_target_safe = targets_valid
                if not targets_valid:
                    raise PreflightNoGo(
                        "UNEXPECTED_DATABASE_REVISION",
                        "alembic_target_not_plain_permanent_table",
                    )

                _execute_readonly(cursor, SQL_STATEMENTS[SQL_LOCK_ALEMBIC_VERSION], audit)
                _execute_readonly(
                    cursor,
                    SQL_STATEMENTS[SQL_TARGET_CLASSIFICATION_AFTER_LOCK],
                    audit,
                )
                locked_capabilities = _one(cursor)
                if locked_capabilities != capabilities:
                    raise PreflightNoGo(
                        "UNEXPECTED_DATABASE_REVISION",
                        "alembic_target_changed_before_lock",
                    )
                capabilities = locked_capabilities

                revisions = _read_revisions(cursor, audit)
                audit.revision_count = len(revisions)
                audit.revision = revisions[0] if len(revisions) == 1 else None
                if len(revisions) != 1 or revisions[0] not in expected_revisions:
                    raise PreflightNoGo(
                        "UNEXPECTED_DATABASE_REVISION",
                        "unexpected_database_revision",
                    )

                _execute_readonly(cursor, SQL_STATEMENTS[SQL_LIFECYCLE_ADMIN], audit)
                lifecycle_admin = _one(cursor)
                authority_capabilities_proven = not (
                    lifecycle_admin.get("rolcanlogin") is not True
                    or (
                        lifecycle_admin.get("rolsuper") is not True
                        and lifecycle_admin.get("rolcreaterole") is not True
                    )
                    or any(capabilities.get(name) is not True for name in capability_names)
                )
                audit.bootstrap_authority_capabilities_proven = authority_capabilities_proven
                if not authority_capabilities_proven:
                    raise PreflightNoGo(
                        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
                        "bootstrap_authority_capabilities_insufficient",
                    )

                try:
                    _execute_readonly(cursor, SQL_STATEMENTS[SQL_PRIVILEGED_CATALOG], audit)
                    catalog = _one(cursor)
                except psycopg.errors.InsufficientPrivilege:
                    audit.privileged_catalog_visible = False
                    raise PreflightNoGo(
                        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
                        "privileged_catalog_not_visible",
                    ) from None
                audit.privileged_catalog_visible = catalog.get("visible") is True
                if catalog.get("visible") is not True:
                    raise PreflightNoGo(
                        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
                        "privileged_catalog_not_visible",
                    )
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_CHRONOS_ROLES], audit)
                roles = tuple(cast(dict[str, object], row) for row in cursor.fetchall())
                audit.chronos_roles_clean = not roles
                if roles:
                    raise PreflightNoGo(
                        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
                        "existing_chronos_roles_unsafe",
                    )
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_CHRONOS_MEMBERSHIPS], audit)
                memberships = tuple(cast(dict[str, object], row) for row in cursor.fetchall())
                audit.chronos_memberships_clean = not memberships
                if memberships:
                    raise PreflightNoGo(
                        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
                        "existing_chronos_memberships_unsafe",
                    )
                _execute_readonly(cursor, SQL_STATEMENTS[SQL_CHRONOS_OBJECTS], audit)
                objects = tuple(cast(dict[str, object], row) for row in cursor.fetchall())
                audit.chronos_objects_clean = not objects
                if objects:
                    raise PreflightNoGo(
                        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
                        "existing_chronos_objects_unsafe",
                    )
            except Exception as error:
                if (
                    not isinstance(error, PreflightNoGo)
                    and audit.inspection_failure_class == "NOT_OBSERVED"
                ):
                    audit.inspection_failure_class = "RESULT_PROCESSING_EXCEPTION"
                inspection_error = error
            if audit.begin_read_only_completed and not audit.rollback_attempted:
                primary_failure_class = audit.inspection_failure_class
                try:
                    _execute_readonly(cursor, SQL_STATEMENTS[SQL_ROLLBACK], audit)
                except Exception:
                    if inspection_error is not None:
                        audit.inspection_failure_class = primary_failure_class
                    else:
                        raise
            if inspection_error is not None:
                raise inspection_error
    except PreflightNoGo as error:
        pending_error = error
    except Exception:
        if audit.inspection_failure_class == "NOT_OBSERVED":
            audit.inspection_failure_class = (
                "CONNECTION_EXCEPTION"
                if audit.connection_success_count == 0
                else "CONTROL_FLOW_EXCEPTION"
            )
        pending_error = PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            "postgresql_readonly_inspection_failed",
        )
    finally:
        if connection is not None:
            audit.connection_close_completed = False
            try:
                connection.close()
            except Exception:
                audit.connection_close_completed = False
                if pending_error is None:
                    audit.inspection_failure_class = "CLOSE_EXCEPTION"
            else:
                audit.connection_close_completed = True
    if pending_error is not None:
        raise PreflightNoGo(
            pending_error.reason,
            pending_error.gate,
            dsn_security_profile=pending_error.dsn_security_profile,
            sanitized_evidence=pending_error.sanitized_evidence,
            sanitized_postgresql_evidence=(
                audit.sanitized_evidence()
                if audit.connection_attempt_count
                else pending_error.sanitized_postgresql_evidence
            ),
            effect_counts=audit.effects(),
        ) from None
    if audit.connection_close_completed is False:
        raise PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            "postgresql_connection_close_failed",
            sanitized_postgresql_evidence=audit.sanitized_evidence(),
            effect_counts=audit.effects(),
        )
    if audit.sql_statement_count > MAX_SQL_STATEMENTS:
        raise PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            "sql_budget_exhausted",
            sanitized_postgresql_evidence=audit.sanitized_evidence(),
            effect_counts=audit.effects(),
        )
    grantable = tuple(name for name in capability_names if capabilities.get(name) is True)
    targets_valid = (
        capabilities.get("public_schema_exists") is True
        and capabilities.get("alembic_version_is_plain_permanent_table") is True
    )
    return DatabaseObservation(
        database_name=cast(str, database_name),
        session_user=cast(str, session_user),
        current_user=cast(str, current_user),
        postgresql_version=cast(str, version),
        ssl=ssl_row["ssl"] is True,
        revision=revisions[0] if len(revisions) == 1 else "NOT_SINGLETON",
        revision_count=len(revisions),
        default_transaction_read_only=default_read_only == "on",
        transaction_read_only=transaction_read_only == "on",
        statement_timeout_ms=statement_timeout_ms,
        lock_timeout_ms=lock_timeout_ms,
        lifecycle_admin_can_login=lifecycle_admin.get("rolcanlogin") is True,
        lifecycle_admin_superuser=lifecycle_admin.get("rolsuper") is True,
        lifecycle_admin_createrole=lifecycle_admin.get("rolcreaterole") is True,
        privileged_catalog_visible=catalog.get("visible") is True,
        chronos_roles=roles,
        chronos_memberships=memberships,
        chronos_objects=objects,
        sql_statement_count=audit.sql_statement_count,
        postgresql_version_num=version_num,
        bootstrap_grantable_capabilities=grantable,
        sql_read_count=audit.sql_read_count,
        bootstrap_targets_valid=targets_valid,
        sql_statement_completed_count=audit.sql_statement_completed_count,
        sql_read_attempt_count=audit.sql_read_attempt_count,
    )


def _github_get(path: str) -> dict[str, Any]:
    token = _required_sensitive_context("GITHUB_TOKEN")
    try:
        validate_data_torrent_authority()
    except ChronosProductionError:
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "mission_authority_inactive") from None
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            "https://api.github.com" + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_state_unavailable"
        ) from None
    finally:
        session.close()
    if not 200 <= response.status_code < 300:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            f"github_actions_http_{response.status_code}",
        )
    try:
        document = response.json(object_pairs_hook=_unique_json_object)
    except (TypeError, ValueError):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_state_invalid"
        ) from None
    if not isinstance(document, dict):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_state_invalid")
    return cast(dict[str, Any], document)


def _github_actions_state(
    repository: str,
    run_id: int,
    main_sha: str,
    *,
    workflow_file: str = "chronos-neon-pure-readonly-preflight-v4.yml",
) -> tuple[int, int, int]:
    def validated_runs(
        document: Mapping[str, Any],
        gate: str,
        *,
        expected_status: str | None = None,
    ) -> list[dict[str, Any]]:
        runs = document.get("workflow_runs")
        total_count = document.get("total_count")
        if (
            not isinstance(runs, list)
            or not all(isinstance(run, dict) for run in runs)
            or isinstance(total_count, bool)
            or not isinstance(total_count, int)
            or total_count != len(runs)
            or total_count > 100
        ):
            raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", gate)
        typed = cast(list[dict[str, Any]], runs)
        seen_run_ids: set[int] = set()
        for run in typed:
            run_identifier = run.get("id")
            if (
                isinstance(run_identifier, bool)
                or not isinstance(run_identifier, int)
                or run_identifier < 1
            ):
                raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", gate)
            if run_identifier in seen_run_ids:
                raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", gate)
            seen_run_ids.add(run_identifier)
            if expected_status is not None and run.get("status") != expected_status:
                raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", gate)
        return typed

    counts: dict[str, int] = {}
    for status in ("queued", "in_progress"):
        document = _github_get(f"/repos/{repository}/actions/runs?status={status}&per_page=100")
        runs = validated_runs(document, "github_actions_runs_invalid", expected_status=status)
        counts[status] = sum(1 for run in runs if run["id"] != run_id)
    dispatches = _github_get(
        f"/repos/{repository}/actions/workflows/"
        f"{workflow_file}/runs"
        f"?event=workflow_dispatch&head_sha={main_sha}&per_page=100"
    )
    runs = validated_runs(dispatches, "github_dispatch_history_invalid")
    if any(
        run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or isinstance(run.get("run_attempt"), bool)
        or not isinstance(run.get("run_attempt"), int)
        or run.get("run_attempt") != 1
        for run in runs
    ):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_dispatch_history_invalid")
    exact_dispatches = [run for run in runs if run.get("head_sha") == main_sha]
    if len(exact_dispatches) != len(runs):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_dispatch_history_invalid")
    if not any(run["id"] == run_id for run in exact_dispatches):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "current_dispatch_not_observed")
    # Bind the source last, immediately before returning authorization state, so
    # a main advance during the three Actions inventory reads fails closed.
    main_ref = _github_get(f"/repos/{repository}/git/ref/heads/main")
    ref_object = main_ref.get("object")
    if (
        main_ref.get("ref") != "refs/heads/main"
        or not isinstance(ref_object, dict)
        or ref_object.get("type") != "commit"
        or not isinstance(ref_object.get("sha"), str)
        or _HEX_SHA.fullmatch(cast(str, ref_object.get("sha"))) is None
    ):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_main_ref_invalid")
    if cast(str, ref_object["sha"]) != main_sha:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_main_ref_mismatch")
    return counts["queued"], counts["in_progress"], len(exact_dispatches)


def _github_authority_window_dispatch_count(
    repository: str,
    run_id: int,
    main_sha: str,
    *,
    workflow_file: str,
    not_before: str,
) -> int:
    """Count every dispatch in one immutable authority window, across all SHAs."""

    try:
        cutoff = datetime.fromisoformat(not_before.replace("Z", "+00:00"))
    except ValueError:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_authority_window_invalid"
        ) from None
    if (
        not not_before.endswith("Z")
        or cutoff.tzinfo is None
        or cutoff.utcoffset() != UTC.utcoffset(cutoff)
    ):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_authority_window_invalid")
    document = _github_get(
        f"/repos/{repository}/actions/workflows/{workflow_file}/runs"
        "?event=workflow_dispatch&per_page=100"
    )
    runs = document.get("workflow_runs")
    total_count = document.get("total_count")
    if (
        not isinstance(runs, list)
        or not all(isinstance(run, dict) for run in runs)
        or isinstance(total_count, bool)
        or not isinstance(total_count, int)
        or total_count != len(runs)
        or total_count > 100
    ):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_authority_dispatch_history_invalid"
        )
    seen: set[int] = set()
    authority_runs: list[dict[str, Any]] = []
    for raw_run in runs:
        run = cast(dict[str, Any], raw_run)
        identifier = run.get("id")
        created_at = run.get("created_at")
        if (
            isinstance(identifier, bool)
            or not isinstance(identifier, int)
            or identifier < 1
            or identifier in seen
            or run.get("event") != "workflow_dispatch"
            or not isinstance(created_at, str)
            or not created_at.endswith("Z")
        ):
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE",
                "github_authority_dispatch_history_invalid",
            )
        seen.add(identifier)
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE",
                "github_authority_dispatch_history_invalid",
            ) from None
        if created.tzinfo is None or created.utcoffset() != UTC.utcoffset(created):
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE",
                "github_authority_dispatch_history_invalid",
            )
        if created >= cutoff:
            authority_runs.append(run)
    current = [run for run in authority_runs if run.get("id") == run_id]
    if (
        len(current) != 1
        or current[0].get("head_branch") != "main"
        or current[0].get("head_sha") != main_sha
        or isinstance(current[0].get("run_attempt"), bool)
        or current[0].get("run_attempt") != 1
    ):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "current_authority_dispatch_not_observed"
        )
    return len(authority_runs)


def _bootstrap_authority_plausible(database: DatabaseObservation) -> bool:
    current_user = database.current_user
    forbidden = current_user == BOOTSTRAP_AUTHORITY or current_user.startswith(
        ("chronos_", "chronos_bootstrap_executor_")
    )
    required_capabilities = {
        "schema_usage_grantable",
        "schema_create_grantable",
        "table_select_grantable",
        "table_insert_grantable",
        "table_update_grantable",
        "table_delete_grantable",
        "authority_role_memberships_clean",
    }
    capabilities_proven = set(database.bootstrap_grantable_capabilities) == required_capabilities
    inventory_clean = (
        not database.chronos_roles
        and not database.chronos_memberships
        and not database.chronos_objects
    )
    return (
        database.session_user == current_user
        and database.lifecycle_admin_can_login
        and (database.lifecycle_admin_superuser or database.lifecycle_admin_createrole)
        and database.privileged_catalog_visible
        and database.bootstrap_targets_valid
        and capabilities_proven
        and inventory_clean
        and not forbidden
    )


def _sanitize_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    identity_keys: frozenset[str],
) -> list[dict[str, object]]:
    sanitized: list[dict[str, object]] = []
    for row in rows:
        item: dict[str, object] = {}
        for key, value in row.items():
            if key in identity_keys:
                item[f"{key}_sha256"] = _fingerprint(str(value))
            else:
                item[key] = value
        sanitized.append(item)
    return sanitized


def _sanitized_neon(neon: NeonObservation) -> dict[str, object]:
    positive = neon.identity_verdict == "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
    return {
        "identity_path": neon.identity_path,
        "identity_proof_mode": "POSITIVE_OWNERSHIP" if positive else neon.identity_path,
        "project_identity_verdict": neon.identity_verdict,
        "neon_project_identity_verdict": "NEON_PROJECT_IDENTITY_PROVEN",
        "project_inventory_exhaustive": neon.project_inventory_exhaustive,
        "project_pages_read": neon.project_pages_read,
        "projects_observed": neon.projects_observed,
        "endpoint_projects_inspected": neon.endpoint_projects_inspected,
        "endpoint_inventory_reads": neon.endpoint_projects_inspected,
        "endpoint_detail_reads": neon.endpoint_detail_reads,
        "project_detail_reads": neon.project_detail_reads,
        "branch_pages_read": neon.branch_pages_read,
        "branch_endpoint_reads": neon.branch_endpoint_reads,
        "cursor_continuation_requested": neon.cursor_continuation_requested,
        "cursor_cycle_encountered": neon.cursor_cycle_encountered,
        "positive_witness_checks": list(neon.positive_witness_checks),
        "project_id_sha256": _fingerprint(neon.project_id),
        "project_name_sha256": _fingerprint(neon.project_name),
        "region": _fingerprint(neon.region),
        "production_branch_id_sha256": _fingerprint(neon.branch_id),
        "production_branch_name_sha256": _fingerprint(neon.branch_name),
        "production_branch_default": neon.branch_default,
        "production_branch_parent_id_sha256": (
            _fingerprint(neon.branch_parent_id) if neon.branch_parent_id is not None else None
        ),
        "recovery_parent_id_sha256": _fingerprint(neon.branch_id),
        "endpoint_id_sha256": _fingerprint(neon.endpoint_id),
        "endpoint_host_sha256": _fingerprint(neon.endpoint_host),
        "endpoint_state": neon.endpoint_state,
        "suspend_timeout_seconds": neon.suspend_timeout_seconds,
        "branch_state": neon.branch_state,
        "owner_id_sha256": _fingerprint(neon.owner_id),
        "owner_branch_count": neon.owner_branch_count,
        "branch_limit": neon.branch_limit,
        "branch_capacity_proven": neon.branch_capacity_proven,
        "bill_free_branch_capacity_proven": neon.bill_free_branch_capacity_proven,
        "owner_scope_verdict": neon.owner_scope_verdict,
        "branch_count_reads": neon.branch_count_reads,
        "subscription_type": neon.subscription_type,
        "billing_plan": neon.billing_plan,
        "target_project_branch_count": neon.target_project_branch_count,
        "history_retention_seconds": neon.history_retention_seconds,
        "postgresql_major": neon.postgresql_major,
        "autoscaling_limit_max_cu": neon.autoscaling_limit_max_cu,
        "api_get_count": neon.api_get_count,
        "api_post_count": 0,
        "api_put_count": 0,
        "api_patch_count": 0,
        "api_delete_count": 0,
    }


def _report(
    *,
    checks: GateChecks,
    decision: GateDecision,
    neon: NeonObservation,
    database: DatabaseObservation,
    queue_count: int,
    in_progress_count: int,
    dispatch_count: int,
    dsn_security_profile: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": REPORT_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {
            "repository": EXPECTED_REPOSITORY,
            "ref": EXPECTED_REF,
            "main_sha": os.environ["GITHUB_SHA"],
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        },
        "verdict": decision.verdict,
        "reason": decision.reason,
        "failed_gate": failed_gate(checks),
        "effect_counter_certainty": "OBSERVED",
        "dsn_contract_verdict": ("NEON_BOOTSTRAP_DSN_MATCHES_CURRENT_SECURE_CONTRACT"),
        "dsn_security_profile": dict(dsn_security_profile),
        "checks": asdict(checks),
        "neon": _sanitized_neon(neon),
        "postgresql": {
            "database_name_sha256": _fingerprint(database.database_name),
            "postgresql_version": str(database.postgresql_version_num),
            "postgresql_version_num": database.postgresql_version_num,
            "database_target_verified": True,
            "principal_target_verified": True,
            "current_revision": database.revision,
            "revision_count": database.revision_count,
            "ssl_verified": database.ssl,
            "default_transaction_read_only": database.default_transaction_read_only,
            "transaction_read_only": database.transaction_read_only,
            "statement_timeout_ms": database.statement_timeout_ms,
            "lock_timeout_ms": database.lock_timeout_ms,
            "lifecycle_admin_sha256": _fingerprint(database.current_user),
            "bootstrap_authority_plausible": _bootstrap_authority_plausible(database),
            "bootstrap_targets_valid": database.bootstrap_targets_valid,
            "bootstrap_grantable_capabilities": list(database.bootstrap_grantable_capabilities),
            "chronos_inventory_classification": (
                "ABSENT"
                if not database.chronos_roles
                and not database.chronos_memberships
                and not database.chronos_objects
                else "UNSAFE_EXISTING_STATE"
            ),
            "existing_chronos_roles": _sanitize_rows(
                database.chronos_roles,
                identity_keys=frozenset({"rolname"}),
            ),
            "existing_chronos_memberships": _sanitize_rows(
                database.chronos_memberships,
                identity_keys=frozenset({"granted_role", "member_role", "grantor_role"}),
            ),
            "existing_chronos_objects": _sanitize_rows(
                database.chronos_objects,
                identity_keys=frozenset({"schema_name", "object_name", "owner_role"}),
            ),
            "sql_statement_count": database.sql_statement_count,
            "sql_statement_completed_count": database.sql_statement_completed_count,
            "sql_read_attempt_count": database.sql_read_attempt_count,
            "sql_read_count": database.sql_read_count,
            "sql_write_count": 0,
            "begin_read_only_attempted": 1,
            "begin_read_only_completed": 1,
            "rollback_attempted": 1,
            "rollback_completed": 1,
        },
        "github_actions": {
            "queued": queue_count,
            "in_progress": in_progress_count,
            "current_run_excluded": int(os.environ["GITHUB_RUN_ID"]),
            "exact_main_dispatch_count": dispatch_count,
        },
        "effects": {
            "neon_get_count": neon.api_get_count,
            "neon_mutations": 0,
            "production_sql_writes": 0,
            "recovery_branch_creations": 0,
            "role_creations": 0,
            "migration_0014": 0,
            "r2_operations": 0,
            "provider_calls": 0,
            "purchases": 0,
            "sensitive_values_exposed": 0,
            "postgresql_connection_attempts": 1,
            "postgresql_connection_successes": 1,
            "postgresql_retries": 0,
            "sql_statement_count": database.sql_statement_count,
            "sql_statement_completed_count": database.sql_statement_completed_count,
            "sql_read_attempt_count": database.sql_read_attempt_count,
            "sql_read_count": database.sql_read_count,
            "sql_write_count": 0,
            "begin_read_only_attempted": 1,
            "begin_read_only_completed": 1,
            "rollback_attempted": 1,
            "rollback_completed": 1,
        },
    }


def _no_go_report(
    reason: str,
    gate: str,
    *,
    dsn_security_profile: Mapping[str, object] | None = None,
    sanitized_evidence: Mapping[str, object] | None = None,
    sanitized_postgresql_evidence: Mapping[str, object] | None = None,
    effect_counts: Mapping[str, int] | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {
            "repository": os.getenv("GITHUB_REPOSITORY", "UNKNOWN"),
            "ref": os.getenv("GITHUB_REF", "UNKNOWN"),
            "main_sha": os.getenv("GITHUB_SHA", "UNKNOWN"),
            "run_id": os.getenv("GITHUB_RUN_ID", "UNKNOWN"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "UNKNOWN"),
        },
        "verdict": NO_GO_VERDICT,
        "reason": reason,
        "failed_gate": gate,
        "effect_counter_certainty": "OBSERVED",
        "effects": {
            "neon_get_count": 0,
            "neon_mutations": 0,
            "production_sql_writes": 0,
            "recovery_branch_creations": 0,
            "role_creations": 0,
            "migration_0014": 0,
            "r2_operations": 0,
            "provider_calls": 0,
            "purchases": 0,
            "sensitive_values_exposed": 0,
            "postgresql_connection_attempts": 0,
            "postgresql_connection_successes": 0,
            "postgresql_retries": 0,
            "sql_statement_count": 0,
            "sql_statement_completed_count": 0,
            "sql_read_attempt_count": 0,
            "sql_read_count": 0,
            "sql_write_count": 0,
            "begin_read_only_attempted": 0,
            "begin_read_only_completed": 0,
            "rollback_attempted": 0,
            "rollback_completed": 0,
        },
    }
    if dsn_security_profile is not None:
        report["dsn_security_profile"] = dict(dsn_security_profile)
        report["dsn_contract_verdict"] = dsn_security_profile.get(
            "contract_verdict",
            "NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT",
        )
    if sanitized_evidence is not None:
        report["neon"] = dict(sanitized_evidence)
        api_get_count = sanitized_evidence.get("api_get_count")
        if isinstance(api_get_count, int) and not isinstance(api_get_count, bool):
            effects = cast(dict[str, object], report["effects"])
            effects["neon_get_count"] = api_get_count
    if sanitized_postgresql_evidence is not None:
        report["postgresql"] = dict(sanitized_postgresql_evidence)
    effects = cast(dict[str, object], report["effects"])
    for key, value in (effect_counts or {}).items():
        effects[key] = value
    return report


def run_preflight() -> dict[str, object]:
    repository = _required_context("GITHUB_REPOSITORY")
    git_ref = _required_context("GITHUB_REF")
    main_sha = _required_context("GITHUB_SHA")
    run_attempt = _required_context("GITHUB_RUN_ATTEMPT")
    run_id = _positive_integer_context("GITHUB_RUN_ID")
    if repository != EXPECTED_REPOSITORY or git_ref != EXPECTED_REF:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_source_not_exact_main")
    if _HEX_SHA.fullmatch(main_sha) is None:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_main_sha_invalid")
    if run_attempt != "1":
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "workflow_rerun_forbidden")
    queue_count, in_progress_count, dispatch_count = _github_actions_state(
        repository,
        run_id,
        main_sha,
    )
    if dispatch_count != 1:
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "exact_main_dispatch_not_unique")
    if queue_count != 0 or in_progress_count != 0:
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_not_quiescent")
    api_key = _required_sensitive_context("NEON_API_KEY")
    database_url = _required_context("NEON_BOOTSTRAP_DATABASE_URL")
    _, target = _validated_psycopg_url(database_url)
    dsn_security_profile = _target_dsn_security_profile(target)
    try:
        _reject_libpq_environment()
        client = NeonReadOnlyClient(api_key)
        neon = _resolve_neon_identity(client, target)
        try:
            require_neon_recovery_feasibility(neon)
            purchase_required = False
            recovery_feasible = True
            database = _inspect_database(
                database_url,
                expected_postgresql_major=neon.postgresql_major,
            )
        except PreflightNoGo as error:
            raise PreflightNoGo(
                error.reason,
                error.gate,
                sanitized_evidence=error.sanitized_evidence or _sanitized_neon(neon),
                sanitized_postgresql_evidence=(error.sanitized_postgresql_evidence),
                effect_counts=error.effect_counts,
            ) from None
        sql_safety = (
            database.default_transaction_read_only
            and database.transaction_read_only
            and database.statement_timeout_ms == EXPECTED_STATEMENT_TIMEOUT_MS
            and database.lock_timeout_ms == EXPECTED_LOCK_TIMEOUT_MS
            and database.sql_statement_count <= MAX_SQL_STATEMENTS
        )
        checks = GateChecks(
            secrets_present=True,
            project_identity_verified=True,
            production_branch_verified=True,
            direct_endpoint_verified=sql_safety,
            ssl_verified=database.ssl,
            expected_revision_verified=(
                database.revision_count == 1 and database.revision == EXPECTED_REVISION
            ),
            bootstrap_authority_plausible=_bootstrap_authority_plausible(database),
            recovery_branch_feasible=recovery_feasible,
            purchase_required=purchase_required,
            github_queue_empty=queue_count == 0,
            github_in_progress_empty=in_progress_count == 0,
            github_dispatch_unique=dispatch_count == 1,
        )
        decision = evaluate_checks(checks)
        return _report(
            checks=checks,
            decision=decision,
            neon=neon,
            database=database,
            queue_count=queue_count,
            in_progress_count=in_progress_count,
            dispatch_count=dispatch_count,
            dsn_security_profile=dsn_security_profile,
        )
    except PreflightNoGo as error:
        raise PreflightNoGo(
            error.reason,
            error.gate,
            dsn_security_profile=dsn_security_profile,
            sanitized_evidence=error.sanitized_evidence,
            sanitized_postgresql_evidence=error.sanitized_postgresql_evidence,
            effect_counts=error.effect_counts,
        ) from None


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _conservative_technical_no_go_report(gate: str) -> dict[str, object]:
    report = _no_go_report("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    report["effect_counter_certainty"] = "CONSERVATIVE_UPPER_BOUNDS_ONLY"
    effects = cast(dict[str, object], report["effects"])
    effects.update(
        {
            "neon_get_count": MAX_NEON_GETS,
            "postgresql_connection_attempts": 1,
            "postgresql_connection_successes": 1,
            "sql_statement_count": MAX_SQL_STATEMENTS,
            "sql_statement_completed_count": MAX_SQL_STATEMENTS,
            "sql_read_attempt_count": MAX_SQL_STATEMENTS,
            "sql_read_count": MAX_SQL_STATEMENTS,
            "begin_read_only_attempted": 1,
            "begin_read_only_completed": 1,
            "rollback_attempted": 1,
            "rollback_completed": 1,
        }
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_preflight()
    except PreflightNoGo as error:
        report = _no_go_report(
            error.reason,
            error.gate,
            dsn_security_profile=error.dsn_security_profile,
            sanitized_evidence=error.sanitized_evidence,
            sanitized_postgresql_evidence=error.sanitized_postgresql_evidence,
            effect_counts=error.effect_counts,
        )
    except Exception:
        report = _conservative_technical_no_go_report("unexpected_sanitized_failure")
    try:
        _write_report(args.report, report)
    except Exception:
        report = _conservative_technical_no_go_report("report_serialization_or_write_failure")
        _write_report(args.report, report)
    print(str(report["verdict"]))


if __name__ == "__main__":
    main()
