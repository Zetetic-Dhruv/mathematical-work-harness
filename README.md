# Mathematical work: review and proof construction

The researcher maintains the mathematical specification; a proof agent develops
formal derivations. This adaptation over the open-source DeepSeek Harness supplies
a revisioned controller, a terminal review interface, a restricted tool plugin,
and a Lean reconstruction of the Littlestone path-consistency repair. The
controller operations are provider-independent. An optional pinned adapter
connects them to a DeepSeek Harness session using Leanstral.

## Scope

The supplied seven Lean proofs check in the recorded environment. The review
packet contains 19 items, including six explicit internal claims. The 46 passing
deterministic tests comprise 31 controller, eight review-adapter, and seven plugin
tests. Test fixtures are distinct from mathematical review.

The local alpha interaction used an existing agent session through the
plugin-to-controller interface. It did not use the optional Leanstral adapter or
make a model-provider request through this package. Checking the supplied
reconstruction neither generated a new proof nor approved its mathematical items.

The checker executes only source matching a trusted prepared packet. Preparing a
new packet is a maintainer operation: inspect the source before running it. New
agent proposals can be stored provisionally, but require that preparation before
execution. The syntax index is deliberately narrow and does not extract every
mathematical commitment from arbitrary Lean. There is no operating-system sandbox
for malicious Lean code. Library binaries and the local machine are trusted.

## Environment

Run all commands from the selected Lean project root. The controller, plugin, and
Lean checks described here used Lean 4.31.0, Mathlib revision
`fabf563a7c95a166b8d7b6efca11c8b4dc9d911f`, Python 3.12.14, and Node 24.19.0.
The archive intentionally includes neither Lean toolchains nor library binaries.
Install those separately and ensure `lake env lean --version` selects the intended
toolchain. The Python controller and deterministic tests use only the standard
library. Inference additionally requires the exact versions in
`harness/requirements.txt`; `harness/runtime-pin.json` records their sources.

Set these paths locally. `MATHAI` is the extracted package root (containing
`harness` and `demo`); `LEAN_PROJECT` is the existing pinned Lean project.

```sh
export MATHAI=/absolute/path/to/mathematical-work
export LEAN_PROJECT=/absolute/path/to/lean-project
cd "$LEAN_PROJECT"
python3 -m unittest discover -s "$MATHAI/harness/tests" -p 'test_*.py'
python3 -m unittest discover -s "$MATHAI/demo" -p 'test_*.py'
node --test "$MATHAI/harness/tests/plugin.test.mjs"
```

The included `demo/review.json` records the original project's input hashes. When
the selected project inputs differ, prepare a fresh packet after inspecting the
supplied source. This records the local project inputs and grants no mathematical
approval:

```sh
export MATHAI_RUN=$(mktemp -d)
python3 "$MATHAI/demo/prepare_review.py" \
  --candidate "$MATHAI/demo/Littlestone.lean" \
  --index "$MATHAI/demo/review-index.json" \
  --project-root "$LEAN_PROJECT" --output "$MATHAI_RUN/review.json"
python3 "$MATHAI/harness/dry_run.py" \
  --project-root "$LEAN_PROJECT" --baseline "$MATHAI_RUN/review.json" \
  --state "$MATHAI_RUN/state" --output "$MATHAI_RUN/reconstruction.json"
python3 "$MATHAI/demo/rehearse.py" \
  --project-root "$LEAN_PROJECT" --baseline "$MATHAI_RUN/review.json" \
  --output "$MATHAI_RUN/rehearsal.json"
```

The dry run submits five questions and a provisional branch, checks the known
proof, verifies that acceptance is blocked, and reopens the persistent record.
The separate rehearsal checks real Lean evidence with explicitly synthetic
approval decisions in a disposable state. Its output is not a human review.
Neither script makes model calls or closes the transport and broader-class
obligations. Changing project inputs requires a fresh packet and renewed review;
the complete compiled library dependency closure is not attested by these hashes.

## Human review

The dry-run report supplies the candidate and revision identifiers. Read
`demo/review-notes.md`, inspect the complete packet, then record each decision:

```sh
python3 "$MATHAI/harness/controller.py" --state "$MATHAI_RUN/state" status
python3 "$MATHAI/harness/controller.py" --state "$MATHAI_RUN/state" \
  packet CANDIDATE_ID
python3 "$MATHAI/harness/controller.py" --state "$MATHAI_RUN/state" \
  interactive-review CANDIDATE_ID --reviewer 'mathematical maintainer'
python3 "$MATHAI/harness/controller.py" --state "$MATHAI_RUN/state" \
  promote CANDIDATE_ID --scope local
```

The interactive interface presents each item and requires a reason for approval
or rejection. Skipping an item leaves it pending. A general result needs its
explicit generalization item reviewed and promoted with `--scope general`.
Question answers do not approve items. `revise --baseline PATH --reviewer NAME
--reason TEXT` changes the active specification and invalidates earlier
acceptances. `events` displays the retained history. Independent tasks use
separate state directories. Research obligations beyond the accepted statement
remain in the specification until a separately reviewed revision resolves them.

Human commands are local maintainer operations. The model has only read-context,
question, provisional-branch, candidate-submission, and fixed-check tools; it
cannot approve, answer as the maintainer, revise the baseline, or promote results.

Initialization records a `specification-initialized` setup event, explicitly
without mathematical review. Subsequent revision events retain the supplied
reviewer attribution; neither operation creates item approvals.

The agent's `read_context` operation returns persisted branch assumptions, linked
question IDs, branch revisions, and candidate-to-branch links. Stale branches
remain visible for recovery but cannot supply a current candidate. Visibility of
a provisional branch never grants accepted use. These records can be used by an
existing agent through the controller's closed `agent-rpc` interface without
installing or calling a model provider.

## Optional DeepSeek Harness and Leanstral session

Create a private virtual environment and install the pinned requirements. No
global runtime configuration is changed. Offline startup checks the actual
runtime tool registry and controller connection without an API request:

```sh
python3 -m venv "$MATHAI_RUN/venv"
"$MATHAI_RUN/venv/bin/pip" install -r "$MATHAI/harness/requirements.txt"
"$MATHAI_RUN/venv/bin/python" "$MATHAI/harness/adapter.py" \
  --state "$MATHAI_RUN/state" --dsh-home "$MATHAI_RUN/runtime" \
  --workdir "$LEAN_PROJECT"
```

Live inference is opt-in. Load `MISTRAL_API_KEY` from private local storage, verify
free access to `labs-leanstral-1-5` on the account, and append `--live
--free-api-confirmed --max-requests 8 --max-seconds 180`. The runtime uses that
single model and has no paid fallback or auxiliary model. Provider errors stop
the run; retries are disabled. Local request-limit tests do not establish
provider-side quota behavior. Keep runtime state and conversation logs
private. Never place credentials in the package or a review packet.

Model sessions are tied to a revision and optional provisional branch. Supply
`--branch BRANCH_ID` to explore its explicit assumptions, and reuse a session ID
only while that binding remains current. Human review can proceed in a separate
terminal while the worker explores.

## License

The new source is distributed under Apache-2.0, matching the surrounding project.
The runtime, model, Lean, and Mathlib are separately obtained dependencies subject
to their own terms. No model was trained for this package.
