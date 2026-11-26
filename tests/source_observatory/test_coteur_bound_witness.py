"""Tiny closed witnesses for static Coteur diagnostics, without provider data."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from robin.source_observatory import coteur_static as protocol

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "cockpit/scripts/coteur-static-query-shapes.cjs"
NODE = os.environ.get("ROBIN_TEST_NODE") or shutil.which("node")


def witness():
    return dict(schemaVersion="coteur-static-query-bound-v2", status="UNPROVEN",
                reason="AST_NODE_BOUND", boundKind="NODE_VISITS", projectionComplete=False,
                observed=dict(visitedNodes=10, maximumDepthObserved=4, currentDepth=4,
                              pendingNodes=2, nodeLimit=10, depthLimit=100),
                prefixWitnesses=[dict(path="/synthetic", sourceOffset=0,
                                     queryValuesElided=True, contractEstablished=False)],
                omissions=dict(candidates=0, prefixes=0, pieces=0, query=0),
                sourceReady=False, sourceChoices=0, sourceAPICalls=0,
                executedJavaScript=False, ASTConstructionMemoryBoundProven=False)


def consume(value, code=1):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    return protocol.classify_child(returncode=code, timed_out=False, stdout=raw, stderr=b"")


def test_closed_witness_is_diagnostic_only():
    value = witness()
    result = consume(value)
    assert result.get("boundWitness") == value
    assert result["childReason"] == "AST_NODE_BOUND"
    assert result["projection"] is None and result["sourceReady"] is False
    assert "boundWitness" not in consume(value, 0)


@pytest.mark.parametrize("control", ["\x00", "\x1f", "\x7f", "\x80", "\x9f", "\u00a0"])
def test_final_path_control_restriction(control):
    value = witness()
    value["prefixWitnesses"][0]["path"] = "/a" + control + "b"
    assert "boundWitness" not in consume(value)


@pytest.mark.parametrize("mutation", ["bool", "kind", "extra", "depth", "values", "count"])
def test_untrusted_diagnostics_fail_closed(mutation):
    value = witness()
    if mutation == "bool":
        value["observed"]["nodeLimit"] = True
    elif mutation == "kind":
        value["boundKind"] = "DEPTH"
    elif mutation == "extra":
        value["extra"] = "SYNTHETIC_POISON"
    elif mutation == "depth":
        value["observed"]["maximumDepthObserved"] = 3
    elif mutation == "values":
        value["prefixWitnesses"][0]["queryValuesElided"] = False
    else:
        value["prefixWitnesses"] *= 5
    result = consume(value)
    assert "boundWitness" not in result and result["projection"] is None


def test_duplicate_nonfinite_and_timeout_rejected():
    raw = json.dumps(witness()).encode()
    for bad in [raw.replace(b'"status": "UNPROVEN"', b'"status":"UNPROVEN","status":"UNPROVEN"'),
                raw.replace(b'"sourceChoices": 0', b'"sourceChoices":NaN')]:
        assert "boundWitness" not in consume(bad)
    result = protocol.classify_child(returncode=1, timed_out=True, stdout=raw, stderr=b"")
    assert result["reason"] == "CHILD_TIMEOUT" and "boundWitness" not in result


def project(source, limits):
    assert NODE, "Node is required for the producer/consumer integration"
    script = "const p=require(process.argv[1]);const x=JSON.parse(process.argv[2]);" +              "process.stdout.write(JSON.stringify(p.project(x.source,x.limits)));"
    env = {k: v for k, v in os.environ.items() if k not in {"NODE_OPTIONS", "NODE_PATH"}}
    run = subprocess.run([NODE, "-e", script, str(SCRIPT), json.dumps(dict(source=source, limits=limits))],
                         capture_output=True, timeout=8, cwd=ROOT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert run.returncode == 0 and run.stderr == b""
    return json.loads(run.stdout)


@pytest.mark.parametrize("source,limits,kind", [
    ("0;", dict(maxNodes=2), "NODE_VISITS"),
    ("0;1;2;", dict(maxNodes=2), "WORK_QUEUE"),
    ("const x=(((a+b)+c)+d);", dict(maxDepth=1), "DEPTH"),
])
def test_actual_tiny_producer_to_consumer(source, limits, kind):
    value = project(source, limits)
    assert value["boundKind"] == kind
    assert consume(value)["boundWitness"] == value
    assert value["projectionComplete"] is False and value["sourceReady"] is False
    assert value["ASTConstructionMemoryBoundProven"] is False


def test_success_and_old_failure_contracts_preserved():
    value = project("fetch('/api/pronos?page=ELIDE_VALUE',{method:'GET'});", {})
    assert "ELIDE_VALUE" not in json.dumps(value)
    assert consume(value, 0)["status"] == "STATIC_AST_CANDIDATES_ONLY"
    old = dict(schemaVersion="coteur-static-query-error-v1", status="UNPROVEN",
               reason="AST_BOUND", sourceReady=False)
    result = consume(old)
    assert result["childReason"] == "AST_BOUND" and "boundWitness" not in result


@pytest.mark.parametrize("control", ["\x7f", "\x80", "\x85", "\x9f", "\u00a0"])
def test_producer_filters_invalid_bound_prefixes(control):
    source = json.dumps("/api/synthetic" + control) + "; const x=(((a+b)+c)+d);"
    value = project(source, dict(maxDepth=3))
    assert value["schemaVersion"] == "coteur-static-query-bound-v2"
    assert value["prefixWitnesses"] == []
    assert consume(value)["boundWitness"] == value
