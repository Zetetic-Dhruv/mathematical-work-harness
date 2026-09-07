"""Pinned DeepSeek Harness SDK launcher; offline by default, no paid fallback."""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import threading
import uuid

from controller import Controller, GateError, MODEL, encoded

SDK_VERSION = "0.1.2rc1"
MAX_TOKENS = 4096

PERSONA = """You maintain formal proofs alongside a human who maintains the mathematical specification and argument. Call mathai_read_context first. Every new definition, type construction, hypothesis, witness, local definition, instance and internal have must be explicitly reviewable before accepted use. A passing check is not human approval. Preserve the original obligation when proposing repairs. Ask several targeted questions with consequences together; you may then create isolated provisional branches and explore explicit hypothetical assumptions while answers are pending. Neither silence nor a question answer approves a packet. Never claim local evidence establishes generality or reuse; list remaining transport and broader-target obligations. You have only the closed controller tools, no shell. Changed source is stored provisionally but not executed until a trusted maintainer prepares a source-bound review baseline. Never request or reveal API keys. No paid fallback is permitted."""


def composition(plugin):
    # The SDK-minimal tree is explicit and version-pinned. Disable every shell,
    # editor, process/filesystem execution producer and the DeepSeek adapter.
    disabled = ["persistent-bash", "persistent-pwsh", "str-replace-editor", "terminal-bash", "terminal-pwsh", "pty", "subprocess", "fs-local", "sandbox", "sandbox-policy", "deepseek-llm-api-extensions", "llm-deepseek"]
    patch = [{"id": name, "disabled": True} for name in disabled]
    patch += [{"id": "tools", "config": {"mode": "native"}}, {"id": "agent-loop", "config": {"agents": [], "maxParallelToolCalls": 1}}, {"id": "system-prompt", "config": {"includeHarnessIdentity": False, "includeRuntimeContext": False, "persona": PERSONA}}]
    patch.append({"insert": [
        {"id": "mathai-llm", "name": "@deepseek-ai/dsh-llm-pi-ai", "config": {"providers": {"mistral": {"apiKeyEnv": "MISTRAL_API_KEY", "retryPolicy": {"mode": "normal", "maxRetries": 0}, "models": [{"id": MODEL, "name": "Leanstral 1.5", "contextWindow": 32768, "maxTokens": MAX_TOKENS}]}}}},
        {"id": "mathai-tools", "name": str(plugin)},
    ]})
    return patch


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", required=True)
    p.add_argument("--dsh-home", required=True, help="Dedicated private Harness home, not ~/.dsh")
    p.add_argument("--workdir", required=True, help="Explicit runtime working directory")
    p.add_argument("--live", action="store_true", help="Authorize this bounded inference run (default: offline startup smoke)")
    p.add_argument("--free-api-confirmed", action="store_true", help="Human confirms this API key/account has free access to the exact model")
    p.add_argument("--max-requests", type=int, default=8)
    p.add_argument("--max-seconds", type=int, default=180)
    p.add_argument("--session-id", help="Reuse only to continue the same revision and branch")
    p.add_argument("--branch", help="Existing provisional branch id; gets an independent session by default")
    p.add_argument("--prompt", default="Inspect the current specification and pending questions. Identify the next bounded proof or question; keep unreviewed work provisional.")
    args = p.parse_args(argv)
    if not 1 <= args.max_requests <= 32 or not 1 <= args.max_seconds <= 1800:
        p.error("Bound requests to 1..32 and wall time to 1..1800 seconds")
    if args.live and (not args.free_api_confirmed or not os.environ.get("MISTRAL_API_KEY")):
        p.error("Live execution requires MISTRAL_API_KEY and explicit --free-api-confirmed; no paid fallback")
    for distribution in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin"):
        if version(distribution) != SDK_VERSION:
            p.error(distribution + " must be pinned to " + SDK_VERSION)
    from deepseek_harness import DeepSeekHarness
    workdir = Path(args.workdir).resolve(strict=True)
    home = Path(args.dsh_home).resolve()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    ctl = Controller(args.state)
    try:
        context = ctl.context()
        revision = context["revision"]
        prompt = args.prompt
        if args.branch:
            branch = ctl.db.execute("SELECT * FROM branches WHERE id=?", (args.branch,)).fetchone()
            if branch is None or branch["revision"] != revision:
                raise GateError("Branch is absent or stale")
            prompt = "PROVISIONAL EXPLORATION ONLY. Branch " + args.branch + ", hypothetical assumptions: " + branch["hypotheses"] + "\n" + prompt
        session = args.session_id or "proof-" + revision + "-" + (args.branch or "main") + "-" + uuid.uuid4().hex[:8]
        binding_key = "session-binding:" + session
        binding = {"revision": revision, "branch": args.branch}
        existing = ctl.db.execute("SELECT value FROM meta WHERE key=?", (binding_key,)).fetchone()
        if existing and json.loads(existing[0]) != binding:
            raise GateError("Session belongs to a different revision or branch; use a fresh session")
        with ctl.transaction():
            ctl.put_meta(binding_key, binding)
            ctl.event("model-run-requested" if args.live else "offline-smoke-requested", {"session": session, "revision": revision, "branch": args.branch, "model": MODEL, "max_requests": args.max_requests, "max_seconds": args.max_seconds, "free_api_confirmed": args.free_api_confirmed})
        patch = home / "mathai.patch.json"
        patch.write_text(json.dumps(composition(Path(__file__).with_name("plugin") / "index.mjs"), indent=2))
        report = home / "offline-smoke.json"
        # Runtime inherits env by SDK contract; clear every other credential and
        # disable telemetry. We never put the Mistral key in a config/trace.
        env = {k: "" for k in os.environ if any(word in k.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")) and k != "MISTRAL_API_KEY"}
        env.update(MATHAI_PYTHON=sys.executable, MATHAI_CONTROLLER=str(Path(__file__).with_name("controller.py")), MATHAI_STATE=str(ctl.root), MATHAI_WORKDIR=str(workdir), MATHAI_MAX_REQUESTS=str(args.max_requests), MATHAI_OFFLINE="0" if args.live else "1", MATHAI_SELFTEST_OUTPUT="" if args.live else str(report), DSH_TELEMETRY_DISABLED="1", DSH_TOOLS_MODE="native")
        if not args.live:
            env["MISTRAL_API_KEY"] = ""
        harness = DeepSeekHarness(dsh_home=str(home), profile="sdk-minimal", patches=(str(patch),), cwd=str(workdir), runtime_cwd=str(workdir), provider="mistral", model=MODEL, max_tokens=MAX_TOKENS, env=env, initialize_timeout_seconds=30, request_timeout_seconds=args.max_seconds)
        timed_out = threading.Event()
        def stop():
            timed_out.set()
            harness.close()
        timer = threading.Timer(args.max_seconds, stop)
        timer.daemon = True
        try:
            timer.start()
            with harness:
                if args.live:
                    result = harness.run(prompt, session_id=session)
                    output = {"session": session, "finish_reason": result.finish_reason, "final_response": result.final_response, "revision": revision, "timed_out": timed_out.is_set(), "acceptance": "Human review and trusted promotion remain separate"}
                else:
                    output = json.loads(report.read_text())
                    expected = sorted("mathai_" + operation for operation in ("read_context", "queue_questions", "create_branch", "submit_candidate", "check_candidate"))
                    if output["tool_names"] != expected:
                        raise GateError("Unexpected model-facing tools in runtime composition")
                    output["sdk_version"] = SDK_VERSION
                    output["live_api_verified"] = False
            with ctl.transaction():
                ctl.event("model-run-finished" if args.live else "offline-smoke-finished", output)
            print(json.dumps(output, indent=2))
            return 0
        finally:
            timer.cancel()
            harness.close()
    finally:
        ctl.close()


if __name__ == "__main__":
    raise SystemExit(main())
