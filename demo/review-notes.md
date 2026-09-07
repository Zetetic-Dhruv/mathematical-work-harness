# Mathematical review: path consistency

Status: provisional reconstruction. Nothing in this packet records human approval.

The domain is an arbitrary `X : Type u`. The class consists exactly of the constant true and constant false functions. Trees are complete binary trees whose two subtrees have the same depth. At a true branch the left child is followed; at a false branch the right child is followed.

The deliberately defective predicate keeps the original class at each recursive call. It therefore accepts the repeated-input tree at every natural-number depth. The repaired predicate restricts the class by each observed branch label. At a leaf it requires a remaining concept, rather than accepting an empty class.

The proposed general result has no finiteness, decidable-equality, or measurability assumption:

```
{X : Type u} [Nonempty X] :
  (∃ t : Tree X 1, PathConsistent (constants X) t) ∧
  (∀ (n : Nat) (t : Tree X n), PathConsistent (constants X) t → n ≤ 1)
```

The upper bound does not need nonemptiness; a supplied shattered tree suffices. Nonemptiness supplies the input for the depth-one witness. A separate theorem exhibits a repeated-input depth-two tree accepted by the defective predicate and rejected by the repaired one.

The upper-bound argument has two intermediate claims. First, after selecting the true root label, the remaining class contains only functions that are true everywhere. Second, a class with one fixed label everywhere cannot shatter a positive-depth tree, because either root label would contradict that fixed label. Applying this obstruction to the left subtree forces total depth at most one.

## Questions awaiting the mathematical maintainer

1. Do these complete, depth-indexed trees and Boolean branch directions express the intended objects?
2. Should the repaired leaf require a concept witness, thereby distinguishing an empty class from a nonempty class with no positive shattered depth?
3. Does restricting the class at every branch express the intended same-concept-per-path condition?
4. Are the arbitrary-domain upper bound, the nonempty-domain depth-one witness, and the six explicitly displayed local claims acceptable with their complete contexts?
5. Should the next research obligation connect this reconstruction to the project's dimension and mistake-bound statements, or investigate a different class? Neither extension is supplied or accepted by this packet.

The source, complete elaborated declaration bodies, and local contexts at each explicit `have` are supplied separately. Imported Lean/Mathlib infrastructure is a baseline to be approved. Compilation and axiom checks provide formal evidence, not approval of the mathematical question or its wider applicability.

## What remains open

The demonstrated arbitrary-domain theorem is complete at its stated scope. Transport to the original project's types and any broader finite-class bound are separate, open obligations. They cannot be closed by the two-constant-class result, by finite-instance tests, or by successful compilation of unrelated declarations.
