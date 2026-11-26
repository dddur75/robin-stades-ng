"""CLI routing preserves legacy callers and requires explicit opaque execution."""
from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from robin.source_observatory import olbg_opaque_campaign as opaque


class CLIRouting(unittest.TestCase):
    def test_legacy_compatibility_and_explicit_opaque(self) -> None:
        script = Path(__file__).resolve().parents[2] / "cockpit/scripts/collect-olbg-tipsters.py"
        spec = importlib.util.spec_from_file_location("opaque_cli_contract", script)
        assert spec is not None and spec.loader is not None
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            approval = root / "approval.json"
            raw = b'{"planSHA256":"synthetic"}'
            approval.write_bytes(raw)
            base = ["--directory", str(root)]
            approved = [*base, "--opaque", "--approval", str(approval),
                        "--approval-sha", sha256(raw).hexdigest()]
            def call(args: list[str]) -> dict:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(cli.main(args), 0)
                return json.loads(output.getvalue())
            with (patch.object(cli, "run_olbg_slot", return_value={"state": "legacy"}) as run,
                  patch.object(cli, "validate_olbg_campaign") as validate,
                  patch.object(opaque, "run_opaque_slot", return_value={"state": "opaque"}) as run_new,
                  patch.object(opaque, "validate_campaign") as validate_new):
                self.assertEqual(call(base), {"state": "legacy"})
                run.assert_called_once_with(root)
                self.assertEqual(call([*base, "--validate-only"]),
                                 {"state": "validated", "requests": 0})
                validate.assert_called_once_with(root)
                self.assertEqual(call([*approved, "--validate-only"]),
                                 {"state": "VALIDATED_ONLY", "requests": 0})
                run_new.assert_not_called()
                self.assertEqual(call([*approved, "--execute"]), {"state": "opaque"})
                run_new.assert_called_once_with(root, approval=json.loads(raw))
                self.assertEqual(validate_new.call_count, 2)
                for args in ([*base, "--execute"], [*base, "--approval", str(approval)],
                             [*base, "--opaque"], [*approved, "--validate-only", "--execute"]):
                    with self.subTest(args=args), redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as error:
                            cli.main(args)
                        self.assertEqual(error.exception.code, 2)
                invalid = [*base, "--opaque", "--approval", str(approval),
                           "--approval-sha", "0" * 64, "--execute"]
                with self.assertRaises(PermissionError):
                    cli.main(invalid)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run_new.call_count, 1)
                self.assertEqual(validate_new.call_count, 2)
