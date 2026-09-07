"""Deterministic adapter tests. No human approvals or model calls are simulated."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from verify import enrich_items, sha256, source_index


ROOT = Path(__file__).resolve().parent


class ReviewAdapterTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "Littlestone.lean").read_text()
        self.spec = json.loads((ROOT / "review-index.json").read_text())

    def test_every_declaration_and_have_has_an_item(self):
        items = source_index(self.source, self.spec)
        self.assertEqual(len(items), 19)
        self.assertEqual(sum(i["kind"] == "have" for i in items), 6)
        self.assertEqual(sum(i["kind"] == "generalization" for i in items), 2)

    def test_missing_have_index_fails(self):
        del self.spec["local_arguments"]["uniform_no_positive.have.1"]
        with self.assertRaisesRegex(ValueError, "Missing local argument"):
            source_index(self.source, self.spec)

    def test_untyped_have_fails(self):
        source = self.source.replace("have impossible_bound : 2 ≤ 1 := by", "have impossible_bound := by")
        with self.assertRaisesRegex(ValueError, "explicit, named, and typed"):
            source_index(source, self.spec)

    def test_unsupported_forms_stay_provisional(self):
        for addition in ("\n#eval IO.println 1", "\naxiom counterfeit : False", "\nmacro \"hidden\" : tactic => `(tactic| trivial)"):
            with self.subTest(addition=addition), self.assertRaisesRegex(ValueError, "Unsupported"):
                source_index(self.source + addition, self.spec)

    def test_missing_elaborated_context_fails(self):
        packet = json.loads((ROOT / "review.json").read_text())
        traces_removed = [m for m in packet["messages"] if m.get("kind") != "trace"]
        with self.assertRaisesRegex(ValueError, "Missing unique elaborated local context"):
            enrich_items(source_index(self.source, self.spec), traces_removed, self.spec)

    def test_source_change_rejected_before_lean(self):
        with tempfile.TemporaryDirectory(prefix="mathai-rejection-") as directory:
            temporary = Path(directory)
            candidate = temporary / "Candidate.lean"
            candidate.write_text(self.source + "\n#eval IO.println 1\n")
            output = temporary / "result.json"
            result = subprocess.run([sys.executable, str(ROOT / "verify.py"), "--candidate", str(candidate),
                                     "--baseline", str(ROOT / "review.json"), "--output", str(output),
                                     "--project-root", str(temporary / "does-not-exist")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            evidence = json.loads(output.read_text())
            self.assertIn("BEFORE Lean execution", evidence["checks"][0]["detail"])
            self.assertEqual(evidence["verified_item_ids"], [])

    def test_compiled_generality_does_not_close_open_obligations(self):
        packet = json.loads((ROOT / "review.json").read_text())
        ids = {i["id"] for i in packet["items"]}
        self.assertIn("constants_exact_depth", ids)
        self.assertTrue(all(o["id"] not in ids and o["status"] == "open" for o in packet["open_obligations"]))
        self.assertEqual(packet["human_approval"], "not_performed")

    def test_packet_bound_to_exact_source_and_real_contexts(self):
        packet = json.loads((ROOT / "review.json").read_text())
        self.assertEqual(packet["source_sha256"], sha256(self.source.encode()))
        regenerated = enrich_items(source_index(self.source, self.spec), packet["messages"], self.spec)
        self.assertEqual(regenerated, packet["items"])
        haves = [i for i in regenerated if i["kind"] == "have"]
        self.assertTrue(all("⊢" in i["context"] for i in haves))
        self.assertTrue(all("@" in i["elaborated_form"] for i in haves))


if __name__ == "__main__":
    unittest.main()
