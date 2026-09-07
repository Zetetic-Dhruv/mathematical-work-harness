#!/usr/bin/env python3
"""Prepare a source-bound packet from TRUSTED source and an explicit manual index.

This maintainer-only operation executes Lean, so do not offer it as an agent tool
or run it on uninspected external source. It grants no human approval. Edit the
index when mathematical structure changes, inspect every proposed item, then use
the human review interface. Unsupported syntax stays provisional.
"""

import argparse
import json
import os
from pathlib import Path

from verify import check_runtime_inputs, enrich_items, run_lean, runtime_inputs, sha256, source_index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root", default=os.environ.get("DESIGN_LAB_ROOT"))
    args = parser.parse_args()
    if not args.project_root:
        parser.error("Set DESIGN_LAB_ROOT or --project-root")
    data = Path(args.candidate).read_bytes()
    index = json.loads(Path(args.index).read_text())
    inputs = runtime_inputs(args.project_root)
    items = source_index(data.decode(), index)
    messages = run_lean(data, args.project_root, index)
    check_runtime_inputs(args.project_root, inputs)
    packet = {"schema_version": 1, "source_sha256": sha256(data), "source_file": "Littlestone.lean",
              "coverage": "complete", "coverage_basis": "Source-bound manual index for the supported reconstruction fragment",
              "human_approval": "not_performed", "support_files": [], "index": index,
              "runtime_inputs": inputs, "runtime_mathlib_revision": index["mathlib_revision"],
              "items": enrich_items(items, messages, index), "open_obligations": index["open_obligations"],
              "questions": index["questions"], "messages": messages}
    Path(args.output).write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"prepared": args.output, "source_sha256": packet["source_sha256"],
                      "items": len(packet["items"]), "human_approval": "not_performed"}))


if __name__ == "__main__":
    main()
