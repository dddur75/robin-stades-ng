"""Fail-closed official schedule acquisition and five-league parsing boundary."""

from __future__ import annotations

import hashlib
import html
import http.client
import importlib
import io
import json
import re
import ssl
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

from robin.capture.live_contracts import LIVE_ALLOWED_SPORT_KEYS

SOURCE_PLAN_SCHEMA = "robin-official-schedule-source-plan-v1"
EVIDENCE_SCHEMA = "robin-owner-observed-official-schedule-v1"
RECONCILIATION_SCHEMA = "robin-official-schedule-reconciliation-v1"
MAXIMUM_SOURCE_BYTES = 16_777_216
MAXIMUM_REDIRECTS = 5
MAXIMUM_SOURCE_AGE = timedelta(minutes=30)
DEFAULT_TIMEOUT_SECONDS = 45.0
LALIGA_BOOTSTRAP_URL = "https://www.laliga.com/en-GB/laliga-easports/results"

PREMIER_LEAGUE_FULL_SEASON_HTML_V1 = "PREMIER_LEAGUE_FULL_SEASON_HTML_V1"
LALIGA_PUBLIC_MATCHES_JSON_V1 = "LALIGA_PUBLIC_MATCHES_JSON_V1"
DFB_DATACENTER_HTML_V1 = "DFB_DATACENTER_HTML_V1"
LEGA_SERIE_A_CALENDAR_PDF_V1 = "LEGA_SERIE_A_CALENDAR_PDF_V1"
LIGUE1_PROGRAMMATION_HTML_V1 = "LIGUE1_PROGRAMMATION_HTML_V1"

_ADAPTER_BY_SPORT = {
    "soccer_epl": PREMIER_LEAGUE_FULL_SEASON_HTML_V1,
    "soccer_spain_la_liga": LALIGA_PUBLIC_MATCHES_JSON_V1,
    "soccer_germany_bundesliga": DFB_DATACENTER_HTML_V1,
    "soccer_italy_serie_a": LEGA_SERIE_A_CALENDAR_PDF_V1,
    "soccer_france_ligue_one": LIGUE1_PROGRAMMATION_HTML_V1,
}
_OFFICIAL_DOMAINS_BY_ADAPTER = {
    PREMIER_LEAGUE_FULL_SEASON_HTML_V1: ("premierleague.com",),
    LALIGA_PUBLIC_MATCHES_JSON_V1: ("laliga.com",),
    DFB_DATACENTER_HTML_V1: ("dfb.de",),
    LEGA_SERIE_A_CALENDAR_PDF_V1: ("legaseriea.it",),
    LIGUE1_PROGRAMMATION_HTML_V1: ("ligue1.com",),
}
_CONTENT_TYPES_BY_ADAPTER = {
    PREMIER_LEAGUE_FULL_SEASON_HTML_V1: ("text/html", "application/xhtml+xml"),
    LALIGA_PUBLIC_MATCHES_JSON_V1: ("application/json",),
    DFB_DATACENTER_HTML_V1: ("text/html", "application/xhtml+xml"),
    LEGA_SERIE_A_CALENDAR_PDF_V1: ("application/pdf",),
    LIGUE1_PROGRAMMATION_HTML_V1: ("text/html", "application/xhtml+xml"),
}
_COMPETITION_BY_SPORT = {
    "soccer_epl": "Premier League",
    "soccer_spain_la_liga": "LALIGA EA SPORTS",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_italy_serie_a": "Serie A Enilive",
    "soccer_france_ligue_one": "Ligue 1 McDonald's",
}
_DENIED_PROVIDER_HOSTS = frozenset({"api.the-odds-api.com"})


class OfficialScheduleSourceError(RuntimeError):
    """Stable fail-closed error with an optional rejected fetch receipt."""

    def __init__(
        self,
        code: str,
        *,
        receipt: OfficialFetchReceipt | None = None,
    ) -> None:
        self.code = code
        self.receipt = receipt
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OfficialSourceSpec:
    sport_key: str
    adapter: str
    url: str

    @property
    def allowed_domains(self) -> tuple[str, ...]:
        return _OFFICIAL_DOMAINS_BY_ADAPTER[self.adapter]


@dataclass(frozen=True, slots=True)
class OfficialSourcePlan:
    season: str
    sources: tuple[OfficialSourceSpec, ...]
    canonical_sha256: str

    def source(self, sport_key: str) -> OfficialSourceSpec:
        matches = tuple(item for item in self.sources if item.sport_key == sport_key)
        if len(matches) != 1:
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_PLAN_SPORT_MISSING")
        return matches[0]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": SOURCE_PLAN_SCHEMA,
            "season": self.season,
            "sources": {
                item.sport_key: {"adapter": item.adapter, "url": item.url} for item in self.sources
            },
        }


@dataclass(frozen=True, slots=True)
class RedirectHop:
    requested_url: str
    status_code: int
    location: str

    def to_json(self) -> dict[str, object]:
        return {
            "requested_url": self.requested_url,
            "status_code": self.status_code,
            "location": self.location,
        }


@dataclass(frozen=True, slots=True)
class OfficialHttpResponse:
    status_code: int
    final_url: str
    content_type: str
    body: bytes
    redirect_chain: tuple[RedirectHop, ...] = ()
    supporting_official_reads: tuple[SupportingOfficialRead, ...] = ()
    supporting_official_raw_bytes: tuple[bytes, ...] = ()


@dataclass(frozen=True, slots=True)
class SupportingOfficialRead:
    requested_url: str
    final_url: str
    official_domain: str
    status_code: int
    content_type: str
    byte_count: int
    raw_sha256: str
    redirect_chain: tuple[RedirectHop, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "official_domain": self.official_domain,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "byte_count": self.byte_count,
            "raw_sha256": self.raw_sha256,
            "redirect_chain": [item.to_json() for item in self.redirect_chain],
        }


class OfficialScheduleFetcher(Protocol):
    def fetch(self, source: OfficialSourceSpec) -> OfficialHttpResponse: ...


@dataclass(frozen=True, slots=True)
class OfficialFetchReceipt:
    sport_key: str
    adapter_revision: str
    requested_url: str
    final_url: str
    official_domain: str
    observed_at_utc: datetime
    http_status: int
    content_type: str
    byte_count: int
    raw_sha256: str
    redirect_chain: tuple[RedirectHop, ...]
    accepted: bool
    rejection_code: str | None
    supporting_official_reads: tuple[SupportingOfficialRead, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": "robin-official-schedule-fetch-receipt-v1",
            "sport_key": self.sport_key,
            "adapter_revision": self.adapter_revision,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "official_domain": self.official_domain,
            "observed_at_utc": _utc_text(self.observed_at_utc),
            "http_status": self.http_status,
            "content_type": self.content_type,
            "byte_count": self.byte_count,
            "raw_sha256": self.raw_sha256,
            "redirect_chain": [item.to_json() for item in self.redirect_chain],
            "accepted": self.accepted,
            "rejection_code": self.rejection_code,
            "supporting_official_reads": [
                item.to_json() for item in self.supporting_official_reads
            ],
        }


