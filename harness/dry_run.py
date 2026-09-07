"""Reconstructed Lean demonstration; no model calls and no simulated approvals."""
import argparse
import json
from pathlib import Path

from controller import Controller, GateError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", required=True, help="Fresh private state directory")
    p.add_argument("--project-root", required=True)
    p.add_argument("--demo", default=str(Path(__file__).resolve().parents[1] / "demo"))
    p.add_argument("--baseline", help="Prepared packet for this trusted project; defaults to demo/review.json")
    p.add_argument("--output", help="Optional compact JSON report; private controller state is separate")
    a = p.parse_args()
    demo = Path(a.demo).resolve()
    ctl = Controller(a.state)
    try:
        baseline = Path(a.baseline).resolve() if a.baseline else demo / "review.json"
        rev = ctl.initialize(baseline, demo / "verify.py", a.project_root)["revision"]
        packet = json.loads(baseline.read_text())
        questions = ctl.queue_questions([
            {"prompt": prompt, "consequence": consequence}
            for prompt, consequence in zip(packet["questions"], [
                "A change of tree or branch convention requires renewed review of dependent arguments.",
                "Leaf nonemptiness controls whether the empty class has a witness at depth zero.",
                "Changing path consistency changes the definition and reopens its dependent proofs.",
                "Review all scoped hypotheses and intermediate claims before accepting the general result.",
                "The two-constant theorem leaves both transport and broader-class bounds open.",
            ], strict=True)
        ], rev)
        branch = ctl.branch(questions["question_ids"], ["Explore the cumulative restriction repair while mathematical review is pending"], rev)
        cid = ctl.submit((demo / "Littlestone.lean").read_text(), packet, rev, "Littlestone.lean", branch["branch"])["candidate"]
        verification = ctl.verify(cid)
        try:
            ctl.promote(cid)
        except GateError as error:
            blocked = "Unapproved" in str(error)
        else:
            blocked = False
        ctl.close()
        ctl = Controller(a.state)
        status = ctl.candidate_status(cid)
        context = ctl.context()
        report = {
            "kind": "reconstructed-example-offline-demonstration",
            "inference_calls": 0,
            "human_decisions_recorded": 0,
            "candidate": cid,
            "revision": rev,
            "source_sha256": status["source_sha256"],
            "review_items": len(packet["items"]),
            "verification": verification["result"]["status"],
            "coverage": verification["result"]["coverage"],
            "acceptance": status["accepted"],
            "pending_question_ids": questions["question_ids"],
            "provisional_branch": branch["branch"],
            "open_obligations": packet.get("open_obligations", []),
            "unreviewed_promotion_blocked": blocked,
            "restart_preserved_pending_questions": all(q["answer"] is None for q in context["questions"]) and len(context["questions"]) == 5,
        }
        serialized = json.dumps(report, indent=2) + "\n"
        if a.output:
            Path(a.output).write_text(serialized)
        print(serialized, end="")
        return 0 if verification["result"]["status"] == "passed" and blocked and report["restart_preserved_pending_questions"] else 1
    finally:
        ctl.close()


if __name__ == "__main__":
    raise SystemExit(main())
