"""Pure strict query-metadata protocol; no IO or authority."""
import json
import re
from typing import Any

TOP = {'schemaVersion', 'status', 'projectionComplete', 'omissions', 'candidates', 'prefixes', 'sourceReady', 'sourceChoices', 'sourceAPICalls', 'executedJavaScript'}
CAND = {'method', 'methodEvidence', 'sourceOffset', 'pathSegments', 'literalQueryKeysObserved', 'queryValuesElided', 'runtimeQueryContractEstablished', 'bindingEstablished', 'contractEstablished'}
PREFIX = {'path', 'sourceOffset', 'queryValuesElided', 'contractEstablished'}

def integer(x: object) -> bool:
    return type(x) is int and 0 <= x <= 2000000

def path(x: object) -> bool:
    return type(x) is str and 0 < len(x) <= 200 and x.startswith('/') and (not x.startswith('//')) and (re.search('[?#@%\\\\\\x00-\\x20]', x) is None)

def classify(raw: object) -> dict[str, Any]:
    result: dict[str, Any] = dict(status='UNPROVEN', reason='OUTPUT_CONTRACT', projection=None, sourceReady=False)
    if type(raw) is not bytes or len(raw) > 32768:
        return dict(result, reason='STDOUT_CAP')

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise ValueError('DUPLICATE')
            out[k] = v
        return out
    try:
        v = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('FINITE')))
    except (ValueError, UnicodeError, RecursionError):
        return dict(result, reason='INVALID_JSON')
    if type(v) is not dict or set(v) != TOP or v['schemaVersion'] != 'coteur-static-query-shapes-v1' or (v['sourceReady'] is not False) or (v['executedJavaScript'] is not False):
        return result
    if any((type(v[k]) is not int or v[k] != 0 for k in ['sourceChoices', 'sourceAPICalls'])):
        return result
    o = v['omissions']
    if type(o) is not dict or set(o) != {'candidates', 'prefixes', 'pieces', 'query'} or (not all((integer(x) for x in o.values()))):
        return result
    complete = all((x == 0 for x in o.values()))
    expected = 'STATIC_AST_CANDIDATES_ONLY' if complete else 'STATIC_AST_PARTIAL'
    if type(v['projectionComplete']) is not bool or v['projectionComplete'] != complete or v['status'] != expected:
        return result
    if type(v['candidates']) is not list or len(v['candidates']) > 8 or type(v['prefixes']) is not list or (len(v['prefixes']) > 32):
        return result
    clean = []
    for c in v['candidates']:
        if type(c) is not dict or set(c) != CAND or c['method'] != 'GET' or (type(c['methodEvidence']) is not str or c['methodEvidence'] not in {'explicit_fetch_option', 'unresolved_get_wrapper', 'unresolved_open_wrapper'}) or (not integer(c['sourceOffset'])):
            return result
        if c['queryValuesElided'] is not True or any((c[k] is not False for k in ['runtimeQueryContractEstablished', 'bindingEstablished', 'contractEstablished'])):
            return result
        parts = c['pathSegments']
        keys = c['literalQueryKeysObserved']
        if type(parts) is not list or not 1 <= len(parts) <= 16 or type(keys) is not list or (len(keys) > 12):
            return result
        copied: list[dict[str, Any]] = []
        for s in parts:
            if type(s) is not dict:
                return result
            if set(s) == {'literal'} and type(s['literal']) is str and (0 < len(s['literal']) <= 200) and (re.search('[?#@%\\\\\\x00-\\x20]', s['literal']) is None):
                copied.append({'literal': s['literal']})
            elif set(s) == {'pathdynamic'} and s['pathdynamic'] is True:
                copied.append({'pathdynamic': True})
            else:
                return result
        if 'literal' not in copied[0] or not path(''.join((s.get('literal', '') for s in copied))):
            return result
        if any((type(k) is not str or re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,39}', k) is None or re.search('auth|token|key|password|secret|session|sid', k, re.I) for k in keys)) or len(set(keys)) != len(keys):
            return result
        clean.append(dict(method='GET', methodEvidence=c['methodEvidence'], sourceOffset=c['sourceOffset'], pathSegments=copied, literalQueryKeysObserved=list(keys), queryValuesElided=True, runtimeQueryContractEstablished=False, bindingEstablished=False, contractEstablished=False))
    prefixes = []
    for p in v['prefixes']:
        if type(p) is not dict or set(p) != PREFIX or (not path(p['path'])) or (not integer(p['sourceOffset'])) or (p['queryValuesElided'] is not True) or (p['contractEstablished'] is not False):
            return result
        prefixes.append(dict(path=p['path'], sourceOffset=p['sourceOffset'], queryValuesElided=True, contractEstablished=False))
    safe = dict(schemaVersion=v['schemaVersion'], status=expected, projectionComplete=complete, omissions=dict(o), candidates=clean, prefixes=prefixes, sourceReady=False, sourceChoices=0, sourceAPICalls=0, executedJavaScript=False)
    return dict(status=expected, reason=None if complete else 'CLOSED_OMISSION', projection=safe, sourceReady=False)



def decode_bound_witness(raw: object) -> dict[str, Any] | None:
    """Decode a closed diagnostic only; never a usable API projection."""
    if type(raw) is not bytes or len(raw) > 32768:
        return None

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('DUPLICATE')
            value[key] = item
        return value

    try:
        v = json.loads(raw.decode('utf8'), object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('FINITE')))
        fields = {'schemaVersion', 'status', 'reason', 'boundKind', 'projectionComplete',
                  'observed', 'prefixWitnesses', 'omissions', 'sourceReady',
                  'sourceChoices', 'sourceAPICalls', 'executedJavaScript',
                  'ASTConstructionMemoryBoundProven'}
        if type(v) is not dict or set(v) != fields:
            return None
        if v['schemaVersion'] != 'coteur-static-query-bound-v2' or v['status'] != 'UNPROVEN':
            return None
        if any(v[k] is not False for k in ('projectionComplete', 'sourceReady',
                                          'executedJavaScript', 'ASTConstructionMemoryBoundProven')):
            return None
        if any(type(v[k]) is not int or v[k] != 0 for k in ('sourceChoices', 'sourceAPICalls')):
            return None
        o = v['observed']
        observed_fields = {'visitedNodes', 'maximumDepthObserved', 'currentDepth',
                           'pendingNodes', 'nodeLimit', 'depthLimit'}
        if type(o) is not dict or set(o) != observed_fields or any(type(x) is not int for x in o.values()):
            return None
        nodes, depth = o['nodeLimit'], o['depthLimit']
        visited, current, maximum, pending = (o[k] for k in
            ('visitedNodes', 'currentDepth', 'maximumDepthObserved', 'pendingNodes'))
        if not (1 <= nodes <= 200000 and 1 <= depth <= 100 and
                0 <= visited <= nodes and 0 <= pending <= nodes and
                0 <= current <= maximum <= depth + 1 and current <= visited):
            return None
        if maximum == depth + 1 and current != maximum:
            return None
        kind, reason = v['boundKind'], v['reason']
        if type(kind) is not str or type(reason) is not str:
            return None
        if kind == 'NODE_VISITS':
            valid = reason == 'AST_NODE_BOUND' and visited == nodes
        elif kind == 'WORK_QUEUE':
            # pending excludes discarded local children: no invented child count.
            valid = (reason == 'AST_NODE_BOUND' and 1 <= visited <= nodes and
                     current < visited and maximum <= depth)
        elif kind == 'DEPTH':
            valid = (reason == 'AST_DEPTH_BOUND' and visited < nodes and
                     current == maximum == depth + 1)
        else:
            valid = False
        if not valid:
            return None
        omissions = v['omissions']
        if (type(omissions) is not dict or set(omissions) != {'candidates', 'prefixes', 'pieces', 'query'}
                or not all(integer(x) for x in omissions.values())):
            return None
        witnesses = v['prefixWitnesses']
        if type(witnesses) is not list or len(witnesses) > 4:
            return None
        if len(json.dumps(witnesses, ensure_ascii=False, separators=(',', ':')).encode('utf8')) > 4096:
            return None
        copied: list[dict[str, Any]]
        seen: set[str]
        copied, seen = [], set()
        for item in witnesses:
            if (type(item) is not dict or set(item) != PREFIX or not path(item['path'])
                    or any(ord(c) < 33 or 127 <= ord(c) <= 159 or c.isspace() for c in item['path'])
                    or not integer(item['sourceOffset']) or item['queryValuesElided'] is not True
                    or item['contractEstablished'] is not False or item['path'] in seen):
                return None
            seen.add(item['path'])
            copied.append(dict(path=item['path'], sourceOffset=item['sourceOffset'],
                               queryValuesElided=True, contractEstablished=False))
        return dict(schemaVersion='coteur-static-query-bound-v2', status='UNPROVEN',
                    reason=reason, boundKind=kind, projectionComplete=False, observed=dict(o),
                    prefixWitnesses=copied, omissions=dict(omissions), sourceReady=False,
                    sourceChoices=0, sourceAPICalls=0, executedJavaScript=False,
                    ASTConstructionMemoryBoundProven=False)
    except (ValueError, UnicodeError, RecursionError, TypeError, OverflowError):
        return None


