"""Offline protocol tests with simulated human decisions and synthetic checks."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controller import Controller, GateError, MAX_BRANCHES, digest, packet_items

SOURCE = "-- synthetic fixture; never claimed as a checked mathematical proof\n"


def item(name, kind="theorem", deps=(), scope="local"):
    return {"id": name, "kind": kind, "source": {"line": 1}, "context": "x : Nat", "statement": "True", "argument": "Synthetic test purpose", "dependencies": list(deps), "scope": scope}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mathai-test-")
        self.root = Path(self.tmp.name)
        self.baseline = self.root / "review.json"
        self.verifier = self.root / "fixture_verifier.py"
        shutil.copyfile(Path(__file__).with_name("fixture_verifier.py"), self.verifier)
        self.packet = {"source_sha256": digest(SOURCE), "items": [item("hyp", "hypothesis"), item("lemma", deps=["hyp"]), item("target", deps=["lemma"])]}
        self.write_baseline()
        self.ctl = Controller(self.root / "state")
        self.rev = self.ctl.initialize(self.baseline, self.verifier, Path.cwd())["revision"]

    def tearDown(self):
        self.ctl.close()
        self.tmp.cleanup()

    def write_baseline(self):
        self.baseline.write_text(json.dumps(self.packet))

    def replace_baseline(self, mode):
        self.packet["fixture_mode"] = mode
        self.write_baseline()
        self.rev = self.ctl.revise(self.baseline, "simulated human", "Fixture mode changed")["revision"]

    def submit(self, **kwargs):
        return self.ctl.submit(kwargs.get("source", SOURCE), kwargs.get("packet", self.packet), kwargs.get("revision", self.rev), kwargs.get("filename", "Candidate.lean"), kwargs.get("branch"))["candidate"]

    def approve(self, cid, ids=None):
        for i in ids if ids is not None else [i["id"] for i in self.packet["items"]]:
            self.ctl.review(cid, i, "approved", "simulated human", "Unit-test decision")

    def accepted_candidate(self):
        cid = self.submit()
        self.approve(cid)
        self.ctl.verify(cid)
        self.ctl.promote(cid)
        return cid

    def test_initialization_records_setup_not_human_review(self):
        events = self.ctl.db.execute("SELECT kind,payload FROM events ORDER BY seq").fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "specification-initialized")
        payload = json.loads(events[0]["payload"])
        self.assertEqual(payload["actor"], "controller-setup")
        self.assertEqual(payload["human_approval"], "not_performed")
        self.assertNotIn("reviewer", payload)
        self.assertEqual(self.ctl.db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 0)
        self.assertEqual(self.ctl.db.execute("SELECT COUNT(*) FROM acceptances").fetchone()[0], 0)

    def test_revision_retains_explicit_reviewer_without_approving_items(self):
        revised = self.ctl.revise(self.baseline, "synthetic human", "Explicit fixture revision")
        event = self.ctl.db.execute("SELECT kind,payload FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        self.assertEqual(event["kind"], "premise-revised")
        payload = json.loads(event["payload"])
        self.assertEqual(payload["reviewer"], "synthetic human")
        self.assertEqual(payload["reason"], "Explicit fixture revision")
        self.assertEqual(payload["revision"], revised["revision"])
        self.assertEqual(self.ctl.db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 0)

    def test_check_without_review_is_provisional(self):
        cid = self.submit()
        self.assertEqual(self.ctl.verify(cid)["result"]["status"], "passed")
        with self.assertRaisesRegex(GateError, "Unapproved"):
            self.ctl.promote(cid)
        self.assertFalse(self.ctl.candidate_status(cid)["accepted"]["local"])

    def test_review_without_check_is_provisional(self):
        cid = self.submit()
        self.approve(cid)
        with self.assertRaisesRegex(GateError, "No trusted"):
            self.ctl.promote(cid)

    def test_all_dependencies_must_be_reviewed(self):
        cid = self.submit()
        self.approve(cid, ["target", "lemma"])
        self.ctl.verify(cid)
        with self.assertRaisesRegex(GateError, "hyp"):
            self.ctl.promote(cid)

    def test_acceptance_persists_restart_and_does_not_generalize(self):
        cid = self.accepted_candidate()
        self.ctl.close()
        self.ctl = Controller(self.root / "state")
        result = self.ctl.candidate_status(cid)
        self.assertTrue(result["accepted"]["local"])
        self.assertFalse(result["accepted"]["general"])
        self.assertEqual(result["generalization"], "unresolved")
        with self.assertRaisesRegex(GateError, "No explicit general"):
            self.ctl.promote(cid, "general")

    def test_rejecting_review_revokes_acceptance(self):
        cid = self.accepted_candidate()
        self.ctl.review(cid, "hyp", "rejected", "simulated human", "Withdraw assumption")
        self.assertFalse(self.ctl.candidate_status(cid)["accepted"]["local"])

    def test_same_content_new_revision_invalidates_every_old_acceptance(self):
        cid = self.accepted_candidate()
        self.ctl.revise(self.baseline, "simulated human", "Import baseline reviewed afresh")
        status = self.ctl.candidate_status(cid)
        self.assertTrue(status["stale"])
        self.assertFalse(status["accepted"]["local"])
        with self.assertRaisesRegex(GateError, "Stale"):
            self.ctl.promote(cid)
        with self.assertRaisesRegex(GateError, "Stale"):
            self.ctl.review(cid, "target", "approved", "human", "No stale approval")
        with self.assertRaisesRegex(GateError, "Stale"):
            self.submit()

    def test_source_hash_is_bound_to_review_packet(self):
        cid = self.submit(source=SOURCE + "-- edit\n")
        self.approve(cid)
        self.assertEqual(self.ctl.verify(cid)["result"]["status"], "failed")
        with self.assertRaises(GateError):
            self.ctl.promote(cid)

    def test_model_metadata_cannot_claim_human_approval_or_close_obligation(self):
        forged = copy.deepcopy(self.packet)
        forged.update(human_approval="approved", open_obligations=[{"status": "closed"}], source_sha256="invented", runtime_inputs=[], messages=["verified"])
        cid = self.submit(packet=forged)
        stored = json.loads(self.ctl.candidate(cid)["packet"])
        self.assertEqual(set(stored), {"items", "source_sha256"})
        self.assertEqual(stored["source_sha256"], digest(SOURCE))
        self.assertEqual(self.ctl.candidate_status(cid)["reviews"], {})
        self.assertFalse(self.ctl.candidate_status(cid)["accepted"]["local"])

    def test_runtime_input_mutation_after_check_prevents_promotion_and_current_acceptance(self):
        runtime_file = self.root / "lean-toolchain"
        runtime_file.write_text("synthetic-toolchain")
        self.packet["runtime_inputs"] = [{"path": "lean-toolchain", "sha256": digest(runtime_file.read_bytes())}]
        self.ctl.close()
        self.ctl = Controller(self.root / "runtime-state")
        self.write_baseline()
        self.rev = self.ctl.initialize(self.baseline, self.verifier, self.root)["revision"]
        cid = self.accepted_candidate()
        runtime_file.write_text("changed-toolchain")
        with self.assertRaisesRegex(GateError, "runtime input changed"):
            self.ctl.promote(cid)
        self.assertFalse(self.ctl.candidate_status(cid)["accepted"]["local"])

    def test_source_tamper_fails_closed(self):
        cid = self.accepted_candidate()
        source = Path(self.ctl.candidate(cid)["source"])
        source.chmod(0o600)
        source.write_text("tampered")
        with self.assertRaisesRegex(GateError, "artifact changed"):
            self.ctl.promote(cid)

    def test_baseline_tamper_fails_closed(self):
        cid = self.accepted_candidate()
        baseline = Path(self.ctl.revision()["baseline"])
        baseline.chmod(0o600)
        baseline.write_text("{}")
        with self.assertRaisesRegex(GateError, "Baseline snapshot changed"):
            self.ctl.promote(cid)
        self.assertFalse(self.ctl.candidate_status(cid)["accepted"]["local"])

    def test_verifier_tamper_fails_closed(self):
        cid = self.accepted_candidate()
        self.verifier.write_text(self.verifier.read_text() + "\n# changed\n")
        with self.assertRaisesRegex(GateError, "Verifier changed"):
            self.ctl.promote(cid)
        self.assertFalse(self.ctl.candidate_status(cid)["accepted"]["local"])

    def test_bad_verifier_outcomes_cannot_promote(self):
        for mode in ("failed", "incomplete", "wrong_inventory", "missing_ids", "nonzero", "malformed", "no_output"):
            with self.subTest(mode=mode):
                self.replace_baseline(mode)
                cid = self.submit()
                self.approve(cid)
                self.ctl.verify(cid)
                with self.assertRaises(GateError):
                    self.ctl.promote(cid)

    def test_check_timeout_is_failed_not_unchecked(self):
        self.replace_baseline("timeout")
        cid = self.submit()
        result = self.ctl.verify(cid, timeout=0.05)["result"]
        self.assertEqual(result["status"], "failed")
        self.assertIn("timeout", result["error"])

    def test_credentials_are_not_passed_to_verifier(self):
        os.environ["FAKE_TEST_API_KEY"] = "synthetic-not-a-secret"
        try:
            result = self.ctl.verify(self.submit())["result"]
        finally:
            del os.environ["FAKE_TEST_API_KEY"]
        self.assertEqual(result["credentials_present"], [])

    def test_revision_change_during_check_cannot_accept(self):
        self.replace_baseline("slow")
        cid = self.submit()
        self.approve(cid)
        result = {}
        def run_check():
            other = Controller(self.root / "state")
            try:
                result.update(other.verify(cid))
            finally:
                other.close()
        thread = threading.Thread(target=run_check)
        thread.start()
        time.sleep(0.15)
        self.ctl.revise(self.baseline, "simulated human", "Revision during check")
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result["result"]["stale"])
        with self.assertRaises(GateError):
            self.ctl.promote(cid)

    def test_general_requires_explicit_bridge_and_local_closure(self):
        self.packet["items"].append(item("bridge", "transport", ["target"], "general"))
        self.write_baseline()
        self.rev = self.ctl.revise(self.baseline, "simulated human", "Add a bridge")["revision"]
        cid = self.submit()
        self.ctl.verify(cid)
        self.approve(cid, ["bridge"])
        with self.assertRaisesRegex(GateError, "Unapproved"):
            self.ctl.promote(cid, "general")
        self.approve(cid)
        self.assertTrue(self.ctl.promote(cid, "general")["accepted"]["general"])

    def test_general_scope_label_alone_is_not_a_bridge(self):
        self.packet["items"] = [item("unsupported", "theorem", scope="general")]
        self.write_baseline()
        self.rev = self.ctl.revise(self.baseline, "simulated human", "Explicit test")["revision"]
        cid = self.submit()
        self.approve(cid)
        self.ctl.verify(cid)
        with self.assertRaisesRegex(GateError, "requires an explicit"):
            self.ctl.promote(cid, "general")

    def test_no_agent_approval_or_evidence_import_surface(self):
        for operation in ("approve", "review", "answer", "revise", "promote", "set_verifier", "import_verification", "shell", "exec"):
            with self.subTest(operation=operation), self.assertRaises(GateError):
                self.ctl.agent_request({"operation": operation})

    def test_questions_are_durable_and_answers_do_not_approve(self):
        batch = self.ctl.queue_questions([{"prompt": "Which domain?", "consequence": "Changes target"}, {"prompt": "Keep generalization open?", "consequence": "Scope decision"}], self.rev)
        cid = self.submit()
        self.ctl.answer(batch["question_ids"][0], "Use finite domain", "simulated human")
        self.ctl.close()
        self.ctl = Controller(self.root / "state")
        context = self.ctl.context()
        self.assertEqual(len(context["questions"]), 2)
        self.assertEqual(context["questions"][0]["answer"], "Use finite domain")
        self.assertIsNone(context["questions"][1]["answer"])
        self.assertEqual(self.ctl.candidate_status(cid)["reviews"], {})

    def test_question_batch_is_atomic(self):
        with self.assertRaises(GateError):
            self.ctl.queue_questions([{"prompt": "Good", "consequence": "Explicit"}, {"prompt": "Missing consequence"}], self.rev)
        self.assertEqual(len(self.ctl.context()["questions"]), 0)

    def test_branch_isolation_and_cap(self):
        questions = self.ctl.queue_questions([{"prompt": "Which assumption?", "consequence": "Two routes"}], self.rev)
        bids = [self.ctl.branch(questions["question_ids"], ["Assume route " + str(i)], self.rev)["branch"] for i in range(MAX_BRANCHES)]
        self.assertEqual(len(set(bids)), MAX_BRANCHES)
        paths = [Path(r[0]) for r in self.ctl.db.execute("SELECT path FROM branches")]
        self.assertEqual(len(set(paths)), MAX_BRANCHES)
        for path in paths:
            self.assertFalse(json.loads((path / "assumptions.json").read_text())["accepted_use"])
        with self.assertRaisesRegex(GateError, "cap"):
            self.ctl.branch(questions["question_ids"], ["Fifth"], self.rev)
        cid = self.submit(branch=bids[0])
        self.assertFalse(self.ctl.candidate_status(cid)["accepted"]["local"])

    def test_agent_context_recovers_branches_and_candidate_links_after_restart(self):
        questions = self.ctl.queue_questions([
            {"prompt": "Which representation?", "consequence": "Changes transport"},
            {"prompt": "Keep broader claim open?", "consequence": "Preserves scope"},
        ], self.rev)
        hypotheses = ["Provisional finite-domain route", "General target remains open"]
        branch = self.ctl.branch(questions["question_ids"], hypotheses, self.rev)["branch"]
        cid = self.submit(branch=branch)
        independent = self.submit()
        self.ctl.close()
        self.ctl = Controller(self.root / "state")
        context = self.ctl.agent_request({"operation": "read_context"})
        self.assertEqual(context["branches"], [{
            "branch": branch, "revision": self.rev,
            "question_ids": questions["question_ids"], "hypotheses": hypotheses,
            "stale": False, "accepted_use": False,
        }])
        candidates = {c["candidate"]: c for c in context["candidates"]}
        self.assertEqual(candidates[cid]["branch"], branch)
        self.assertIsNone(candidates[independent]["branch"])
        self.assertEqual(candidates[cid]["reviews"], {})
        self.assertFalse(any(candidates[cid]["accepted"].values()))
        self.assertTrue(all(q["answer"] is None for q in context["questions"]))

    def test_agent_context_keeps_stale_branch_history_separate_from_current_work(self):
        old = self.ctl.branch([], ["Old provisional route"], self.rev)["branch"]
        old_candidate = self.submit(branch=old)
        self.rev = self.ctl.revise(self.baseline, "synthetic human", "New fixture revision")["revision"]
        current = self.ctl.branch([], ["Current provisional route"], self.rev)["branch"]
        context = self.ctl.agent_request({"operation": "read_context"})
        branches = {b["branch"]: b for b in context["branches"]}
        self.assertTrue(branches[old]["stale"])
        self.assertFalse(branches[current]["stale"])
        self.assertTrue(all(not b["accepted_use"] for b in branches.values()))
        candidate = next(c for c in context["candidates"] if c["candidate"] == old_candidate)
        self.assertEqual(candidate["branch"], old)
        self.assertTrue(candidate["stale"])
        with self.assertRaisesRegex(GateError, "Branch does not belong"):
            self.submit(branch=old)

    def test_context_reads_legacy_setup_event_without_rewriting_history_or_schema(self):
        legacy = {"revision": self.rev, "reviewer": "initial-human-maintainer", "reason": "Initial supplied specification"}
        self.ctl.db.execute("UPDATE events SET kind=?,payload=? WHERE seq=1", ("premise-revised", json.dumps(legacy)))
        self.ctl.db.commit()
        schema = [tuple(r) for r in self.ctl.db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name")]
        events = [tuple(r) for r in self.ctl.db.execute("SELECT * FROM events ORDER BY seq")]
        self.ctl.close()
        self.ctl = Controller(self.root / "state")
        context = self.ctl.agent_request({"operation": "read_context"})
        self.assertEqual(context["revision"], self.rev)
        self.assertEqual(context["branches"], [])
        self.assertEqual([tuple(r) for r in self.ctl.db.execute("SELECT * FROM events ORDER BY seq")], events)
        self.assertEqual([tuple(r) for r in self.ctl.db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name")], schema)

    def test_candidate_filename_cannot_escape(self):
        for filename in ("../escape.lean", "/tmp/escape.lean", "bad-name.lean", "Candidate.py"):
            with self.subTest(filename=filename), self.assertRaises(GateError):
                self.submit(filename=filename)

    def test_packet_cycles_missing_dependencies_and_context_rejected(self):
        cases = [[item("a", deps=["b"])], [item("a", deps=["b"]), item("b", deps=["a"])], [item("a"), item("a")]]
        missing_context = item("a")
        del missing_context["context"]
        cases.append([missing_context])
        for inventory in cases:
            with self.assertRaises(GateError):
                packet_items({"items": inventory})

    def test_review_packet_metadata_cannot_override_trusted_inventory(self):
        packet = copy.deepcopy(self.packet)
        packet["items"][0]["argument"] = "Different human-reviewed purpose"
        cid = self.submit(packet=packet)
        self.approve(cid)
        self.ctl.verify(cid)
        with self.assertRaisesRegex(GateError, "inventory"):
            self.ctl.promote(cid)

    def test_event_log_retains_rejected_route(self):
        cid = self.submit()
        self.ctl.review(cid, "target", "rejected", "simulated human", "Target mismatch")
        self.ctl.revise(self.baseline, "simulated human", "Reset scope")
        event = self.ctl.db.execute("SELECT payload FROM events WHERE kind='human-review'").fetchone()[0]
        self.assertEqual(json.loads(event)["reason"], "Target mismatch")


if __name__ == "__main__":
    unittest.main()
