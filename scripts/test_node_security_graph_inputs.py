"""Offline preparation refusal tests; no Cargo, network, or candidate execution."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import node_security_graph_inputs as inputs


REPO = Path(__file__).resolve().parent.parent


class InputPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="node-graph-inputs-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve()
        for relative in [*inputs.BASELINES, inputs.DOCUMENT]:
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPO / relative).read_bytes())

    def prepare(self, bundle_id="example"):
        return inputs.prepare(self.repo, bundle_id)

    def test_real_inputs_match_eight_dependencies_without_lock_generation(self):
        files = inputs.expected_files(self.repo)
        self.assertEqual(len(files), 6)
        self.assertNotIn("input/Cargo.lock", files)
        self.assertEqual(inputs.digest(files["input/Cargo.toml"]), inputs.MANIFEST_SHA256)
        self.assertLess(sum(map(len, files.values())), inputs.MAX_INPUT_BYTES)
        self.assertFalse((self.repo / "artifacts").exists())

    def test_prepare_verify_and_existing_output_refusal(self):
        root = self.prepare()
        self.assertEqual(inputs.verify(self.repo, "example"), {
            "status": "INPUTS_VERIFIED", "execution_ready": False, "execution_authorized": False,
        })
        before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        with self.assertRaises(FileExistsError):
            self.prepare()
        after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(len(before), 7)
        self.assertFalse((root / "target").exists())
        self.assertFalse((root / "cargo-home/registry").exists())

    def test_total_limit_includes_final_marker_and_rejects_before_output(self):
        files = inputs.expected_files(self.repo)
        total = inputs.total_bytes(files)
        with patch.object(inputs, "MAX_INPUT_BYTES", total - 1):
            with self.assertRaisesRegex(inputs.InputError, "total byte limit"):
                self.prepare()
        self.assertFalse((self.repo / "artifacts").exists())
        with patch.object(inputs, "MAX_INPUT_BYTES", total):
            root = self.prepare()
        self.assertEqual(sum(p.stat().st_size for p in root.rglob("*") if p.is_file()), total)

    def test_plan_cannot_claim_execution_and_contains_only_reviewed_commands(self):
        root = self.prepare()
        plan = json.loads((root / "review-plan.json").read_bytes())
        self.assertFalse(plan["execution_ready"])
        self.assertFalse(plan["execution_authorized"])
        self.assertEqual(len(plan["missing_execution_evidence"]), 6)
        commands = plan["commands_for_review_only"]
        self.assertEqual([item["argv"][1] for item in commands], [
            "generate-lockfile", "fetch", "metadata", "metadata", "metadata", "tree", "tree", "tree",
        ])
        self.assertEqual(commands[0]["stage"], "G1")
        self.assertTrue(all(item["stage"] == "G2" for item in commands[1:]))
        self.assertTrue(all("--frozen" in item["argv"] for item in commands[2:]))

    def test_each_baseline_drift_rejects_before_output(self):
        for relative in inputs.BASELINES:
            with self.subTest(relative=relative):
                path = self.repo / relative
                saved = path.read_bytes()
                path.write_bytes(saved + b"\n")
                with self.assertRaisesRegex(inputs.InputError, "baseline input hash"):
                    self.prepare()
                self.assertFalse((self.repo / "artifacts").exists())
                path.write_bytes(saved)

    def test_manifest_and_config_drift_reject_before_output(self):
        document = self.repo / inputs.DOCUMENT
        saved = document.read_text()
        for old, new in [('version = "=0.4.2"', 'version = "=0.4.3"'), ('timeout = 30', 'timeout = 31')]:
            with self.subTest(old=old):
                self.assertIn(old, saved)
                document.write_text(saved.replace(old, new))
                with self.assertRaisesRegex(inputs.InputError, "TOML input hash"):
                    self.prepare()
                self.assertFalse((self.repo / "artifacts").exists())
        document.write_text(saved + '\n```toml\nextra = "block"\n```\n')
        with self.assertRaisesRegex(inputs.InputError, "exactly two"):
            self.prepare()

    def test_invalid_bundle_names_never_create_output(self):
        for name in ["", "..", "../elsewhere", "/tmp/elsewhere", "a/b", "a\\b", "X", "1abc", "a" * 49]:
            with self.subTest(name=name), self.assertRaises(inputs.InputError):
                self.prepare(name)
        self.assertFalse((self.repo / "artifacts").exists())

    def test_source_file_link_and_ancestor_link_reject(self):
        source = self.repo / "node/Cargo.toml"
        elsewhere = self.repo / "manifest-copy"
        source.rename(elsewhere)
        source.symlink_to(elsewhere)
        with self.assertRaises(OSError):
            self.prepare()
        source.unlink()
        elsewhere.rename(source)
        parent = self.repo / "node"
        parent.rename(self.repo / "node-copy")
        parent.symlink_to(self.repo / "node-copy", target_is_directory=True)
        with self.assertRaises(OSError):
            self.prepare()
        self.assertFalse((self.repo / "artifacts").exists())

    def test_hardlinked_source_rejects(self):
        os.link(self.repo / "node/Cargo.toml", self.repo / "linked-manifest")
        with self.assertRaisesRegex(inputs.InputError, "single-link"):
            self.prepare()

    def test_fifo_source_is_rejected_without_blocking(self):
        source = self.repo / "node/Cargo.toml"
        source.unlink()
        os.mkfifo(source)
        with self.assertRaisesRegex(inputs.InputError, "regular"):
            self.prepare()

    def test_source_size_limit_rejects_before_output(self):
        (self.repo / inputs.DOCUMENT).write_bytes(b"x" * (inputs.MAX_SOURCE_BYTES + 1))
        with self.assertRaisesRegex(inputs.InputError, "byte limit"):
            self.prepare()
        self.assertFalse((self.repo / "artifacts").exists())

    def test_linked_output_parent_does_not_write_through(self):
        destination = self.repo / "other"
        destination.mkdir()
        (self.repo / "artifacts").symlink_to(destination, target_is_directory=True)
        with self.assertRaises(OSError):
            self.prepare()
        self.assertEqual(list(destination.iterdir()), [])

    def test_tamper_cannot_be_hidden_by_rehashing_manifest(self):
        root = self.prepare()
        plan_path = root / "review-plan.json"
        plan = json.loads(plan_path.read_bytes())
        plan["execution_ready"] = True
        plan_path.write_bytes(inputs.json_bytes(plan))
        checksums_path = root / "checksums.json"
        checksums = json.loads(checksums_path.read_bytes())
        checksums["files"]["review-plan.json"] = inputs.digest(plan_path.read_bytes())
        checksums_path.write_bytes(inputs.json_bytes(checksums))
        complete_path = root / "complete.json"
        complete = json.loads(complete_path.read_bytes())
        complete["checksums_sha256"] = inputs.digest(checksums_path.read_bytes())
        complete_path.write_bytes(inputs.json_bytes(complete))
        with self.assertRaisesRegex(inputs.InputError, "content mismatch"):
            inputs.verify(self.repo, "example")

    def test_unlisted_file_missing_finalization_and_empty_directory_reject(self):
        root = self.prepare()
        extra = root / "Cargo.lock"
        extra.write_text("not a generated lock\n")
        with self.assertRaises(inputs.InputError):
            inputs.verify(self.repo, "example")
        extra.unlink()
        (root / "target").mkdir()
        with self.assertRaises(inputs.InputError):
            inputs.verify(self.repo, "example")
        (root / "target").rmdir()
        (root / "complete.json").unlink()
        with self.assertRaisesRegex(inputs.InputError, "incomplete"):
            inputs.verify(self.repo, "example")

    def test_prepared_file_and_directory_symlinks_reject(self):
        root = self.prepare()
        saved = self.repo / "saved-input"
        (root / "input").rename(saved)
        (root / "input").symlink_to(saved, target_is_directory=True)
        with self.assertRaises(inputs.InputError):
            inputs.verify(self.repo, "example")
        (root / "input").unlink()
        saved.rename(root / "input")
        original = root / "input/input.rs"
        original.rename(self.repo / "saved-stub")
        original.symlink_to(self.repo / "saved-stub")
        with self.assertRaises(inputs.InputError):
            inputs.verify(self.repo, "example")

    def test_write_failure_keeps_unfinalized_partial_without_retry_overwrite(self):
        write = inputs.write_exclusive
        calls = 0

        def fail_after_first(parent, name, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic write failure")
            write(parent, name, data)

        with patch.object(inputs, "write_exclusive", side_effect=fail_after_first):
            with self.assertRaises(OSError):
                self.prepare()
        root = self.repo / inputs.BUNDLE_PARENT / "example"
        self.assertTrue((root / "input/Cargo.toml").is_file())
        self.assertFalse((root / "complete.json").exists())
        with self.assertRaises(inputs.InputError):
            inputs.verify(self.repo, "example")
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_short_writes_complete_or_fail_without_infinite_loop(self):
        write = os.write
        with patch.object(os, "write", side_effect=lambda fd, data: write(fd, data[:7])):
            self.prepare()
        self.assertEqual(inputs.verify(self.repo, "example")["status"], "INPUTS_VERIFIED")
        with patch.object(os, "write", return_value=0):
            with self.assertRaisesRegex(inputs.InputError, "short input write"):
                self.prepare("zero-write")
        self.assertFalse((self.repo / inputs.BUNDLE_PARENT / "zero-write/complete.json").exists())

    def test_unsupported_execution_arguments_stop_before_input_access(self):
        for argv in [[], ["run"], ["g1"], ["g2"], ["fetch"], ["prepare", "example", "--allow-unverified"]]:
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with patch.object(inputs, "expected_files", side_effect=AssertionError("must not read")):
                    with self.assertRaises(SystemExit) as caught:
                        inputs.main(argv)
                self.assertEqual(caught.exception.code, 2)

    def test_cli_reports_only_bounded_diagnostics(self):
        output, error = io.StringIO(), io.StringIO()
        with patch.object(inputs, "__file__", str(self.repo / "scripts/node_security_graph_inputs.py")):
            with redirect_stdout(output), redirect_stderr(error):
                self.assertEqual(inputs.main(["check"]), 0)
                self.assertEqual(inputs.main(["verify", "missing"]), 2)
        self.assertFalse(json.loads(output.getvalue())["execution_ready"])
        self.assertNotIn(str(self.repo), error.getvalue())
        self.assertIn("STOP/input-preparation", error.getvalue())


if __name__ == "__main__":
    unittest.main()
