"""Revisioned argument review; no model-callable approval or evidence import.

This bounded controller trusts its configured verifier and human CLI. It is not
an OS security boundary against arbitrary programs running as the same user.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import signal
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

MODEL = "labs-leanstral-1-5"
MAX_SOURCE = 1_000_000
MAX_QUESTIONS = 16
MAX_BRANCHES = 4


class GateError(Exception):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def new_id(prefix):
    return prefix + "-" + uuid.uuid4().hex[:16]


def packet_items(packet):
    items = packet.get("items", packet.get("review_items"))
    if not isinstance(items, list) or not items:
        raise GateError("A nonempty review-item inventory is required")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise GateError("Each review item requires a string id")
        if item["id"] in seen or not item["id"]:
            raise GateError("Review item IDs must be unique and nonempty")
        seen.add(item["id"])
        for field in ("kind", "source", "context", "statement", "argument"):
            if field not in item:
                raise GateError("Missing review field: " + field)
        if item.get("scope") not in ("local", "general"):
            raise GateError("Every item requires explicit local/general scope")
        if not isinstance(item.get("dependencies"), list):
            raise GateError("Every item requires explicit dependencies")
        if any(not isinstance(dep, str) for dep in item["dependencies"]):
            raise GateError("Dependency IDs must be strings")
    graph = {i["id"]: i["dependencies"] for i in items}
    visiting, done = set(), set()
    def visit(node):
        if node not in graph:
            raise GateError("Dependency absent from packet: " + node)
        if node in visiting:
            raise GateError("Cyclic argument dependencies")
        if node in done:
            return
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        done.add(node)
    for node in graph:
        visit(node)
    return items


class Controller:
    def __init__(self, state):
        self.root = Path(state).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.root / "state.sqlite", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,baseline TEXT NOT NULL,sha TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,revision TEXT NOT NULL,source TEXT NOT NULL,source_sha TEXT NOT NULL,packet TEXT NOT NULL,packet_sha TEXT NOT NULL,branch TEXT,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS reviews(candidate TEXT,item TEXT,packet_sha TEXT,decision TEXT,reviewer TEXT,reason TEXT,created REAL,PRIMARY KEY(candidate,item,packet_sha));
        CREATE TABLE IF NOT EXISTS verifications(id TEXT PRIMARY KEY,candidate TEXT,revision TEXT,source_sha TEXT,packet_sha TEXT,result TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS acceptances(candidate TEXT,scope TEXT,revision TEXT,verification TEXT,created REAL,PRIMARY KEY(candidate,scope));
        CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY,batch TEXT,revision TEXT,payload TEXT,answer TEXT,reviewer TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS branches(id TEXT PRIMARY KEY,revision TEXT,questions TEXT,hypotheses TEXT,path TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,payload TEXT,created REAL);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def event(self, kind, payload):
        self.db.execute("INSERT INTO events(kind,payload,created) VALUES(?,?,?)", (kind, encoded(payload), time.time()))

    def meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            raise GateError("State is not initialized: " + key)
        return json.loads(row[0])

    def put_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, encoded(value)))

    def current(self):
        return self.meta("revision")

    def fresh(self, revision):
        if revision != self.current():
            raise GateError("Stale revision; rebase and review against the current premise")

    def revision(self, revision=None):
        row = self.db.execute("SELECT * FROM revisions WHERE id=?", (revision or self.current(),)).fetchone()
        if row is None:
            raise GateError("Unknown revision")
        path = Path(row["baseline"])
        if digest(path.read_bytes()) != row["sha"]:
            raise GateError("Baseline snapshot changed on disk")
        self.check_runtime_inputs(json.loads(path.read_text()))
        return row

    def check_runtime_inputs(self, baseline):
        """Recheck declared trusted project inputs, not an entire .olean closure."""
        config = self.meta("verifier")
        project = Path(config["workdir"])
        for item in baseline.get("runtime_inputs", []):
            relative = Path(item["path"])
            path = (project / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(project):
                raise GateError("Baseline runtime input must stay inside configured project")
            if not path.is_file() or digest(path.read_bytes()) != item["sha256"]:
                raise GateError("Trusted runtime input changed: " + str(relative))
        mathlib = baseline.get("runtime_mathlib_revision")
        if mathlib:
            path = project / ".lake" / "packages" / "mathlib"
            run = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True, timeout=10)
            if run.returncode or run.stdout.strip() != mathlib:
                raise GateError("Trusted Mathlib revision changed")

    def initialize(self, baseline, verifier, workdir, python=sys.executable):
        if self.db.execute("SELECT 1 FROM meta WHERE key='revision'").fetchone():
            raise GateError("Already initialized; use revise")
        verifier = Path(verifier).resolve(strict=True)
        config = {"path": str(verifier), "sha256": digest(verifier.read_bytes()), "python": str(Path(python).resolve(strict=True)), "workdir": str(Path(workdir).resolve(strict=True))}
        with self.transaction():
            self.put_meta("verifier", config)
            self.put_meta("model", MODEL)
        return self._install_revision(baseline, "specification-initialized", {
            "actor": "controller-setup",
            "reason": "Initial supplied specification loaded; no mathematical review performed",
            "human_approval": "not_performed",
        })

    def revise(self, baseline, reviewer, reason):
        if not reviewer or not reason:
            raise GateError("Revision requires human attribution and reason")
        return self._install_revision(baseline, "premise-revised", {
            "reviewer": reviewer, "reason": reason, "previous_acceptances": "stale",
        })

    def _install_revision(self, baseline, event_kind, attribution):
        """Load a source-bound specification without creating item approvals."""
        baseline = Path(baseline).resolve(strict=True)
        data = baseline.read_bytes()
        parsed = json.loads(data)
        packet_items(parsed)
        self.check_runtime_inputs(parsed)
        # Explicit baseline manifest is authoritative. Include toolchain/import
        # fingerprints in it; never infer that a filename pins dependencies.
        revision = new_id("rev")
        directory = self.root / "revisions" / revision
        directory.mkdir(parents=True)
        target = directory / "review.json"
        target.write_bytes(data)
        target.chmod(0o400)
        with self.transaction():
            self.db.execute("INSERT INTO revisions VALUES(?,?,?,?)", (revision, str(target), digest(data), time.time()))
            self.put_meta("revision", revision)
            self.event(event_kind, {"revision": revision, "baseline_sha256": digest(data), **attribution})
        return {"revision": revision, "baseline_sha256": digest(data)}

    def submit(self, source, packet, revision, filename="Candidate.lean", branch=None):
        self.fresh(revision)
        items = packet_items(packet)
        if not isinstance(source, str) or len(source.encode()) > MAX_SOURCE:
            raise GateError("Candidate must be bounded text")
        # Model-supplied labels such as human_approval/open_obligations are not
        # authority. Keep only the mathematical inventory and a derived digest.
        packet = {"items": items, "source_sha256": digest(source)}
        if Path(filename).name != filename or not filename.endswith(".lean") or not filename[:-5].replace("_", "").isalnum():
            raise GateError("Candidate filename must be a simple Lean filename")
        if branch:
            row = self.db.execute("SELECT revision FROM branches WHERE id=?", (branch,)).fetchone()
            if row is None or row[0] != revision:
                raise GateError("Branch does not belong to this revision")
        cid = new_id("candidate")
        directory = self.root / "candidates" / cid
        directory.mkdir(parents=True)
        path = directory / filename
        path.write_text(source)
        path.chmod(0o400)
        ph = digest(encoded(packet))
        with self.transaction():
            self.fresh(revision)
            self.db.execute("INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?)", (cid, revision, str(path), digest(source), encoded(packet), ph, branch, time.time()))
            self.event("candidate-submitted", {"candidate": cid, "revision": revision, "source_sha256": digest(source), "packet_sha256": ph, "branch": branch})
        return self.candidate_status(cid)

    def candidate(self, cid):
        row = self.db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise GateError("Unknown candidate")
        if digest(Path(row["source"]).read_bytes()) != row["source_sha"]:
            raise GateError("Candidate artifact changed on disk")
        return row

    def review(self, cid, item_id, decision, reviewer, reason):
        if decision not in ("approved", "rejected") or not reviewer or not reason:
            raise GateError("Explicit decision, reviewer and reason are required")
        with self.transaction():
            candidate = self.candidate(cid)
            self.fresh(candidate["revision"])
            items = packet_items(json.loads(candidate["packet"]))
            if item_id not in {i["id"] for i in items}:
                raise GateError("Unknown review item")
            self.db.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?,?,?,?)", (cid, item_id, candidate["packet_sha"], decision, reviewer, reason, time.time()))
            self.db.execute("DELETE FROM acceptances WHERE candidate=?", (cid,))
            self.event("human-review", {"candidate": cid, "item": item_id, "packet_sha256": candidate["packet_sha"], "decision": decision, "reviewer": reviewer, "reason": reason})
        return self.candidate_status(cid)

    def verify(self, cid, timeout=120):
        candidate = self.candidate(cid)
        self.fresh(candidate["revision"])
        baseline = self.revision(candidate["revision"])
        config = self.meta("verifier")
        if digest(Path(config["path"]).read_bytes()) != config["sha256"]:
            raise GateError("Trusted verifier changed; initialize a separately reviewed state")
        # Only a fixed trusted command is executed. Agent strings are file content,
        # never shell fragments or executable/argv selections.
        with tempfile.TemporaryDirectory(prefix="mathai-check-") as tmp:
            output = Path(tmp) / "result.json"
            argv = [config["python"], config["path"], "--candidate", candidate["source"], "--baseline", baseline["baseline"], "--output", str(output)]
            env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
            try:
                # The configured project is explicit, never a public hardcoded path.
                env["DESIGN_LAB_ROOT"] = config["workdir"]
                run = subprocess.Popen(argv, cwd=config["workdir"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
                try:
                    stdout, stderr = run.communicate(timeout=timeout)
                except BaseException:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(run.pid, signal.SIGKILL)
                    run.communicate()
                    raise
                result = read_json(output) if output.is_file() else {"status": "failed", "coverage": "incomplete", "error": "Verifier produced no JSON result"}
                if not isinstance(result, dict):
                    raise ValueError("Verifier result must be an object")
                result["exit_code"] = run.returncode
                if run.returncode != 0:
                    result["status"] = "failed"
                result["stdout"] = stdout[-16000:]
                result["stderr"] = stderr[-16000:]
            except subprocess.TimeoutExpired:
                result = {"status": "failed", "coverage": "incomplete", "error": "Verifier timeout"}
            except (ValueError, OSError) as exc:
                result = {"status": "failed", "coverage": "incomplete", "error": str(exc)}
        vid = new_id("verification")
        with self.transaction():
            self.candidate(cid)
            self.revision(candidate["revision"])
            # A completed old check remains historical evidence, never current.
            result["stale"] = candidate["revision"] != self.current()
            self.db.execute("INSERT INTO verifications VALUES(?,?,?,?,?,?,?)", (vid, cid, candidate["revision"], candidate["source_sha"], candidate["packet_sha"], encoded(result), time.time()))
            self.db.execute("DELETE FROM acceptances WHERE candidate=?", (cid,))
            self.event("verification-finished", {"verification": vid, "candidate": cid, "status": result.get("status"), "stale": result["stale"]})
        return {"verification": vid, "result": result}

    def promotion_gate(self, candidate, scope):
        self.fresh(candidate["revision"])
        self.revision(candidate["revision"])
        items = packet_items(json.loads(candidate["packet"]))
        inventory = {i["id"]: i for i in items}
        required = {i["id"] for i in items if i["scope"] == scope}
        if not required:
            raise GateError("No explicit " + scope + " claim in this packet")
        if scope == "general" and not any(i["scope"] == "general" and i["kind"] in ("generalization", "transport", "reuse") for i in items):
            raise GateError("General acceptance requires an explicit generalization/transport/reuse obligation")
        def close(node):
            for dep in inventory[node]["dependencies"]:
                if dep not in required:
                    required.add(dep)
                    close(dep)
        for item in list(required):
            close(item)
        approvals = {row["item"]: row["decision"] for row in self.db.execute("SELECT item,decision FROM reviews WHERE candidate=? AND packet_sha=?", (candidate["id"], candidate["packet_sha"]))}
        pending = sorted(i for i in required if approvals.get(i) != "approved")
        if pending:
            raise GateError("Unapproved dependency closure: " + ", ".join(pending))
        row = self.db.execute("SELECT * FROM verifications WHERE candidate=? ORDER BY created DESC,id DESC LIMIT 1", (candidate["id"],)).fetchone()
        if row is None:
            raise GateError("No trusted verification")
        if any(row[key] != candidate[key] for key in ("revision", "source_sha", "packet_sha")):
            raise GateError("Verification does not match the exact candidate revision")
        result = json.loads(row["result"])
        if result.get("status") != "passed" or result.get("coverage") != "complete" or result.get("stale"):
            raise GateError("Latest verification is failed, stale or incompletely covered")
        if result.get("review_items") != items:
            raise GateError("Verifier inventory does not match the human-review packet")
        if not required.issubset(set(result.get("verified_item_ids", []))):
            raise GateError("Verification does not establish all requested obligations")
        config = self.meta("verifier")
        if digest(Path(config["path"]).read_bytes()) != config["sha256"]:
            raise GateError("Verifier changed after verification")
        return row["id"]

    def promote(self, cid, scope="local"):
        if scope not in ("local", "general"):
            raise GateError("Unknown acceptance scope")
        with self.transaction():
            candidate = self.candidate(cid)
            vid = self.promotion_gate(candidate, scope)
            # BEGIN IMMEDIATE holds the revision stable through publication.
            self.db.execute("INSERT OR REPLACE INTO acceptances VALUES(?,?,?,?,?)", (cid, scope, candidate["revision"], vid, time.time()))
            self.event("accepted", {"candidate": cid, "scope": scope, "revision": candidate["revision"], "verification": vid})
        return self.candidate_status(cid)

    def queue_questions(self, questions, revision):
        self.fresh(revision)
        if not isinstance(questions, list) or not 1 <= len(questions) <= MAX_QUESTIONS:
            raise GateError("Submit between 1 and 16 targeted questions")
        batch, ids = new_id("batch"), []
        with self.transaction():
            self.fresh(revision)
            for question in questions:
                if not isinstance(question, dict) or not question.get("prompt") or not question.get("consequence"):
                    raise GateError("Each question needs a prompt and consequence")
                qid = new_id("question")
                ids.append(qid)
                self.db.execute("INSERT INTO questions VALUES(?,?,?,?,?,?,?)", (qid, batch, revision, encoded(question), None, None, time.time()))
            self.event("questions-queued", {"batch": batch, "questions": ids, "revision": revision})
        return {"batch": batch, "question_ids": ids, "status": "pending", "accepted_use": False}

    def answer(self, qid, answer, reviewer):
        if not answer or not reviewer:
            raise GateError("Answer and human attribution are required")
        with self.transaction():
            row = self.db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
            if row is None:
                raise GateError("Unknown question")
            self.fresh(row["revision"])
            self.db.execute("UPDATE questions SET answer=?,reviewer=? WHERE id=?", (answer, reviewer, qid))
            self.event("question-answered", {"question": qid, "answer": answer, "reviewer": reviewer, "grants_approval": False})
        return {"question": qid, "status": "answered", "grants_approval": False}

    def branch(self, question_ids, hypotheses, revision):
        self.fresh(revision)
        if not isinstance(hypotheses, list) or not hypotheses or not all(isinstance(h, str) for h in hypotheses):
            raise GateError("Exploration needs an explicit hypothetical assumption list")
        for qid in question_ids:
            row = self.db.execute("SELECT revision FROM questions WHERE id=?", (qid,)).fetchone()
            if row is None or row[0] != revision:
                raise GateError("Question is not from this revision")
        bid = new_id("branch")
        directory = self.root / "provisional" / bid
        directory.mkdir(parents=True)
        baseline = self.revision(revision)
        shutil.copyfile(baseline["baseline"], directory / "baseline.json")
        (directory / "baseline.json").chmod(0o400)
        (directory / "assumptions.json").write_text(encoded({"revision": revision, "questions": question_ids, "hypotheses": hypotheses, "accepted_use": False}))
        with self.transaction():
            self.fresh(revision)
            if self.db.execute("SELECT COUNT(*) FROM branches WHERE revision=?", (revision,)).fetchone()[0] >= MAX_BRANCHES:
                raise GateError("This revision reached its four-branch exploration cap")
            self.db.execute("INSERT INTO branches VALUES(?,?,?,?,?,?)", (bid, revision, encoded(question_ids), encoded(hypotheses), str(directory), time.time()))
            self.event("provisional-branch-created", {"branch": bid, "revision": revision, "questions": question_ids, "hypotheses": hypotheses})
        return {"branch": bid, "revision": revision, "accepted_use": False}

    def candidate_status(self, cid):
        row = self.candidate(cid)
        reviews = {r["item"]: r["decision"] for r in self.db.execute("SELECT item,decision FROM reviews WHERE candidate=? AND packet_sha=?", (cid, row["packet_sha"]))}
        scopes = {"local": False, "general": False}
        for accepted in self.db.execute("SELECT scope,revision FROM acceptances WHERE candidate=?", (cid,)):
            if accepted["revision"] == self.current():
                try:
                    self.promotion_gate(row, accepted["scope"])
                    scopes[accepted["scope"]] = True
                except GateError:
                    pass
        return {"candidate": cid, "revision": row["revision"], "branch": row["branch"], "stale": row["revision"] != self.current(), "source_sha256": row["source_sha"], "packet_sha256": row["packet_sha"], "reviews": reviews, "accepted": scopes, "generalization": "accepted" if scopes["general"] else "unresolved"}

    def context(self):
        revision = self.revision()
        # Recover provisional assumptions from the existing database, including
        # stale branches. Visibility never grants accepted use of a branch.
        branches = [{
            "branch": row["id"], "revision": row["revision"],
            "question_ids": json.loads(row["questions"]),
            "hypotheses": json.loads(row["hypotheses"]),
            "stale": row["revision"] != revision["id"], "accepted_use": False,
        } for row in self.db.execute("SELECT * FROM branches ORDER BY created,id")]
        return {"revision": revision["id"], "model": MODEL, "specification": read_json(revision["baseline"]), "questions": [{**dict(r), "payload": json.loads(r["payload"]), "stale": r["revision"] != revision["id"]} for r in self.db.execute("SELECT * FROM questions ORDER BY created")], "branches": branches, "candidates": [self.candidate_status(r[0]) for r in self.db.execute("SELECT id FROM candidates ORDER BY created")], "limits": {"max_provisional_branches_per_revision": MAX_BRANCHES, "max_questions_per_batch": MAX_QUESTIONS}, "maintainers": {"argument": "human", "proof": "agent"}}

    def interactive_review(self, cid, reviewer, read=input, write=print):
        """Human-only item-by-item terminal interface; never auto-approves."""
        candidate = self.candidate(cid)
        self.fresh(candidate["revision"])
        write("Candidate " + cid + " | revision " + candidate["revision"] + " | packet " + candidate["packet_sha"])
        write("Items below are proposals. Each decision is separate; checking and promotion remain separate actions.")
        for item in packet_items(json.loads(candidate["packet"])):
            write(json.dumps(item, indent=2, ensure_ascii=False))
            decision = read("[a]pprove, [r]eject, [s]kip, [q]uit: ").strip().lower()
            if decision == "q":
                break
            if decision not in ("a", "r"):
                continue
            reason = read("Mathematical reason (required): ").strip()
            if not reason:
                write("No decision recorded without a reason.")
                continue
            self.review(cid, item["id"], "approved" if decision == "a" else "rejected", reviewer, reason)
        return self.candidate_status(cid)

    def agent_request(self, request):
        # Deliberate closed dispatch: no approve, answer, revise, promote,
        # verifier installation, external paths, raw commands or evidence input.
        op = request.get("operation")
        if op == "read_context":
            return self.context()
        if op == "queue_questions":
            return self.queue_questions(request["questions"], request["revision"])
        if op == "create_branch":
            return self.branch(request.get("question_ids", []), request["hypotheses"], request["revision"])
        if op == "submit_candidate":
            return self.submit(request["source"], request["packet"], request["revision"], request.get("filename", "Candidate.lean"), request.get("branch"))
        if op == "check_candidate":
            return self.verify(request["candidate"])
        raise GateError("Operation is not available to the proof agent")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="Private persistent controller directory")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--baseline", required=True)
    init.add_argument("--verifier", required=True)
    init.add_argument("--workdir", default=str(Path.cwd()))
    init.add_argument("--python", default=sys.executable)
    revise = sub.add_parser("revise")
    revise.add_argument("--baseline", required=True)
    revise.add_argument("--reviewer", required=True)
    revise.add_argument("--reason", required=True)
    sub.add_parser("status")
    sub.add_parser("agent-rpc")
    packet = sub.add_parser("packet")
    packet.add_argument("candidate")
    submit = sub.add_parser("submit")
    submit.add_argument("--candidate", required=True)
    submit.add_argument("--packet", required=True)
    submit.add_argument("--revision", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("candidate")
    verify.add_argument("--timeout", type=int, default=120)
    review = sub.add_parser("review")
    review.add_argument("candidate")
    review.add_argument("item")
    review.add_argument("--decision", required=True, choices=["approved", "rejected"])
    review.add_argument("--reviewer", required=True)
    review.add_argument("--reason", required=True)
    interactive = sub.add_parser("interactive-review")
    interactive.add_argument("candidate")
    interactive.add_argument("--reviewer", required=True)
    promote = sub.add_parser("promote")
    promote.add_argument("candidate")
    promote.add_argument("--scope", choices=["local", "general"], default="local")
    answer = sub.add_parser("answer")
    answer.add_argument("question")
    answer.add_argument("--text", required=True)
    answer.add_argument("--reviewer", required=True)
    sub.add_parser("events")
    args = parser.parse_args(argv)
    def terminated(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminated)
    ctl = Controller(args.state)
    try:
        if args.command == "init":
            result = ctl.initialize(args.baseline, args.verifier, args.workdir, args.python)
        elif args.command == "revise":
            result = ctl.revise(args.baseline, args.reviewer, args.reason)
        elif args.command == "status":
            result = ctl.context()
        elif args.command == "packet":
            row = ctl.candidate(args.candidate)
            result = {"candidate": row["id"], "packet_sha256": row["packet_sha"], "proposal_packet": json.loads(row["packet"]), "authoritative_status": ctl.candidate_status(row["id"]), "baseline_open_obligations": read_json(ctl.revision()["baseline"]).get("open_obligations", []), "source": Path(row["source"]).read_text()}
        elif args.command == "submit":
            source = Path(args.candidate)
            result = ctl.submit(source.read_text(), read_json(args.packet), args.revision, source.name)
        elif args.command == "verify":
            result = ctl.verify(args.candidate, args.timeout)
        elif args.command == "review":
            result = ctl.review(args.candidate, args.item, args.decision, args.reviewer, args.reason)
        elif args.command == "interactive-review":
            result = ctl.interactive_review(args.candidate, args.reviewer)
        elif args.command == "promote":
            result = ctl.promote(args.candidate, args.scope)
        elif args.command == "answer":
            result = ctl.answer(args.question, args.text, args.reviewer)
        elif args.command == "events":
            result = [{**dict(row), "payload": json.loads(row["payload"])} for row in ctl.db.execute("SELECT * FROM events ORDER BY seq")]
        else:
            raw = sys.stdin.read(MAX_SOURCE * 3 + 1)
            if len(raw) > MAX_SOURCE * 3:
                raise GateError("Agent request too large")
            result = ctl.agent_request(json.loads(raw))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (GateError, ValueError, KeyError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    finally:
        ctl.close()


if __name__ == "__main__":
    raise SystemExit(main())
