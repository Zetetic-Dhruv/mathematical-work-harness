"""Real Lean checks with synthetic review decisions in a disposable test record.

This is a deterministic protocol rehearsal. It never records a researcher's
mathematical approval and never closes the two outstanding research obligations.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
from controller import Controller, GateError


def must_block(action, text):
    try:
        action()
    except GateError as error:
        if text not in str(error):
            raise AssertionError("Unexpected rejection: " + str(error)) from error
        return True
    raise AssertionError("Required acceptance boundary did not block")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", required=True)
    p.add_argument("--baseline")
    p.add_argument("--output")
    a = p.parse_args()
    demo = Path(__file__).resolve().parent
    baseline = Path(a.baseline).resolve() if a.baseline else demo / "review.json"
    packet = json.loads(baseline.read_text())
    source = (demo / "Littlestone.lean").read_text()
    checks = {}
    with tempfile.TemporaryDirectory(prefix="mathai-synthetic-review-") as temporary:
        state = Path(temporary) / "synthetic-test-state"
        ctl = Controller(state)
        try:
            rev = ctl.initialize(baseline, demo / "verify.py", a.project_root)["revision"]
            cid = ctl.submit(source, packet, rev, "Littlestone.lean")["candidate"]
            result = ctl.verify(cid)["result"]
            assert result["status"] == "passed", result.get("error", result.get("checks"))
            checks["real_lean_verification"] = True
            held = "constants_depth_le_one.have.2"
            for item in packet["items"]:
                if item["id"] != held:
                    ctl.review(cid, item["id"], "approved", "synthetic-test-input", "Protocol test only; no human mathematical review")
            checks["unreviewed_internal_have_blocks"] = must_block(lambda: ctl.promote(cid, "general"), held)
            ctl.review(cid, held, "approved", "synthetic-test-input", "Protocol test only; no human mathematical review")
            local = ctl.promote(cid, "local")
            checks["local_completion_does_not_promote_generality"] = local["accepted"]["local"] and not local["accepted"]["general"]
            general = ctl.promote(cid, "general")
            checks["explicit_general_result_can_be_promoted_in_test"] = general["accepted"]["general"]
            checks["broader_research_obligations_remain_open"] = all(o["status"] == "open" for o in ctl.context()["specification"]["open_obligations"])
            ctl.close()
            ctl = Controller(state)
            checks["restart_preserves_synthetic_decisions"] = ctl.candidate_status(cid)["accepted"]["general"]
            ctl.revise(baseline, "synthetic-test-input", "Test revision invalidation using the same known proof fixture")
            checks["superseded_verification_cannot_be_promoted"] = must_block(lambda: ctl.promote(cid, "general"), "Stale")
            checks["superseded_acceptance_is_revoked"] = not any(ctl.candidate_status(cid)["accepted"].values())
        finally:
            ctl.close()
    assert all(checks.values()), checks
    report = {"kind": "deterministic-protocol-rehearsal", "review_decisions": "synthetic-test-inputs-only", "human_mathematical_review": "not_performed", "inference_calls": 0, "source_sha256": packet["source_sha256"], "checks": checks}
    serialized = json.dumps(report, indent=2) + "\n"
    if a.output:
        Path(a.output).write_text(serialized)
    print(serialized, end="")


if __name__ == "__main__":
    main()
