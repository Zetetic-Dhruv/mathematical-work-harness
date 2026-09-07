#!/usr/bin/env python3
"""Source-bound Lean evidence; never a mathematical approval or general Lean sandbox.

Only source whose bytes match a trusted prepared baseline is executed. Preparing
that baseline is a maintainer operation, not an agent tool. A baseline enumerates
whole declarations plus explicit local `have` arguments; Lean's JSON diagnostics
provide elaborated terms and exact contexts. Other Lean forms require a different
review adapter. This checker neither discovers hidden mathematical commitments nor
judges the adequacy of any assumption.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def runtime_inputs(project_root):
    project = Path(project_root).resolve()
    return [{"path": name, "sha256": sha256((project / name).read_bytes())}
            for name in ("lean-toolchain", "lake-manifest.json", "lakefile.lean")]


def check_runtime_inputs(project_root, expected):
    if runtime_inputs(project_root) != expected:
        raise ValueError("Design Lab project inputs changed; prepare a new baseline and reopen review")


def stripped_lines(source):
    """Reject nested comments/strings with commands; retain line count for indexing."""
    depth = 0
    cleaned = []
    for line in source.splitlines():
        row = []
        i = 0
        while i < len(line):
            if line[i:i + 2] == "/-":
                depth += 1
                i += 2
            elif depth and line[i:i + 2] == "-/":
                depth -= 1
                i += 2
            elif not depth and line[i:i + 2] == "--":
                break
            elif depth:
                i += 1
            else:
                row.append(line[i])
                i += 1
        cleaned.append("".join(row))
    if depth:
        raise ValueError("Unclosed comment")
    return cleaned


def source_index(source, spec):
    """Narrow lexical index, not a general Lean parser or a security sandbox."""
    lines = source.splitlines()
    clean = stripped_lines(source)
    joined = "\n".join(clean)
    if re.search(r'\b(sorry|admit|axiom|unsafe|run_tac|elab|macro|syntax|initialize|implemented_by|let|suffices|attribute|open|section|noncomputable|instance|class|structure|partial|mutual|scoped|infix|notation)\b|#eval|#check|"|`', joined):
        raise ValueError("Unsupported source form; remains provisional")
    imports = [line for line in clean if line.startswith("import ")]
    if imports != ["import Mathlib.Data.Set.Basic", "import Mathlib.Tactic"]:
        raise ValueError("The supported imported baseline changed")
    allowed_header = re.compile(
        r'^(import Mathlib\.(Data\.Set\.Basic|Tactic)|namespace Reconstruction|'
        r'universe u|end Reconstruction|set_option pp\.all true|'
        r'#print (?:axioms )?[A-Za-z_][A-Za-z0-9_.]*|'
        r'(?:inductive|def|theorem) [A-Za-z_][A-Za-z0-9_]*.*)$')
    for line in clean:
        if line.lstrip().startswith("#") and line[:1].isspace():
            raise ValueError("Indented commands are outside the supported fragment")
        if line and not line[0].isspace() and not allowed_header.fullmatch(line):
            raise ValueError("Unsupported top-level source form: " + line[:100])
    starts = [(i, re.match(r'^(inductive|def|theorem) (\w+)', s))
              for i, s in enumerate(clean) if re.match(r'^(inductive|def|theorem) (\w+)', s)]
    names = [m.group(2) for _, m in starts]
    if set(names) != set(spec["declarations"]) or len(names) != len(set(names)):
        raise ValueError("Declaration index differs from the supplied manual index")
    items = [{"id": "library", "kind": "baseline", "source": "Littlestone.lean:1-2",
              "context": "Lean and imported Mathlib infrastructure; no project theorem imported.",
              "statement": "import Mathlib.Data.Set.Basic\nimport Mathlib.Tactic",
              "argument": "Explicit imported baseline; its approval is a human decision.",
              "dependencies": [], "scope": "local", "coverage": "complete"}]
    observed_haves = set()
    for index, (start, match) in enumerate(starts):
        kind, name = match.groups()
        stop = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        for j in range(start + 1, stop):
            if clean[j].startswith(("#print", "set_option", "end ")):
                stop = j
                break
        while stop > start + 1 and not clean[stop - 1].strip():
            stop -= 1
        body = "\n".join(lines[start:stop])
        header = body.split(":=", 1)[0].rstrip()
        meta = spec["declarations"][name]
        item = dict(meta, id=name, source=f"Littlestone.lean:{start + 1}-{stop}",
                    source_span={"start": start + 1, "end": stop}, source_text=body,
                    context=header, statement=header, scope="general" if meta["kind"] == "generalization" else "local",
                    coverage="complete", declaration=name, lean_kind=kind)
        items.append(item)
        haves = [(j, re.search(r'\bhave\s+(\w+)\s*:(?!=)', clean[j])) for j in range(start, stop)
                 if re.search(r'\bhave\s+(\w+)\s*:(?!=)', clean[j])]
        if sum(len(re.findall(r'\bhave\b', clean[j])) for j in range(start, stop)) != len(haves):
            raise ValueError("Every local have must be explicit, named, and typed")
        for number, (j, hm) in enumerate(haves, 1):
            ident = f"{name}.have.{number}"
            observed_haves.add(ident)
            if ident not in spec["local_arguments"]:
                raise ValueError("Missing local argument index: " + ident)
            trace_line = next((k for k in range(j + 1, stop) if clean[k].strip() == "trace_state"), None)
            if trace_line is None or trace_line > j + 3:
                raise ValueError("Each supported have needs an immediate trace_state in its proof")
            local = dict(spec["local_arguments"][ident], id=ident, kind="have",
                         source=f"Littlestone.lean:{j + 1}", source_span={"start": j + 1, "end": trace_line + 1},
                         source_text="\n".join(lines[j:trace_line + 1]), context=header,
                         statement="\n".join(lines[j:trace_line]).split(":=", 1)[0].strip(),
                         scope="local", coverage="complete", declaration=name, local_name=hm.group(1),
                         trace_line=trace_line + 1)
            items.append(local)
    if observed_haves != set(spec["local_arguments"]):
        raise ValueError("Unused local arguments in manual index")
    ids = {x["id"] for x in items}
    for item in items:
        if any(d not in ids for d in item["dependencies"]):
            raise ValueError("Unknown dependency: " + item["id"])
    return items


def run_lean(data, project_root, expected):
    project = Path(project_root).resolve()
    if (project / "lean-toolchain").read_text().strip() != expected["toolchain"]:
        raise ValueError("Design Lab toolchain differs from the prepared baseline")
    clean_env = {k: os.environ[k] for k in ("HOME", "PATH", "ELAN_HOME", "LANG", "LC_ALL") if k in os.environ}
    mathlib = subprocess.run(["git", "-C", str(project / ".lake/packages/mathlib"), "rev-parse", "HEAD"],
                             env=clean_env, capture_output=True, text=True, check=True).stdout.strip()
    if mathlib != expected["mathlib_revision"]:
        raise ValueError("Mathlib revision differs from the prepared baseline")
    lake = shutil.which("lake")
    if not lake:
        raise ValueError("lake is not installed")
    with tempfile.TemporaryDirectory(prefix="mathai-lean-") as temporary:
        candidate = Path(temporary) / "Littlestone.lean"
        candidate.write_bytes(data)
        clean_env["TMPDIR"] = temporary
        result = subprocess.run([lake, "env", "lean", "--json", str(candidate)], cwd=project,
                                env=clean_env, capture_output=True, text=True, timeout=300)
        messages = []
        for line in result.stdout.splitlines():
            message = json.loads(line)
            message["fileName"] = "Littlestone.lean"
            messages.append(message)
        if result.returncode or any(m.get("severity") in ("error", "warning") for m in messages):
            raise ValueError("Lean check failed: " + json.dumps(messages, ensure_ascii=False)[:4000] + result.stderr[:1000])
    return messages


def enrich_items(items, messages, expected):
    enriched = []
    namespace = expected["namespace"]
    allowed = set(expected["allowed_axioms"])
    for original in items:
        item = dict(original)
        if item["id"] == "library":
            item["elaborated_form"] = expected["toolchain"] + "; Mathlib " + expected["mathlib_revision"]
        elif item["kind"] == "have":
            states = [m["data"] for m in messages if m.get("kind") == "trace" and m["pos"]["line"] == item["trace_line"]]
            if len(states) != 1:
                raise ValueError("Missing unique elaborated local context: " + item["id"])
            item["context"] = states[0]
            item["elaborated_form"] = states[0]
        else:
            name = namespace + "." + item["declaration"]
            printed = [m["data"] for m in messages if re.match(r'^(?:inductive|def|theorem) ' + re.escape(name) + r'(?:\.\{|\s)', m["data"])]
            if len(printed) != 1:
                raise ValueError("Missing unique elaborated declaration: " + name)
            item["elaborated_form"] = printed[0]
            item["context"] = printed[0].split(":=", 1)[0].strip()
            if item["lean_kind"] == "theorem":
                reports = [m["data"] for m in messages if m["data"].startswith("'" + name + "' ")]
                if len(reports) != 1:
                    raise ValueError("Missing axiom report: " + name)
                report = reports[0]
                axioms = [] if "does not depend on any axioms" in report else [a.strip() for a in report.split("[", 1)[1].rstrip("]").split(",")]
                normalized = {re.sub(r'\.\{.*\}$', '', axiom) for axiom in axioms}
                if not normalized.issubset(allowed):
                    raise ValueError("Unapproved axiom dependency: " + report)
                item["axiom_report"] = report
        enriched.append(item)
    return enriched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root", default=os.environ.get("DESIGN_LAB_ROOT"))
    args = parser.parse_args()
    result = {"schema_version": 1, "status": "failed", "coverage": "incomplete", "checks": [],
              "verified_item_ids": [], "review_items": [], "human_approval": "not_performed"}
    try:
        baseline = json.loads(Path(args.baseline).read_text())
        data = Path(args.candidate).read_bytes()
        digest = sha256(data)
        result["candidate_sha256"] = digest
        if digest != baseline["source_sha256"]:
            raise ValueError("Source differs from trusted review baseline; rejected BEFORE Lean execution")
        if not args.project_root:
            raise ValueError("Set DESIGN_LAB_ROOT or --project-root to the existing Design Lab project")
        spec = baseline["index"]
        check_runtime_inputs(args.project_root, baseline["runtime_inputs"])
        indexed = source_index(data.decode(), spec)
        messages = run_lean(data, args.project_root, spec)
        check_runtime_inputs(args.project_root, baseline["runtime_inputs"])
        items = enrich_items(indexed, messages, spec)
        if items != baseline["items"]:
            raise ValueError("Regenerated review items differ from the trusted source-bound baseline")
        result.update(status="passed", coverage="complete", review_items=items,
                      verified_item_ids=[i["id"] for i in items], checked_item_ids=[i["id"] for i in items], messages=messages,
                      checked_item_meaning="Theorem derivations checked; definitions and local arguments checked with their full stated scopes. No free-standing truth claim for a scoped hypothesis.",
                      runtime_inputs=baseline["runtime_inputs"], runtime_mathlib_revision=spec["mathlib_revision"],
                      open_obligations=baseline["open_obligations"],
                      coverage_basis="Exact source-bound manual index; elaborated declarations and local contexts. Not arbitrary semantic extraction.",
                      execution_boundary="Trusted source hash gate, fixed argv and project, sanitized environment. No adversarial OS sandbox claim.")
        result["checks"] = [{"name": name, "status": "passed", "detail": detail} for name, detail in (
            ("source_identity", digest), ("toolchain", spec["toolchain"]),
            ("mathlib", spec["mathlib_revision"]), ("elaboration", "All indexed declarations and local contexts regenerated"),
            ("axioms", "Every theorem has a checked report within the explicit allowed set"))]
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        result["checks"].append({"name": "verification", "status": "failed", "detail": str(exc)})
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    Path(args.output).write_text(serialized)
    print(serialized, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