@dataclass(frozen=True, slots=True)
class OfficialFetchResult:
    raw_bytes: bytes
    receipt: OfficialFetchReceipt
    supporting_official_raw_bytes: tuple[bytes, ...] = ()


@dataclass(frozen=True, slots=True)
class OfficialFixture:
    home: str
    away: str
    kickoff_utc: datetime
    official_id: str
    kickoff_confirmed: bool = True
    round_number: int | None = None


@dataclass(frozen=True, slots=True)
class OfficialScheduleEvidence:
    sport_key: str
    source_authority: str
    source_content_sha256: str
    source_observed_at_utc: datetime
    horizon_not_before_utc: datetime
    horizon_expires_at_utc: datetime
    fixtures: tuple[OfficialFixture, ...]
    adapter_revision: str
    parser_metadata: Mapping[str, object]

    def to_json(self) -> dict[str, object]:
        fixtures: list[dict[str, object]] = []
        for item in self.fixtures:
            identity = "|".join(
                (
                    self.sport_key,
                    _utc_text(item.kickoff_utc),
                    item.home,
                    item.away,
                    item.official_id,
                )
            )
            fixtures.append(
                {
                    "internal_fixture_target_id": (
                        f"official-{self.sport_key}-{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
                    ),
                    "competition": _COMPETITION_BY_SPORT[self.sport_key],
                    "official_home_team": item.home,
                    "official_away_team": item.away,
                    "official_kickoff_utc": _utc_text(item.kickoff_utc),
                }
            )
        return {
            "schema_version": EVIDENCE_SCHEMA,
            "target_set_id": f"official-horizon-{self.sport_key}-{hashlib.sha256(_canonical_bytes({'source_sha256': self.source_content_sha256, 'horizon_not_before_utc': _utc_text(self.horizon_not_before_utc), 'horizon_expires_at_utc': _utc_text(self.horizon_expires_at_utc), 'fixtures': fixtures})).hexdigest()[:24]}",
            "sport_key": self.sport_key,
            "official_source_authority": self.source_authority,
            "official_source_content_sha256": self.source_content_sha256,
            "source_observed_at_utc": _utc_text(self.source_observed_at_utc),
            "selection_horizon_not_before_utc": _utc_text(self.horizon_not_before_utc),
            "selection_horizon_expires_at_utc": _utc_text(self.horizon_expires_at_utc),
            "official_schedule_fixture_count": len(fixtures),
            "official_schedule_completeness": "OWNER_REVIEWED_COMPLETE_OFFICIAL_HORIZON",
            "adapter_revision": self.adapter_revision,
            "parser_metadata": dict(self.parser_metadata),
            "fixtures": fixtures,
        }


class _PdfPage(Protocol):
    def extract_text(self) -> str | None: ...


class _PdfReader(Protocol):
    pages: Sequence[_PdfPage]


PdfTextExtractor = Callable[[bytes], str]


