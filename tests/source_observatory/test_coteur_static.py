"""Synthetic public CLI/protocol integration; never contacts a supplier."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from robin.source_observatory.coteur_static import classify, classify_child

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "cockpit/scripts/coteur-static-query-shapes.cjs"
NODE = os.environ.get("ROBIN_TEST_NODE") or shutil.which("node")


def positive():
    return dict(schemaVersion="coteur-static-query-shapes-v1", status="STATIC_AST_CANDIDATES_ONLY",
                projectionComplete=True, omissions=dict(candidates=0, prefixes=0, pieces=0, query=0),
                candidates=[dict(method="GET", methodEvidence="explicit_fetch_option", sourceOffset=0,
                                 pathSegments=[dict(literal="/api/pronos")], literalQueryKeysObserved=["page"],
                                 queryValuesElided=True, runtimeQueryContractEstablished=False,
                                 bindingEstablished=False, contractEstablished=False)], prefixes=[],
                sourceReady=False, sourceChoices=0, sourceAPICalls=0, executedJavaScript=False)


def cli(source, hook=None):
    assert NODE, "Node is required for this integration"
    args = [NODE]
    if hook:
        args += ["--require", str(hook)]
    args.append(str(SCRIPT))
    env = {k: v for k, v in os.environ.items() if k not in {"NODE_OPTIONS", "NODE_PATH"}}
    return subprocess.run(args, input=source, capture_output=True, cwd=ROOT, timeout=8,
                          env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def test_final_method_evidence_guard_rejects_unhashable_value():
    value = positive()
    value["candidates"][0]["methodEvidence"] = []
    assert classify(json.dumps(value).encode())["reason"] == "OUTPUT_CONTRACT"


def test_final_json_recursion_guard_returns_closed_failure(monkeypatch):
    from robin.source_observatory import coteur_static

    def decoder_limit(*args, **kwargs):
        raise RecursionError("SYNTHETIC_DECODER_LIMIT")

    with monkeypatch.context() as isolated:
        isolated.setattr(coteur_static.json, "loads", decoder_limit)
        result = classify(b"{}")
    assert result["reason"] == "INVALID_JSON"
    assert result["status"] == "UNPROVEN" and result["projection"] is None
    assert result["sourceReady"] is False


def test_actual_cli_accepts_only_query_key_metadata():
    run = cli(b"fetch('/api/pronos?tipster='+uid+'&page=DO_NOT_RETAIN',{method:'GET'});")
    assert run.returncode == 0 and not run.stderr
    assert b"DO_NOT_RETAIN" not in run.stdout
    result = classify_child(returncode=run.returncode, timed_out=False, stdout=run.stdout, stderr=run.stderr)
    assert result["status"] == "STATIC_AST_CANDIDATES_ONLY"
    candidate = result["projection"]["candidates"][0]
    assert candidate["literalQueryKeysObserved"] == ["tipster", "page"]
    assert not candidate["runtimeQueryContractEstablished"] and not candidate["contractEstablished"]


def test_actual_cli_syntax_failure_is_closed_and_classified():
    run = cli(b"(")
    assert run.returncode == 1 and not run.stderr
    result = classify_child(returncode=run.returncode, timed_out=False, stdout=run.stdout, stderr=run.stderr)
    assert result["reason"] == "CHILD_NONZERO" and result["childReason"] == "UNSUPPORTED_SYNTAX"
    assert result["projection"] is None and b"Error:" not in run.stdout


def test_actual_cli_dependency_guard_with_disclosed_resolver_injection(tmp_path):
    hook = tmp_path / "dependency-absent.cjs"
    hook.write_text("const M=require('node:module'),old=M._resolveFilename;"
                    "M._resolveFilename=function(name,...args){if(name==='typescript')"
                    "throw Error('SYNTHETIC_DEPENDENCY_ABSENT');return old.call(this,name,...args);};", encoding="utf8")
    run = cli(b"0;", hook)
    assert run.returncode == 1 and not run.stderr
    result = classify_child(returncode=run.returncode, timed_out=False, stdout=run.stdout, stderr=run.stderr)
    assert result["reason"] == "CHILD_NONZERO" and result["childReason"] == "DEPENDENCY_UNPROVEN"
    assert b"SYNTHETIC_DEPENDENCY_ABSENT" not in run.stdout


def test_completed_child_timeout_and_stdout_cap_remain_distinct():
    timeout = classify_child(returncode=None, timed_out=True, stdout=b"", stderr=b"")
    oversize = classify_child(returncode=0, timed_out=False, stdout=b"x" * 32769, stderr=b"")
    assert timeout["reason"] == "CHILD_TIMEOUT" and oversize["reason"] == "STDOUT_CAP"
    assert timeout["projection"] is None and oversize["projection"] is None



def test_actual_cli_stdin_cap_is_enforced_before_parsing():
    run = cli(b" " * 2000001)
    assert run.returncode == 1 and not run.stderr
    result = classify_child(returncode=run.returncode, timed_out=False, stdout=run.stdout, stderr=run.stderr)
    assert result["reason"] == "CHILD_NONZERO" and result["childReason"] == "INPUT_BOUND"
    assert result["projection"] is None and not result["sourceReady"]