def classify_child(*, returncode: object, timed_out: object, stdout: object, stderr: object) -> dict[str, Any]:
    """Validate one completed local projector; retain no raw failure output."""
    from hashlib import sha256

    if type(timed_out) is not bool or type(stdout) is not bytes or type(stderr) is not bytes:
        raise ValueError("CHILD_METADATA")
    if returncode is not None and (type(returncode) is not int or not -255 <= returncode <= 4294967295):
        raise ValueError("CHILD_METADATA")
    metadata = dict(childExit=returncode, timedOut=timed_out, stdoutBytes=len(stdout),
                    stderrBytes=len(stderr), stderrSHA256=sha256(stderr).hexdigest())
    failure: dict[str, Any] = dict(status="UNPROVEN", reason=None, projection=None, sourceReady=False,
                   childReason=None, **metadata)
    if timed_out:
        return dict(failure, reason="CHILD_TIMEOUT")
    if len(stdout) > 32768:
        return dict(failure, reason="STDOUT_CAP")
    if returncode is None:
        return dict(failure, reason="CHILD_METADATA")
    if returncode != 0:
        bound = decode_bound_witness(stdout)
        if bound is not None:
            return dict(failure, reason='CHILD_NONZERO', childReason=bound['reason'], boundWitness=bound)
        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("DUPLICATE")
                value[key] = item
            return value
        try:
            error = json.loads(stdout.decode("utf8"), object_pairs_hook=unique,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE")))
        except (ValueError, UnicodeError, RecursionError):
            error = None
        closed = {"INPUT_BOUND", "UNSUPPORTED_SYNTAX", "AST_BOUND", "OUTPUT_BOUND",
                  "DEPENDENCY_PIN", "DEPENDENCY_UNPROVEN", "LOCAL_UNPROVEN"}
        if (type(error) is dict and set(error) == {"schemaVersion", "status", "reason", "sourceReady"}
                and error["schemaVersion"] == "coteur-static-query-error-v1"
                and error["status"] == "UNPROVEN" and error["sourceReady"] is False
                and type(error["reason"]) is str and error["reason"] in closed):
            failure["childReason"] = error["reason"]
        return dict(failure, reason="CHILD_NONZERO")
    return dict(classify(stdout), **metadata)