def _utc(value: datetime, *, code: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfficialScheduleSourceError(code)
    return value.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return _utc(value, code="OFFICIAL_SCHEDULE_DATETIME_INVALID").isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _clean(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", value)).split())


def _host_allowed(host: str, domains: tuple[str, ...]) -> bool:
    normalized = host.rstrip(".").casefold()
    return any(normalized == item or normalized.endswith(f".{item}") for item in domains)


def _validate_official_url(url: str, source: OfficialSourceSpec) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").rstrip(".").casefold()
    try:
        port = parsed.port
    except ValueError:
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_URL_INVALID") from None
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_URL_INVALID")
    if host in _DENIED_PROVIDER_HOSTS:
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_PROVIDER_HOST_FORBIDDEN")
    if not _host_allowed(host, source.allowed_domains):
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_HOST_FORBIDDEN")
    return host


def _extract_laliga_public_subscription(payload: bytes) -> str:
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise OfficialScheduleSourceError("LALIGA_BOOTSTRAP_AUTHORITY_INVALID") from None
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        source,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if match is None:
        raise OfficialScheduleSourceError("LALIGA_BOOTSTRAP_AUTHORITY_INVALID")
    try:
        document = json.loads(match.group(1))
    except json.JSONDecodeError:
        raise OfficialScheduleSourceError("LALIGA_BOOTSTRAP_AUTHORITY_INVALID") from None
    if not isinstance(document, dict):
        raise OfficialScheduleSourceError("LALIGA_BOOTSTRAP_AUTHORITY_INVALID")
    candidates: tuple[object, ...] = (
        document.get("runtimeConfig"),
        document.get("props"),
    )
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        runtime = candidate.get("runtimeConfig", candidate)
        if not isinstance(runtime, dict):
            continue
        subscription = runtime.get("backendSubscription")
        if isinstance(subscription, str) and subscription.strip():
            return subscription.strip()
    raise OfficialScheduleSourceError("LALIGA_BOOTSTRAP_AUTHORITY_INVALID")


def load_official_source_plan_bytes(payload: bytes) -> OfficialSourcePlan:
    if len(payload) > 1_048_576:
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_PLAN_TOO_LARGE")
    try:
        raw = json.loads(payload, object_pairs_hook=_reject_duplicate_json_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_PLAN_INVALID") from None
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "season", "sources"}:
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_PLAN_INVALID")
    season = raw.get("season")
    sources = raw.get("sources")
    if (
        raw.get("schema_version") != SOURCE_PLAN_SCHEMA
        or season != "2026-2027"
        or not isinstance(sources, dict)
        or set(sources) != set(LIVE_ALLOWED_SPORT_KEYS)
    ):
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_PLAN_INVALID")
    parsed_sources: list[OfficialSourceSpec] = []
    for sport_key in LIVE_ALLOWED_SPORT_KEYS:
        entry = sources.get(sport_key)
        if not isinstance(entry, dict) or set(entry) != {"adapter", "url"}:
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_PLAN_ENTRY_INVALID")
        adapter = entry.get("adapter")
        url = entry.get("url")
        if adapter != _ADAPTER_BY_SPORT[sport_key] or not isinstance(url, str):
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_PLAN_ADAPTER_INVALID")
        source = OfficialSourceSpec(sport_key=sport_key, adapter=adapter, url=url)
        _validate_official_url(url, source)
        if adapter == LALIGA_PUBLIC_MATCHES_JSON_V1:
            parsed_url = urlparse(url)
            query = parse_qs(parsed_url.query, keep_blank_values=True)
            if (
                (parsed_url.hostname or "").casefold() != "apim.laliga.com"
                or query.get("limit") != ["100"]
                or query.get("offset") != ["300"]
            ):
                raise OfficialScheduleSourceError("LALIGA_PAGINATION_AUTHORITY_INVALID")
        parsed_sources.append(source)
    canonical = {
        "schema_version": SOURCE_PLAN_SCHEMA,
        "season": season,
        "sources": {
            item.sport_key: {"adapter": item.adapter, "url": item.url} for item in parsed_sources
        },
    }
    return OfficialSourcePlan(
        season=season,
        sources=tuple(parsed_sources),
        canonical_sha256=hashlib.sha256(_canonical_bytes(canonical)).hexdigest(),
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("OFFICIAL_SOURCE_PLAN_DUPLICATE_KEY")
        result[key] = value
    return result


class BuiltinHttpsOfficialScheduleFetcher:
    """Direct HTTPS client: no proxy, netrc, persistent cookie, auth or ambient session."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        maximum_bytes: int = MAXIMUM_SOURCE_BYTES,
        maximum_redirects: int = MAXIMUM_REDIRECTS,
    ) -> None:
        if (
            timeout_seconds <= 0
            or maximum_bytes <= 0
            or not isinstance(maximum_redirects, int)
            or isinstance(maximum_redirects, bool)
            or not 0 <= maximum_redirects <= MAXIMUM_REDIRECTS
        ):
            raise ValueError("OFFICIAL_FETCH_LIMIT_INVALID")
        self._timeout_seconds = timeout_seconds
        self._maximum_bytes = maximum_bytes
        self._maximum_redirects = maximum_redirects

    def _request(
        self,
        source: OfficialSourceSpec,
        requested_url: str,
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> OfficialHttpResponse:
        current_url = requested_url
        redirects: list[RedirectHop] = []
        for _ in range(self._maximum_redirects + 1):
            host = _validate_official_url(current_url, source)
            parsed = urlparse(current_url)
            target = parsed.path or "/"
            if parsed.query:
                target = f"{target}?{parsed.query}"
            connection = http.client.HTTPSConnection(
                host,
                port=parsed.port or 443,
                timeout=self._timeout_seconds,
                context=ssl.create_default_context(),
            )
            try:
                headers = {
                    "Accept": ", ".join(_CONTENT_TYPES_BY_ADAPTER[source.adapter]),
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "User-Agent": "RobinOfficialScheduleBoundary/1",
                }
                headers.update(extra_headers or {})
                connection.request(
                    "GET",
                    target,
                    headers=headers,
                )
                response = connection.getresponse()
                status = response.status
                content_type = response.getheader("Content-Type", "")
                content_encoding = (response.getheader("Content-Encoding") or "").strip().casefold()
                if content_encoding not in {"", "identity"}:
                    raise OfficialScheduleSourceError("OFFICIAL_SOURCE_CONTENT_ENCODING_INVALID")
                location = response.getheader("Location")
                length_header = response.getheader("Content-Length")
                if length_header is not None:
                    try:
                        if int(length_header) > self._maximum_bytes:
                            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_RESPONSE_TOO_LARGE")
                    except ValueError:
                        raise OfficialScheduleSourceError(
                            "OFFICIAL_SOURCE_CONTENT_LENGTH_INVALID"
                        ) from None
                if status in {301, 302, 303, 307, 308}:
                    if not location:
                        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_REDIRECT_INVALID")
                    next_url = urljoin(current_url, location)
                    _validate_official_url(next_url, source)
                    redirects.append(
                        RedirectHop(
                            requested_url=current_url,
                            status_code=status,
                            location=next_url,
                        )
                    )
                    current_url = next_url
                    continue
                body = response.read(self._maximum_bytes + 1)
                if len(body) > self._maximum_bytes:
                    raise OfficialScheduleSourceError("OFFICIAL_SOURCE_RESPONSE_TOO_LARGE")
                return OfficialHttpResponse(
                    status_code=status,
                    final_url=current_url,
                    content_type=content_type,
                    body=body,
                    redirect_chain=tuple(redirects),
                )
            except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                raise OfficialScheduleSourceError("OFFICIAL_SOURCE_NETWORK_FAILED") from error
            finally:
                connection.close()
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_REDIRECT_LIMIT_EXCEEDED")

    def fetch(self, source: OfficialSourceSpec) -> OfficialHttpResponse:
        if source.adapter != LALIGA_PUBLIC_MATCHES_JSON_V1:
            return self._request(source, source.url)
        if (urlparse(source.url).hostname or "").casefold() != "apim.laliga.com":
            raise OfficialScheduleSourceError("LALIGA_PAGINATION_AUTHORITY_INVALID")
        bootstrap = self._request(source, LALIGA_BOOTSTRAP_URL)
        bootstrap_type = bootstrap.content_type.split(";", 1)[0].strip().casefold()
        if bootstrap.status_code != 200 or bootstrap_type not in {
            "text/html",
            "application/xhtml+xml",
        }:
            raise OfficialScheduleSourceError("LALIGA_BOOTSTRAP_AUTHORITY_INVALID")
        subscription = _extract_laliga_public_subscription(bootstrap.body)
        result = self._request(
            source,
            source.url,
            extra_headers={"Ocp-Apim-Subscription-Key": subscription},
        )
        if subscription.encode("utf-8") in result.body:
            raise OfficialScheduleSourceError("LALIGA_BOOTSTRAP_SECRET_LEAK")
        subscription = ""
        supporting = SupportingOfficialRead(
            requested_url=LALIGA_BOOTSTRAP_URL,
            final_url=bootstrap.final_url,
            official_domain=(urlparse(bootstrap.final_url).hostname or "").casefold(),
            status_code=bootstrap.status_code,
            content_type=bootstrap.content_type,
            byte_count=len(bootstrap.body),
            raw_sha256=hashlib.sha256(bootstrap.body).hexdigest(),
            redirect_chain=bootstrap.redirect_chain,
        )
        return OfficialHttpResponse(
            status_code=result.status_code,
            final_url=result.final_url,
            content_type=result.content_type,
            body=result.body,
            redirect_chain=result.redirect_chain,
            supporting_official_reads=(supporting,),
            supporting_official_raw_bytes=(bootstrap.body,),
        )


def _receipt(
    source: OfficialSourceSpec,
    *,
    observed_at_utc: datetime,
    response: OfficialHttpResponse | None,
    accepted: bool,
    rejection_code: str | None,
) -> OfficialFetchReceipt:
    final_url = response.final_url if response is not None else source.url
    host = (urlparse(final_url).hostname or "").casefold()
    body = response.body if response is not None else b""
    return OfficialFetchReceipt(
        sport_key=source.sport_key,
        adapter_revision=source.adapter,
        requested_url=source.url,
        final_url=final_url,
        official_domain=host,
        observed_at_utc=_utc(observed_at_utc, code="OFFICIAL_FETCH_TIME_INVALID"),
        http_status=response.status_code if response is not None else 0,
        content_type=response.content_type if response is not None else "",
        byte_count=len(body),
        raw_sha256=hashlib.sha256(body).hexdigest(),
        redirect_chain=response.redirect_chain if response is not None else (),
        accepted=accepted,
        rejection_code=rejection_code,
        supporting_official_reads=(
            response.supporting_official_reads if response is not None else ()
        ),
    )


def fetch_official_schedule_source(
    source: OfficialSourceSpec,
    *,
    fetcher: OfficialScheduleFetcher,
    observed_at_utc: datetime | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> OfficialFetchResult:
    response: OfficialHttpResponse | None = None
    try:
        if _ADAPTER_BY_SPORT.get(source.sport_key) != source.adapter:
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_SPORT_ADAPTER_MISMATCH")
        _validate_official_url(source.url, source)
        response = fetcher.fetch(source)
        _validate_official_url(response.final_url, source)
        if len(response.redirect_chain) > MAXIMUM_REDIRECTS:
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_REDIRECT_LIMIT_EXCEEDED")
        expected_url = source.url
        for hop in response.redirect_chain:
            if hop.requested_url != expected_url or hop.status_code not in {
                301,
                302,
                303,
                307,
                308,
            }:
                raise OfficialScheduleSourceError("OFFICIAL_SOURCE_REDIRECT_CHAIN_INVALID")
            _validate_official_url(hop.requested_url, source)
            _validate_official_url(hop.location, source)
            expected_url = hop.location
        if response.final_url != expected_url:
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_REDIRECT_CHAIN_INVALID")
        if len(response.supporting_official_reads) != len(
            response.supporting_official_raw_bytes
        ) or any(
            item.status_code != 200
            or item.byte_count != len(raw)
            or item.raw_sha256 != hashlib.sha256(raw).hexdigest()
            or not _host_allowed(item.official_domain, source.allowed_domains)
            or not _redirect_chain_valid(
                item.requested_url,
                item.final_url,
                item.redirect_chain,
                source,
            )
            for item, raw in zip(
                response.supporting_official_reads,
                response.supporting_official_raw_bytes,
                strict=True,
            )
        ):
            raise OfficialScheduleSourceError("OFFICIAL_SUPPORTING_READ_INVALID")
        if response.status_code != 200:
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_HTTP_STATUS_INVALID")
        normalized_type = response.content_type.split(";", 1)[0].strip().casefold()
        if normalized_type not in _CONTENT_TYPES_BY_ADAPTER[source.adapter]:
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_CONTENT_TYPE_INVALID")
        if not response.body:
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_RESPONSE_EMPTY")
        if len(response.body) > MAXIMUM_SOURCE_BYTES:
            raise OfficialScheduleSourceError("OFFICIAL_SOURCE_RESPONSE_TOO_LARGE")
    except OfficialScheduleSourceError as error:
        observed = clock() if observed_at_utc is None else observed_at_utc
        rejected = _receipt(
            source,
            observed_at_utc=observed,
            response=response,
            accepted=False,
            rejection_code=error.code,
        )
        raise OfficialScheduleSourceError(error.code, receipt=rejected) from None
    observed = clock() if observed_at_utc is None else observed_at_utc
    accepted = _receipt(
        source,
        observed_at_utc=observed,
        response=response,
        accepted=True,
        rejection_code=None,
    )
    if response is None:
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_RESPONSE_MISSING")
    return OfficialFetchResult(
        raw_bytes=response.body,
        receipt=accepted,
        supporting_official_raw_bytes=response.supporting_official_raw_bytes,
    )


def _redirect_chain_valid(
    requested_url: str,
    final_url: str,
    chain: tuple[RedirectHop, ...],
    source: OfficialSourceSpec,
) -> bool:
    expected = requested_url
    try:
        _validate_official_url(expected, source)
        for hop in chain:
            if hop.requested_url != expected or hop.status_code not in {
                301,
                302,
                303,
                307,
                308,
            }:
                return False
            _validate_official_url(hop.location, source)
            expected = hop.location
        _validate_official_url(final_url, source)
    except OfficialScheduleSourceError:
        return False
    return expected == final_url


def _parse_iso_aware(value: str, *, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise OfficialScheduleSourceError(code) from None
    return _utc(parsed, code=code)


def _parse_epl(
    payload: bytes,
    *,
    horizon_starts: datetime,
    horizon_expires: datetime,
) -> tuple[tuple[OfficialFixture, ...], Mapping[str, object]]:
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise OfficialScheduleSourceError("EPL_SOURCE_ENCODING_INVALID") from None
    if "all 380 matches are below" not in source or "15:00 UK time" not in source:
        raise OfficialScheduleSourceError("EPL_FULL_SEASON_AUTHORITY_INVALID")
    months = {
        name: index
        for index, name in enumerate(
            (
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ),
            start=1,
        )
    }
    date_pattern = re.compile(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(\d{1,2})\s+(" + "|".join(months) + r")(?:\s+(\d{4}))?$"
    )
    fixture_pattern = re.compile(
        r"^(?:(\d{1,2}:\d{2})(?:\s+(?:GMT|BST))?\s+)?(.+?)\s+v\s+(.+?)"
        r"(?:\s+\([^)]*\))?\**$"
    )
    london = ZoneInfo("Europe/London")
    current_date: datetime | None = None
    current_year = 2026
    fixtures: list[OfficialFixture] = []
    unconfirmed_kickoffs = 0
    paragraphs = re.findall(r"<p(?:\s[^>]*)?>(.*?)</p>", source, flags=re.DOTALL | re.IGNORECASE)
    for paragraph in paragraphs:
        paragraph = re.sub(
            r"<em(?:\s[^>]*)?>.*?</em>",
            "",
            paragraph,
            flags=re.DOTALL | re.IGNORECASE,
        )
        paragraph = re.sub(r"<br\s*/?>", "\n", paragraph, flags=re.IGNORECASE)
        for raw_line in paragraph.splitlines():
            line = _clean(raw_line)
            if not line:
                continue
            date_match = date_pattern.fullmatch(line)
            if date_match:
                weekday, day, month, explicit_year = date_match.groups()
                current_year = int(explicit_year or current_year)
                current_date = datetime(
                    current_year,
                    months[month],
                    int(day),
                    tzinfo=london,
                )
                if current_date.strftime("%A") != weekday:
                    raise OfficialScheduleSourceError("EPL_WEEKDAY_MISMATCH")
                continue
            if re.match(
                r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
                line,
            ):
                current_date = None
                raise OfficialScheduleSourceError("EPL_DATE_HEADING_INVALID")
            if current_date is None or " v " not in line:
                continue
            fixture_match = fixture_pattern.fullmatch(line)
            if fixture_match is None:
                raise OfficialScheduleSourceError("EPL_FIXTURE_ROW_INVALID")
            display_time, home, away = fixture_match.groups()
            kickoff_confirmed = display_time is not None
            if not kickoff_confirmed:
                day_start = current_date.astimezone(UTC)
                day_end = (current_date + timedelta(days=1)).astimezone(UTC)
                if day_start < horizon_expires and day_end > horizon_starts:
                    raise OfficialScheduleSourceError("EPL_HORIZON_KICKOFF_UNCONFIRMED")
                unconfirmed_kickoffs += 1
            hour, minute = (int(value) for value in (display_time or "15:00").split(":"))
            kickoff = current_date.replace(hour=hour, minute=minute).astimezone(UTC)
            fixtures.append(
                OfficialFixture(
                    home=_clean(home),
                    away=_clean(away),
                    kickoff_utc=kickoff,
                    official_id=f"epl-{len(fixtures) + 1:03d}",
                    kickoff_confirmed=kickoff_confirmed,
                )
            )
    aliases = {"Newcastle": "Newcastle United"}

    def audit_name(value: str) -> str:
        return aliases.get(value, value)

    clubs = {audit_name(item.home) for item in fixtures} | {
        audit_name(item.away) for item in fixtures
    }
    pairs = Counter((audit_name(item.home), audit_name(item.away)) for item in fixtures)
    expected_pairs = {(home, away) for home in clubs for away in clubs if home != away}
    kickoff_counts = Counter(item.kickoff_utc for item in fixtures)
    team_kickoff_counts = Counter(
        (team, item.kickoff_utc)
        for item in fixtures
        for team in (audit_name(item.home), audit_name(item.away))
    )
    if (
        len(fixtures) != 380
        or len({(item.home, item.away, item.kickoff_utc) for item in fixtures}) != 380
        or len(clubs) != 20
        or set(pairs) != expected_pairs
        or any(count != 1 for count in pairs.values())
        or any(item.home == item.away for item in fixtures)
        or any(count > 10 for count in kickoff_counts.values())
        or any(count != 1 for count in team_kickoff_counts.values())
    ):
        raise OfficialScheduleSourceError("EPL_FULL_SEASON_COMPLETENESS_INVALID")
    return tuple(fixtures), {
        "full_source_fixture_count": 380,
        "club_count": 20,
        "directed_pair_count": 380,
        "unconfirmed_kickoff_count_outside_horizon": unconfirmed_kickoffs,
        "timezone": "Europe/London",
    }


def _team_name(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    if isinstance(value, dict):
        for key in ("nickname", "boundname", "official_name", "name", "shortname", "short_name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return " ".join(candidate.split())
    raise OfficialScheduleSourceError("LALIGA_TEAM_NAME_MISSING")


def _parse_laliga(
    payload: bytes,
    *,
    horizon_starts: datetime,
    horizon_expires: datetime,
) -> tuple[tuple[OfficialFixture, ...], Mapping[str, object]]:
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OfficialScheduleSourceError("LALIGA_JSON_INVALID") from None
    if not isinstance(raw, dict):
        raise OfficialScheduleSourceError("LALIGA_JSON_INVALID")
    matches: object = raw.get("matches")
    data = raw.get("data")
    if not isinstance(matches, list) and isinstance(data, list):
        matches = data
    elif not isinstance(matches, list) and isinstance(data, dict):
        matches = data.get("matches")
    if not isinstance(matches, list):
        raise OfficialScheduleSourceError("LALIGA_MATCH_ENVELOPE_INVALID")
    total_candidates: list[object] = [raw.get("total")]
    for container in (raw.get("pagination"), data):
        if isinstance(container, dict):
            total_candidates.append(container.get("total"))
            pagination = container.get("pagination")
            if isinstance(pagination, dict):
                total_candidates.append(pagination.get("total"))
    totals = {
        value
        for value in total_candidates
        if isinstance(value, int) and not isinstance(value, bool)
    }
    if totals != {380}:
        raise OfficialScheduleSourceError("LALIGA_PAGINATION_AUTHORITY_INVALID")
    fixtures: list[OfficialFixture] = []
    ids: list[str] = []
    weeks: Counter[int] = Counter()
    for item in matches:
        if not isinstance(item, dict):
            raise OfficialScheduleSourceError("LALIGA_MATCH_INVALID")
        competition = item.get("competition")
        slug = competition.get("slug") if isinstance(competition, dict) else competition
        if slug != "primera-division":
            raise OfficialScheduleSourceError("LALIGA_COMPETITION_INVALID")
        date_value = item.get("date")
        if not isinstance(date_value, str):
            raise OfficialScheduleSourceError("OFFICIAL_SCHEDULE_KICKOFF_MISSING")
        kickoff = _parse_iso_aware(date_value, code="OFFICIAL_SCHEDULE_KICKOFF_TIMEZONE_INVALID")
        if (
            horizon_starts <= kickoff < horizon_expires
            and kickoff.hour == kickoff.minute == kickoff.second == 0
        ):
            raise OfficialScheduleSourceError("OFFICIAL_SCHEDULE_KICKOFF_PLACEHOLDER")
        raw_id = item.get("id", item.get("opta_id"))
        if raw_id is None or not str(raw_id).strip():
            raise OfficialScheduleSourceError("LALIGA_MATCH_ID_MISSING")
        gameweek = item.get("gameweek")
        raw_week = gameweek.get("week") if isinstance(gameweek, dict) else gameweek
        if isinstance(raw_week, str) and raw_week.isdigit():
            raw_week = int(raw_week)
        if isinstance(raw_week, bool) or not isinstance(raw_week, int) or not 1 <= raw_week <= 38:
            raise OfficialScheduleSourceError("LALIGA_GAMEWEEK_INVALID")
        official_id = str(raw_id)
        fixtures.append(
            OfficialFixture(
                home=_team_name(item.get("home_team")),
                away=_team_name(item.get("away_team")),
                kickoff_utc=kickoff,
                official_id=official_id,
                round_number=raw_week,
            )
        )
        ids.append(official_id)
        weeks[raw_week] += 1
    round_appearances = {
        week: Counter(
            team
            for item in fixtures
            if item.round_number == week
            for team in (item.home, item.away)
        )
        for week in range(1, 9)
    }
    club_appearances = Counter(team for item in fixtures for team in (item.home, item.away))
    season_starts = datetime(2026, 7, 1, tzinfo=UTC)
    season_expires = datetime(2027, 7, 1, tzinfo=UTC)
    if (
        len(fixtures) != 80
        or any(weeks[week] != 10 for week in range(1, 9))
        or len(ids) != len(set(ids))
        or len({(item.home, item.away, item.kickoff_utc) for item in fixtures}) != len(fixtures)
        or any(left.kickoff_utc < right.kickoff_utc for left, right in zip(fixtures, fixtures[1:]))
        or any(item.home == item.away for item in fixtures)
        or len(club_appearances) != 20
        or any(count != 8 for count in club_appearances.values())
        or any(
            len(appearances) != 20 or any(count != 1 for count in appearances.values())
            for appearances in round_appearances.values()
        )
        or any(not season_starts <= item.kickoff_utc < season_expires for item in fixtures)
    ):
        raise OfficialScheduleSourceError("LALIGA_PAGINATION_AUTHORITY_INVALID")
    return tuple(fixtures), {
        "response_total": 380,
        "response_fixture_count": 80,
        "request_limit": 100,
        "request_offset": 300,
        "gameweek_fixture_counts": dict(sorted(weeks.items())),
        "club_count": len(club_appearances),
        "club_appearances": dict(sorted(club_appearances.items())),
    }


def _parse_bundesliga(
    payload: bytes,
    *,
    horizon_starts: datetime,
    horizon_expires: datetime,
) -> tuple[tuple[OfficialFixture, ...], Mapping[str, object]]:
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise OfficialScheduleSourceError("BUNDESLIGA_SOURCE_ENCODING_INVALID") from None
    if "Bundesliga 2026/27" not in source or "der Spielplan" not in source:
        raise OfficialScheduleSourceError("BUNDESLIGA_SEASON_AUTHORITY_INVALID")
    matchdays = {int(value) for value in re.findall(r"(\d{1,2})\. Spieltag", source)}
    if matchdays != set(range(1, 35)):
        raise OfficialScheduleSourceError("BUNDESLIGA_MATCHDAY_TABLE_INCOMPLETE")
    sections = re.split(r"(\d{1,2})\. Spieltag", source)
    dated_counts = {
        int(sections[index]): len(
            re.findall(
                r"\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}\s+Uhr",
                sections[index + 1],
            )
        )
        for index in range(1, len(sections), 2)
    }
    if (
        any(count not in {0, 9} for count in dated_counts.values())
        or sum(count for count in dated_counts.values()) != 45
    ):
        raise OfficialScheduleSourceError("BUNDESLIGA_EXACT_DATED_TABLE_INVALID")
    berlin = ZoneInfo("Europe/Berlin")
    fixtures: list[OfficialFixture] = []
    dated_round_clubs: dict[int, frozenset[str]] = {}
    for index in range(1, len(sections), 2):
        round_number = int(sections[index])
        if dated_counts[round_number] == 0:
            continue
        round_fixtures: list[OfficialFixture] = []
        blocks = re.split(
            r'<div\s+class="c-MatchTable-row"\s*>',
            sections[index + 1],
        )[1:]
        for block in blocks:
            date_match = re.search(
                r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),\s*"
                r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})\s+Uhr",
                block,
            )
            if date_match is None:
                continue
            local = datetime.strptime(
                " ".join(date_match.groups()),
                "%d.%m.%Y %H:%M",
            ).replace(tzinfo=berlin)
            kickoff = local.astimezone(UTC)
            id_match = re.search(r'id="match_(\d+)"', block)
            home_match = re.search(
                r"c-MatchTable-team--home[^>]*>.*?<a\s+[^>]*>(.*?)</a>",
                block,
                flags=re.DOTALL,
            )
            away_match = re.search(
                r"c-MatchTable-team--away[^>]*>.*?<a\s+[^>]*>(.*?)</a>",
                block,
                flags=re.DOTALL,
            )
            if id_match is None or home_match is None or away_match is None:
                raise OfficialScheduleSourceError("BUNDESLIGA_HORIZON_PARTIAL")
            round_fixtures.append(
                OfficialFixture(
                    home=_clean(home_match.group(1)),
                    away=_clean(away_match.group(1)),
                    kickoff_utc=kickoff,
                    official_id=id_match.group(1),
                    round_number=round_number,
                )
            )
        appearances = Counter(team for item in round_fixtures for team in (item.home, item.away))
        if (
            len(round_fixtures) != 9
            or len(appearances) != 18
            or any(count != 1 for count in appearances.values())
            or any(item.home == item.away for item in round_fixtures)
        ):
            raise OfficialScheduleSourceError("BUNDESLIGA_EXACT_DATED_TABLE_INVALID")
        dated_round_clubs[round_number] = frozenset(appearances)
        fixtures.extend(round_fixtures)
    ids = tuple(item.official_id for item in fixtures)
    club_sets = set(dated_round_clubs.values())
    if (
        len(fixtures) != 45
        or len(ids) != len(set(ids))
        or len({(item.home, item.away, item.kickoff_utc) for item in fixtures}) != len(fixtures)
        or len(dated_round_clubs) != 5
        or len(club_sets) != 1
        or len(next(iter(club_sets), ())) != 18
    ):
        raise OfficialScheduleSourceError("BUNDESLIGA_EXACT_DATED_TABLE_INVALID")
    return tuple(fixtures), {
        "exact_dated_source_fixture_count": len(fixtures),
        "full_matchday_heading_count": 34,
        "exact_dated_matchdays": sorted(dated_round_clubs),
        "club_count": 18,
        "unique_official_match_ids": len(ids),
        "timezone": "Europe/Berlin",
    }


def default_pdf_text_extractor(payload: bytes) -> str:
    """Use an already-installed PDF tool lazily; importing this module stays dependency-free."""

    try:
        pdfplumber = importlib.import_module("pdfplumber")
    except ModuleNotFoundError:
        pdfplumber = None
    if pdfplumber is not None:
        open_pdf = cast(Callable[[io.BytesIO], object], getattr(pdfplumber, "open"))
        document = open_pdf(io.BytesIO(payload))
        try:
            pages = cast(Sequence[object], getattr(document, "pages"))
            texts = [cast(str | None, getattr(page, "extract_text")()) or "" for page in pages]
            return "\n".join(texts)
        finally:
            close = cast(Callable[[], object], getattr(document, "close"))
            close()
    try:
        pypdf = importlib.import_module("pypdf")
    except ModuleNotFoundError:
        raise OfficialScheduleSourceError("SERIE_A_PDF_TOOL_UNAVAILABLE") from None
    reader_class = cast(Callable[[io.BytesIO], _PdfReader], getattr(pypdf, "PdfReader"))
    reader = reader_class(io.BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_serie_a(
    payload: bytes,
    *,
    horizon_starts: datetime,
    horizon_expires: datetime,
    pdf_text_extractor: PdfTextExtractor,
) -> tuple[tuple[OfficialFixture, ...], Mapping[str, object]]:
    try:
        source = pdf_text_extractor(payload)
    except OfficialScheduleSourceError:
        raise
    except Exception as error:
        raise OfficialScheduleSourceError("SERIE_A_PDF_PARSE_FAILED") from error
    if (
        not all(
            marker in source for marker in ("SERIE A ENILIVE 2026/2027", "n. 208", "24 giugno 2026")
        )
        or source.count("GIORNATA") < 5
    ):
        raise OfficialScheduleSourceError("SERIE_A_PDF_AUTHORITY_INVALID")
    rome = ZoneInfo("Europe/Rome")
    fixtures: list[OfficialFixture] = []
    raw_rows = 0
    ambiguous_rows = 0
    row = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+\S+\s+(\d{2}\.\d{2})\s+(.+?)\s+DAZN(?:/SKY)?$")
    for raw_line in source.splitlines():
        line = " ".join(raw_line.split())
        match = row.fullmatch(line)
        if match is None:
            continue
        raw_rows += 1
        date_value, time_value, game = match.groups()
        local = datetime.strptime(f"{date_value} {time_value}", "%d/%m/%Y %H.%M").replace(
            tzinfo=rome
        )
        kickoff = local.astimezone(UTC)
        if "/" in game or game.count("-") != 1:
            ambiguous_rows += 1
            if horizon_starts <= kickoff < horizon_expires:
                raise OfficialScheduleSourceError("SERIE_A_AMBIGUOUS_TABLE")
            continue
        home, away = (value.strip().rstrip("*") for value in game.split("-", 1))
        fixtures.append(
            OfficialFixture(
                home=home,
                away=away,
                kickoff_utc=kickoff,
                official_id=f"serie-a-{len(fixtures) + 1:03d}",
            )
        )
    unique = {(item.home, item.away, item.kickoff_utc) for item in fixtures}
    opening_cutoff = datetime(2026, 9, 1, tzinfo=rome).astimezone(UTC)
    opening = tuple(item for item in fixtures if item.kickoff_utc < opening_cutoff)
    clubs = {team for item in opening for team in (item.home, item.away)}
    appearances = Counter(team for item in opening for team in (item.home, item.away))
    if (
        raw_rows != 50
        or len(fixtures) + ambiguous_rows != raw_rows
        or len(unique) != len(fixtures)
        or len(opening) != 20
        or len(clubs) != 20
        or any(count != 2 for count in appearances.values())
    ):
        raise OfficialScheduleSourceError("SERIE_A_TABLE_COMPLETENESS_INVALID")
    return tuple(fixtures), {
        "communicated_source_fixture_rows": raw_rows,
        "parsed_unambiguous_source_fixture_count": len(fixtures),
        "ambiguous_outside_horizon_fixture_rows": ambiguous_rows,
        "opening_two_matchdays_fixture_count": 20,
        "opening_two_matchdays_club_count": 20,
        "communicated_matchdays": 5,
        "timezone": "Europe/Rome",
    }


def _visible_lines(payload: bytes) -> list[str]:
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise OfficialScheduleSourceError("LIGUE1_SOURCE_ENCODING_INVALID") from None
    source = re.sub(
        r"</?(?:p|h[1-6]|li|article|section|div|br)(?:\s[^>]*)?/?>",
        "\n",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(r"<script\b.*?</script>", "", source, flags=re.DOTALL | re.IGNORECASE)
    source = re.sub(r"<style\b.*?</style>", "", source, flags=re.DOTALL | re.IGNORECASE)
    source = re.sub(r"<[^>]+>", "", source)
    return [" ".join(html.unescape(line).split()) for line in source.splitlines() if line.strip()]


def _parse_ligue1(
    payload: bytes,
) -> tuple[tuple[OfficialFixture, ...], Mapping[str, object]]:
    lines = _visible_lines(payload)
    joined = "\n".join(lines)
    if not (
        "2026/27" in joined
        and "Ligue 1 McDonald" in joined
        and re.search(r"\b2(?:e|ème)\s+journée\b", joined, flags=re.IGNORECASE)
    ):
        raise OfficialScheduleSourceError("LIGUE1_FORWARD_HORIZON_AUTHORITY_INVALID")
    months = {"août": 8, "aout": 8, "august": 8, "septembre": 9, "september": 9}
    weekdays = {
        "lundi": 0,
        "monday": 0,
        "mardi": 1,
        "tuesday": 1,
        "mercredi": 2,
        "wednesday": 2,
        "jeudi": 3,
        "thursday": 3,
        "vendredi": 4,
        "friday": 4,
        "samedi": 5,
        "saturday": 5,
        "dimanche": 6,
        "sunday": 6,
    }
    heading = re.compile(
        r"^(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche|Monday|Tuesday|"
        r"Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)"
        r"(?:\s+(2026))?\s+(?:à|at)\s+(\d{1,2})(?:h|:)(\d{2})(?:\s+sur\b.*)?$",
        flags=re.IGNORECASE,
    )
    paris = ZoneInfo("Europe/Paris")
    current_kickoff: datetime | None = None
    fixtures: list[OfficialFixture] = []
    for line in lines:
        match = heading.fullmatch(line)
        if match is not None:
            weekday, day, month_name, explicit_year, hour, minute = match.groups()
            month = months.get(month_name.casefold())
            if month is None:
                current_kickoff = None
                continue
            local = datetime(
                int(explicit_year or "2026"),
                month,
                int(day),
                int(hour),
                int(minute),
                tzinfo=paris,
            )
            if local.weekday() != weekdays[weekday.casefold()]:
                raise OfficialScheduleSourceError("LIGUE1_WEEKDAY_MISMATCH")
            current_kickoff = local.astimezone(UTC)
            continue
        if current_kickoff is None or "–" not in line or line.count("–") != 1:
            continue
        home, away = (value.strip() for value in line.split("–", 1))
        if not home or not away or len(home) > 80 or len(away) > 80:
            continue
        fixtures.append(
            OfficialFixture(
                home=home,
                away=away,
                kickoff_utc=current_kickoff,
                official_id=f"ligue1-j2-{len(fixtures) + 1:02d}",
            )
        )
    unique = {(item.home, item.away, item.kickoff_utc) for item in fixtures}
    clubs = {team for item in fixtures for team in (item.home, item.away)}
    days = Counter(item.kickoff_utc.astimezone(paris).date().isoformat() for item in fixtures)
    if (
        len(fixtures) != 9
        or len(unique) != 9
        or len(clubs) != 18
        or days != Counter({"2026-08-28": 1, "2026-08-29": 5, "2026-08-30": 3})
    ):
        raise OfficialScheduleSourceError("LIGUE1_FORWARD_HORIZON_INCOMPLETE")
    return tuple(sorted(fixtures, key=lambda item: (item.kickoff_utc, item.home, item.away))), {
        "matchday": 2,
        "forward_horizon_fixture_count": 9,
        "fixture_counts_by_local_date": dict(sorted(days.items())),
        "completeness_rule": "ALL_FIXTURES_IN_FORWARD_HORIZON_NOT_ALL_ROUNDS_IN_ARTICLE_TITLE",
        "timezone": "Europe/Paris",
    }


def build_official_schedule_evidence(
    source: OfficialSourceSpec,
    fetch_result: OfficialFetchResult,
    *,
    horizon_not_before_utc: datetime,
    horizon_expires_at_utc: datetime,
    pdf_text_extractor: PdfTextExtractor | None = None,
) -> OfficialScheduleEvidence:
    horizon_starts = _utc(
        horizon_not_before_utc,
        code="OFFICIAL_SCHEDULE_HORIZON_INVALID",
    )
    horizon_expires = _utc(
        horizon_expires_at_utc,
        code="OFFICIAL_SCHEDULE_HORIZON_INVALID",
    )
    if horizon_starts >= horizon_expires:
        raise OfficialScheduleSourceError("OFFICIAL_SCHEDULE_HORIZON_INVALID")
    normalized_type = fetch_result.receipt.content_type.split(";", 1)[0].strip().casefold()
    try:
        final_host = _validate_official_url(fetch_result.receipt.final_url, source)
    except OfficialScheduleSourceError:
        raise OfficialScheduleSourceError("OFFICIAL_FETCH_RECEIPT_INVALID") from None
    if (
        _ADAPTER_BY_SPORT.get(source.sport_key) != source.adapter
        or not fetch_result.receipt.accepted
        or fetch_result.receipt.sport_key != source.sport_key
        or fetch_result.receipt.adapter_revision != source.adapter
        or fetch_result.receipt.requested_url != source.url
        or fetch_result.receipt.official_domain != final_host
        or fetch_result.receipt.http_status != 200
        or normalized_type not in _CONTENT_TYPES_BY_ADAPTER[source.adapter]
        or fetch_result.receipt.byte_count != len(fetch_result.raw_bytes)
        or fetch_result.receipt.rejection_code is not None
        or fetch_result.receipt.raw_sha256 != hashlib.sha256(fetch_result.raw_bytes).hexdigest()
        or len(fetch_result.receipt.supporting_official_reads)
        != len(fetch_result.supporting_official_raw_bytes)
        or not _redirect_chain_valid(
            fetch_result.receipt.requested_url,
            fetch_result.receipt.final_url,
            fetch_result.receipt.redirect_chain,
            source,
        )
        or any(
            item.status_code != 200
            or item.byte_count <= 0
            or item.byte_count != len(raw)
            or item.raw_sha256 != item.raw_sha256.casefold()
            or len(item.raw_sha256) != 64
            or item.raw_sha256 != hashlib.sha256(raw).hexdigest()
            or not _host_allowed(item.official_domain, source.allowed_domains)
            or not _redirect_chain_valid(
                item.requested_url,
                item.final_url,
                item.redirect_chain,
                source,
            )
            for item, raw in zip(
                fetch_result.receipt.supporting_official_reads,
                fetch_result.supporting_official_raw_bytes,
                strict=True,
            )
        )
    ):
        raise OfficialScheduleSourceError("OFFICIAL_FETCH_RECEIPT_INVALID")
    if source.adapter == PREMIER_LEAGUE_FULL_SEASON_HTML_V1:
        fixtures, metadata = _parse_epl(
            fetch_result.raw_bytes,
            horizon_starts=horizon_starts,
            horizon_expires=horizon_expires,
        )
    elif source.adapter == LALIGA_PUBLIC_MATCHES_JSON_V1:
        fixtures, metadata = _parse_laliga(
            fetch_result.raw_bytes,
            horizon_starts=horizon_starts,
            horizon_expires=horizon_expires,
        )
    elif source.adapter == DFB_DATACENTER_HTML_V1:
        fixtures, metadata = _parse_bundesliga(
            fetch_result.raw_bytes,
            horizon_starts=horizon_starts,
            horizon_expires=horizon_expires,
        )
    elif source.adapter == LEGA_SERIE_A_CALENDAR_PDF_V1:
        fixtures, metadata = _parse_serie_a(
            fetch_result.raw_bytes,
            horizon_starts=horizon_starts,
            horizon_expires=horizon_expires,
            pdf_text_extractor=pdf_text_extractor or default_pdf_text_extractor,
        )
    elif source.adapter == LIGUE1_PROGRAMMATION_HTML_V1:
        fixtures, metadata = _parse_ligue1(fetch_result.raw_bytes)
    else:
        raise OfficialScheduleSourceError("OFFICIAL_SOURCE_ADAPTER_INVALID")
    selected = tuple(
        sorted(
            (item for item in fixtures if horizon_starts <= item.kickoff_utc < horizon_expires),
            key=lambda item: (item.kickoff_utc, item.home, item.away, item.official_id),
        )
    )
    if not selected:
        raise OfficialScheduleSourceError("OFFICIAL_SCHEDULE_HORIZON_EMPTY")
    if any(not item.kickoff_confirmed for item in selected):
        raise OfficialScheduleSourceError("OFFICIAL_SCHEDULE_HORIZON_KICKOFF_UNCONFIRMED")
    identities = tuple((item.home, item.away, item.kickoff_utc) for item in selected)
    ids = tuple(item.official_id for item in selected)
    if (
        len(identities) != len(set(identities))
        or len(ids) != len(set(ids))
        or any(item.home == item.away for item in selected)
        or any(item.kickoff_utc.tzinfo is None for item in selected)
    ):
        raise OfficialScheduleSourceError("OFFICIAL_SCHEDULE_FIXTURE_INVALID")
    return OfficialScheduleEvidence(
        sport_key=source.sport_key,
        source_authority=fetch_result.receipt.final_url,
        source_content_sha256=fetch_result.receipt.raw_sha256,
        source_observed_at_utc=fetch_result.receipt.observed_at_utc,
        horizon_not_before_utc=horizon_starts,
        horizon_expires_at_utc=horizon_expires,
        fixtures=selected,
        adapter_revision=source.adapter,
        parser_metadata=metadata,
    )


def reconcile_official_schedule_evidence(
    evidences: Sequence[OfficialScheduleEvidence],
    *,
    observed_at_utc: datetime,
) -> dict[str, object]:
    observed = _utc(observed_at_utc, code="OFFICIAL_RECONCILIATION_TIME_INVALID")
    if tuple(item.sport_key for item in evidences) != LIVE_ALLOWED_SPORT_KEYS:
        raise OfficialScheduleSourceError("OFFICIAL_RECONCILIATION_FIVE_LEAGUE_INVALID")
    if any(
        item.source_observed_at_utc > observed
        or observed - item.source_observed_at_utc > MAXIMUM_SOURCE_AGE
        or not item.fixtures
        or item.adapter_revision != _ADAPTER_BY_SPORT[item.sport_key]
        for item in evidences
    ):
        raise OfficialScheduleSourceError("OFFICIAL_RECONCILIATION_SOURCE_INVALID")
    horizons = {(item.horizon_not_before_utc, item.horizon_expires_at_utc) for item in evidences}
    if len(horizons) != 1:
        raise OfficialScheduleSourceError("OFFICIAL_RECONCILIATION_HORIZON_MISMATCH")
    return {
        "schema_version": RECONCILIATION_SCHEMA,
        "observed_at_utc": _utc_text(observed),
        "sport_keys": list(LIVE_ALLOWED_SPORT_KEYS),
        "fixture_counts": {item.sport_key: len(item.fixtures) for item in evidences},
        "source_sha256": {item.sport_key: item.source_content_sha256 for item in evidences},
        "adapter_revisions": {item.sport_key: item.adapter_revision for item in evidences},
        "complete_official_horizon": True,
        "provider_dns": 0,
        "provider_tcp": 0,
        "provider_http": 0,
        "secret_reads": 0,  # nosec B105 -- effect counter, not a credential
    }


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DFB_DATACENTER_HTML_V1",
    "EVIDENCE_SCHEMA",
    "LEGA_SERIE_A_CALENDAR_PDF_V1",
    "LALIGA_PUBLIC_MATCHES_JSON_V1",
    "LIGUE1_PROGRAMMATION_HTML_V1",
    "MAXIMUM_SOURCE_AGE",
    "MAXIMUM_SOURCE_BYTES",
    "PREMIER_LEAGUE_FULL_SEASON_HTML_V1",
    "BuiltinHttpsOfficialScheduleFetcher",
    "OfficialFetchReceipt",
    "OfficialFetchResult",
    "OfficialFixture",
    "OfficialHttpResponse",
    "OfficialScheduleEvidence",
    "OfficialScheduleFetcher",
    "OfficialScheduleSourceError",
    "OfficialSourcePlan",
    "OfficialSourceSpec",
    "PdfTextExtractor",
    "RedirectHop",
    "SupportingOfficialRead",
    "build_official_schedule_evidence",
    "default_pdf_text_extractor",
    "fetch_official_schedule_source",
    "load_official_source_plan_bytes",
    "reconcile_official_schedule_evidence",
]
