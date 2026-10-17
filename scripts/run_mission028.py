"""Mission 028 phase 1: immutable census, conservative matching, no retries."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

from robin.historical_deep.adapters import R2ObjectStore, assert_safety_locks
from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.contracts import ProviderStatus
from robin.historical_deep.provider import ApiFootballDeepClient
from robin.historical_deep.quota import QuotaController
from robin.historical_deep.storage import R2FirstRepository

DIGEST = "8cee89679b043fc9929a15c01bac538da2302f50fdbfc58117bc83b58092c17b"
TARGETS = Path("configs/execution/mission028-targets.csv")
PREFIX = "historical-deep-data/schema-v1/_control/mission-028"
OUTPUT = Path("artifacts/historical-deep/mission028")
LEAGUES = dict(E1=40, E2=41, E3=42, EC=43, SC0=179, SC1=180, SC2=183, SC3=184,
              D2=79, I2=136, SP2=141, F2=62, N1=88, B1=144, P1=94, T1=203, G1=197,
              ARG=128, AUT=218, BRA=71, CHN=169, DNK=119, FIN=244, IRL=357, JPN=98,
              MEX=262, NOR=103, POL=106, ROU=283, RUS=235, SWE=113, SWZ=207, USA=253)


EXTRA_CENSUSES = (("ARG", 1032, 2023), ("ARG", 1032, 2024))


def census_queries():
    # Spend the two missing calendars before reading the already archived corpus.
    return [q for q in EXTRA_CENSUSES if q[0] in LEAGUES] + [
        (code, LEAGUES[code], season) for code in sorted(LEAGUES) for season in range(2019, 2025)]


def provider_league_ids(code, season):
    return {LEAGUES[code]} | {league for c, league, year in EXTRA_CENSUSES if (c, year) == (code, season)}


def season_start(label):
    match = re.fullmatch(r"(20\d{2})(?:[-/](\d{2}|20\d{2}))?", label)
    if not match or not 2019 <= int(match[1]) <= 2024:
        raise ValueError("MISSION028_SEASON_EXCLUDED")
    if match[2] and int(match[2]) not in (int(match[1]) + 1, (int(match[1]) + 1) % 100):
        raise ValueError("MISSION028_SEASON_INVALID")
    return int(match[1])


def load_targets(path=TARGETS):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != DIGEST:
        raise ValueError("MISSION028_TARGET_HASH_MISMATCH")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    groups = {(r["ligue_fd"], season_start(r["saison_fd"])) for r in rows}
    if len(rows) != 60515 or groups != {(code, y) for code in LEAGUES for y in range(2019, 2025)}:
        raise ValueError("MISSION028_TARGET_SCOPE_INVALID")
    return rows


def name_key(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value).casefold() if c.isalnum())


def match_rows(rows, fixtures, aliases):
    provider_to_fd = {(league, season): LEAGUES[code] for code, league, season in census_queries()}
    fixture_leagues = {f["fixture"]["id"]: f["league"]["id"] for f in fixtures}
    index = defaultdict(list)
    for f in fixtures:
        if f["fixture"].get("status", {}).get("short") not in ("FT", "AET", "PEN", "AWD", "WO"):
            continue
        index[(provider_to_fd.get((f["league"]["id"], f["league"]["season"]), f["league"]["id"]), f["league"]["season"],
               f["goals"]["home"], f["goals"]["away"])].append(f)
    table, rates = [], {}
    for number, row in enumerate(rows, 1):
        code, season = row["ligue_fd"], season_start(row["saison_fd"])
        home, away = (name_key(aliases.get(f"{code}|{row[k]}", row[k]))
                      for k in ("equipe_dom_fd", "equipe_ext_fd"))
        day = date.fromisoformat(row["date"])
        candidates = {f["fixture"]["id"] for f in index[
            LEAGUES[code], season, int(row["buts_dom"]), int(row["buts_ext"])]
            if abs((date.fromisoformat(f["fixture"]["date"][:10]) - day).days) <= 1
            and name_key(aliases.get(f"{code}|{f['teams']['home']['name']}", f["teams"]["home"]["name"])) == home
            and name_key(aliases.get(f"{code}|{f['teams']['away']['name']}", f["teams"]["away"]["name"])) == away}
        table.append(dict(row, source_row=number, league_id=fixture_leagues[next(iter(candidates))] if len(candidates) == 1 else LEAGUES[code], season=season,
                          fixture_id=next(iter(candidates)) if len(candidates) == 1 else None,
                          reason="AMBIGUOUS" if len(candidates) > 1 else "UNMATCHED"))
    counts = Counter(r["fixture_id"] for r in table if r["fixture_id"] is not None)
    for row in table:
        if row["fixture_id"] is not None and counts[row["fixture_id"]] > 1:
            row.update(fixture_id=None, reason="DUPLICATE_ASSIGNMENT")
        elif row["fixture_id"] is not None:
            row["reason"] = "MATCHED"
    for code in sorted({r["ligue_fd"] for r in rows}):
        group = [r for r in table if r["ligue_fd"] == code]
        matched = sum(r["fixture_id"] is not None for r in group)
        rates[code] = dict(targets=len(group), matched=matched, fraction=matched / len(group))
    return table, rates


class Budget:
    """Reservations count conservatively, including crashes, across UTC days."""
    def __init__(self, entries):
        self.total, self.days = len(entries), Counter(e["day"] for e in entries)

    def reserve(self, now, remaining):
        day = now.astimezone(UTC).date().isoformat()
        if self.total >= 122200 or self.days[day] >= 70000 or remaining <= 5000:
            raise RuntimeError("MISSION028_BUDGET_REACHED")
        self.total += 1
        self.days[day] += 1


def collect_once(collector, store, budget, request, now, remaining):
    task = collector._make_task(**request, identity=None)
    key = f"{PREFIX}/requests/{task.task_id}.json"
    if collector.repository.receipt_for(task) is not None:
        return collector._collect(**request)
    if store.get_object(key) is not None:
        return None  # An uncertain reservation must never cause a second call.
    budget.reserve(now, remaining)
    marker = json.dumps(dict(day=now.astimezone(UTC).date().isoformat())).encode()
    if not store.put_if_absent(key, marker):
        return None
    return collector._collect(**request)


class Transport:
    calls = 0

    def __init__(self, deadline):
        self.deadline = deadline

    def get(self, url, **kwargs):
        if datetime.now(UTC) >= self.deadline:
            raise RuntimeError("MISSION028_PREFLIGHT_EXPIRED")
        self.calls += 1
        return requests.get(url, allow_redirects=False, **kwargs)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    receipt = dict(schema_version="mission-028-phase1-v1", status="PARTIAL", calls=0,
                   status_calls=0, target_sha256=DIGEST, max_calls=200, total_cap=122200,
                   daily_cap=70000, daily_reserve=5000, run_id=os.environ["GITHUB_RUN_ID"])
    transport = store = quota = None
    try:
        rows = load_targets()  # Before R2 and before any provider request.
        assert_safety_locks(os.environ)
        store = R2ObjectStore(os.environ)
        if "--progress" in sys.argv:
            progress = dict(status="OBSERVED", provider_calls_new=0,
                reserved_censuses=len(tuple(store.iter_keys(f"{PREFIX}/requests/"))),
                observed_at=datetime.now(UTC).isoformat())
            (OUTPUT / "progress.json").write_text(json.dumps(progress) + "\n")
            print(json.dumps(progress), flush=True)
            return 0
        entries = [json.loads(store.get_object(k)) for k in store.iter_keys(f"{PREFIX}/requests/")]
        budget = Budget(entries)
        replay = os.environ.get("MISSION028_REPLAY") == "true"
        now = datetime.now(UTC)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        transport = Transport(midnight)
        client = ApiFootballDeepClient(api_key=os.environ.get("API_FOOTBALL_KEY", "offline"),
                                      transport=transport, max_retries=0, status_ttl_seconds=6600)
        if not replay:
            proofs = [ProviderStatus.model_validate_json(store.get_object(k))
                      for k in store.iter_keys(f"{PREFIX}/preflight/")]
            fresh = [p for p in proofs if p.checked_at.date() == now.date()
                     and timedelta(0) <= now - p.checked_at < timedelta(minutes=110)]
            receipt["status_calls"] = int(not fresh)
            status = max(fresh, key=lambda p: p.checked_at) if fresh else client.get_status()
            receipt.update(preflight_checked_at=status.checked_at.isoformat(),
                           quota_low=status.daily_remaining)
            quota = QuotaController(status)
            client.quota = quota
            transport.deadline = min(midnight, status.checked_at + timedelta(minutes=110))
            store.put_if_absent(f"{PREFIX}/preflight/{receipt['run_id']}.json",
                                status.model_dump_json().encode())
        # R2FirstRepository is the same append-only boundary used by mission 027.
        collector = HistoricalDeepCollector(client, R2FirstRepository(store),
            source_commit=os.environ["GITHUB_SHA"])
        fixtures, missing = [], []
        low = quota.status.daily_remaining if quota else None
        for code, league_id, season in census_queries():
            request = dict(phase="mission028", competition=league_id, season=season,
                family="fixtures", endpoint="/fixtures", params=dict(league=league_id, season=season))
            task = collector._make_task(**request, identity=None)
            if replay and collector.repository.receipt_for(task) is None:
                missing.append([code, season])
                continue
            call = collect_once(collector, store, budget, request, datetime.now(UTC),
                                quota.status.daily_remaining if quota else 0)
            if call is None:
                missing.append([code, season])
                continue
            if call.paging_total != 1:
                raise RuntimeError("MISSION028_UNEXPECTED_PAGINATION")
            if any(f["league"]["id"] != league_id or f["league"]["season"] != season
                   for f in call.records):
                raise ValueError("MISSION028_PROVIDER_SCOPE_INVALID")
            fixtures.extend(call.records)
            low = min(low, quota.status.daily_remaining) if quota else None
            receipt["quota_low"] = low
            print(f"Mission 028: {code} {season}; calls={transport.calls}", flush=True)
        aliases_path = Path("configs/execution/mission028-aliases.json")
        aliases = json.loads(aliases_path.read_text()) if aliases_path.exists() else {}
        table, rates = match_rows(rows, fixtures, aliases)
        fixture_index = [dict(fixture_id=f["fixture"]["id"], league_id=f["league"]["id"],
            season=f["league"]["season"], date=f["fixture"]["date"][:10], status=f["fixture"].get("status", {}).get("short"),
            home=f["teams"]["home"]["name"], away=f["teams"]["away"]["name"],
            home_goals=f["goals"]["home"], away_goals=f["goals"]["away"]) for f in fixtures]
        for filename, values in (("correspondance.csv", table), ("fixtures-index.csv", fixture_index),
                                  ("ecarts.csv", [r for r in table if r["fixture_id"] is None])):
            with (OUTPUT / filename).open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=(values or table)[0].keys())
                writer.writeheader()
                writer.writerows(values)
        ids = sorted(r["fixture_id"] for r in table if r["fixture_id"] is not None)
        receipt.update(rates=rates, missing_censuses=missing, matched=len(ids),
            fixture_ids_sha256=hashlib.sha256("".join(f"{i}\n" for i in ids).encode()).hexdigest(),
            quota_low=low, reservations_total=budget.total,
            status="COMPLETE" if not missing and all(r["fraction"] >= .97 for r in rates.values()) else "PARTIAL")
        for path in OUTPUT.glob("*.csv"):
            body = path.read_bytes()
            key = f"{PREFIX}/runs/{receipt['run_id']}/{path.name}"
            store.put_if_absent(key, body)
            receipt[path.name] = dict(sha256=hashlib.sha256(body).hexdigest(), r2_key=key)
    except Exception as error:
        receipt["reason_class"] = type(error).__name__
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", str(error)):
            receipt["reason_code"] = str(error)
    receipt["calls"] = transport.calls - receipt["status_calls"] if transport else 0
    receipt["distinct_censuses_called"] = receipt["calls"]
    receipt["quota_remaining"] = quota.status.daily_remaining if quota else None
    body = (json.dumps(receipt, indent=2) + "\n").encode()
    (OUTPUT / "public-receipt.json").write_bytes(body)
    if store:
        store.put_if_absent(f"{PREFIX}/runs/{receipt['run_id']}/public-receipt.json", body)
    return 0 if receipt["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
