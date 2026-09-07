# Specification for human-maintained mathematical work

Version 1.0. This document specifies responsibilities and acceptance conditions. The accompanying software implements a bounded instance of this specification; its supported Lean fragment and validation results are reported separately.

## Mathematical responsibility

A mathematical investigation has a question, a representation of that question, and arguments intended to answer it. Definitions, type constructions, hypotheses, and intermediate claims participate in that representation. A checked proof establishes its encoded proposition. The researcher remains responsible for judging whether that proposition and its argument serve the investigation.

Two maintainers work concurrently:

* The researcher maintains the mathematical specification and argument. This includes supplying constructions and proofs, reviewing proposals, repairing definitions, and deciding how a discovery changes the investigation.
* The proof agent maintains formal derivations and their evidence. It may search, construct examples, propose arguments or revisions, and explore questions before the researcher has answered them.

These are responsibilities, not a prohibition on collaboration across them. The researcher can write Lean; the agent can suggest mathematics. Authority to accept a mathematical commitment remains with the researcher.

## Unit of review

Every newly introduced definition, type construction, hypothesis, and internal `have` is a review item. Witnesses, case assumptions, local definitions, and instances are included when introduced into the argument. Intermediate items cannot be hidden behind approval of the final theorem.

A review packet contains:

1. The item and its enclosing argument, with exact source locations.
2. The complete local judgment, including variable types, implicit parameters, instances, local hypotheses, and values of local definitions.
3. The elaborated proposition or type. Definitions and constructions include their bodies, not only their signatures.
4. Its mathematical purpose, dependencies, and intended range of application.
5. Its revision and the precise proposed change, with consequences for dependent arguments.

The researcher reviews each item; several items may be displayed together. A question answered about one item is not blanket approval of the packet. Acceptance of the implementation plan is not approval of future mathematical statements.

Imported libraries and permitted foundational axioms form an explicit baseline. Reviewing a task does not entail rereviewing every definition in those libraries. New axioms cannot be smuggled into that baseline through a proof proposal. An assumption local to a theorem remains visible in its statement and is not represented as a proved result.

## Provisional work and accepted use

Exploration may use provisional definitions and provisional lemmas inside a separate workspace. Such work is valuable even when its specification is subsequently rejected.

Mathematical review and formal verification have independent states. Review may be pending, approved, rejected, or stale. Verification may be unchecked, passed, or failed. Acceptance is computed from these states and the dependency relation; it is not a model-generated judgment.

A result enters accepted use only when:

* The researcher has approved every mathematical commitment needed by its argument at the current revision.
* The exact approved statement has a checked proof under the approved baseline, or the approved definition or construction has been successfully elaborated and checked as appropriate.
* Every result used as a dependency is accepted. Local hypotheses are explicitly scoped and reviewed rather than falsely counted as independently proved facts.
* Required review coverage is complete for the supported fragment. Unsupported or unmapped constructions remain provisional.
* No prohibited proof placeholder or unapproved axiom occurs in the checked result.
* The revision checked by the verifier is still current immediately before acceptance.

A proof may pass while its mathematical review remains pending. Conversely, approving an argument does not supply a missing formal proof. Neither event substitutes for the other.

## Revision and discovery

Every proposed deviation names the original obligation and its current status. Three responses are distinguished:

| Kind of change | Mathematical consequence | Required treatment |
|---|---|---|
| New construction for the same claim | The target stays fixed; the argument and intermediate obligations change. | Review the new commitments and recheck affected proofs. |
| Definition, representation, or hypothesis repair | The encoded question changes, potentially changing what the result answers. | Compare the old and proposed statements, explain the repair, and reopen affected approvals. |
| New mathematical question | The investigation acquires an additional obligation. | Preserve the original target and create a separately scoped question linked to its origin. |

A proposal asks targeted questions about the actual choices: which assumption is intended, whether a restriction is acceptable, which construction should be pursued, or whether a newly exposed question belongs in the active investigation. Several questions may be pending together.

While the researcher considers them, the agent may explore alternatives provisionally. Each branch records its hypothetical assumptions and base revision. Unaffected approved work can continue. Silence, elapsed time, and successful compilation are not answers to a question.

After a decision, reconcile candidate results against the adopted specification. Evidence from a previous revision stays attached to that revision. It cannot be relabeled as evidence for the new one. Rejected routes, counterexamples, and the reasons for rejection remain available to subsequent sessions.

The bounded implementation may conservatively reopen an entire affected task when its premise or baseline changes. This sacrifices some review efficiency without permitting stale acceptance; independent tasks need not stop.

## Generality and reuse

Track the intended target, the proposition actually established, its assumptions, and its quantified scope separately. A correct local result may be accepted at its own scope while a broader obligation remains open.

Four outcomes require different treatment:

* An invalid inference requires argument or proof repair.
* A valid special-case result requires an additional argument before it answers a broader target.
* A missing bridge requires a named source, destination, and precise outstanding mathematical obligation.
* A proof that answers its target may still have unestablished reuse beyond that target.

A generalization obligation is closed by the required parameterized proof or a checked transport argument. Reuse is demonstrated only for identified applications. Tests on selected instances provide evidence about those instances; they do not prove an unrestricted statement.

Finite enumeration is a legitimate proof method for finite claims. Its presence is not a failure criterion. Proof length, branching, tactic traces, and similar measurements describe a derivation; they do not automatically measure its mathematical generality or quality. Necessary assumptions cannot be removed indiscriminately as a purported robustness test.

Do not collapse compliance, validity, completion, and generalization into one score or assume that their historical audit labels form a logical implication chain.

## Minimum operational behavior

The human-facing interface records authoritative mathematical decisions. Agent-facing tools can request review, submit candidates, and invoke fixed checks; they cannot approve their own statements, manufacture verifier results, or close an unrelated obligation.

Pending questions, branch assumptions, revisions, decisions, and verification evidence survive restart. A fresh agent session receives the current specification revision and its approval states together with the relevant open questions and rejected routes.

Model or tool failure leaves the mathematical states intact. Exhausted inference quota stops inference; it does not authorize a paid fallback, automatic approval, or a change to the claim. The absence of a human decision remains visible as pending work.

Worked examples may use scripted researcher decisions to illustrate the procedure; those decisions must be labelled and kept separate from actual mathematical review. A reconstructed historical example likewise remains distinct from newly generated model output. The implementation was developed after the two historical projects.
