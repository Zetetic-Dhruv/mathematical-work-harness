import Mathlib.Data.Set.Basic
import Mathlib.Tactic

/-!
# A reconstruction of a path-consistency repair

This file compares two predicates on the same complete binary trees. The first
deliberately forgets earlier branch labels. The second retains them by restricting
the concept class. All results are provisional mathematical material for review;
successful compilation does not constitute human approval.
-/

namespace Reconstruction

universe u

set_option pp.all true

/-- Complete binary trees, with depth recorded in the type. -/
inductive Tree (X : Type u) : Nat → Type u where
  | leaf : Tree X 0
  | branch : {n : Nat} → X → Tree X n → Tree X n → Tree X (n + 1)

/-- Exactly the two constant Boolean functions, on an arbitrary domain. -/
def constants (X : Type u) : Set (X → Bool) :=
  {c | c = (fun _ => true) ∨ c = (fun _ => false)}

/-- Deliberately defective: recursive calls keep the unrestricted class. -/
def BranchWise {X : Type u} {n : Nat} (C : Set (X → Bool)) : Tree X n → Prop
  | .leaf => True
  | .branch x l r =>
      (∃ c ∈ C, c x = true ∧ BranchWise C l) ∧
      (∃ c ∈ C, c x = false ∧ BranchWise C r)

/-- Each recursive class remembers every label already selected on that path.
The empty path requires a concept witness, including when the depth is zero. -/
def PathConsistent {X : Type u} {n : Nat} (C : Set (X → Bool)) : Tree X n → Prop
  | .leaf => C.Nonempty
  | .branch x l r =>
      (∃ c ∈ C, c x = true) ∧ (∃ c ∈ C, c x = false) ∧
      PathConsistent {c ∈ C | c x = true} l ∧
      PathConsistent {c ∈ C | c x = false} r

/-- The same input is used at every internal node. -/
def repeated {X : Type u} (x : X) : (n : Nat) → Tree X n
  | 0 => .leaf
  | n + 1 => .branch x (repeated x n) (repeated x n)

/-- The defect admits every depth, despite having only two constant concepts. -/
theorem branchWise_repeated {X : Type u} (x : X) (n : Nat) :
    BranchWise (constants X) (repeated x n) := by
  induction n with
  | zero => trivial
  | succ n ih =>
      exact ⟨⟨fun _ => true, Or.inl rfl, rfl, ih⟩,
        ⟨fun _ => false, Or.inr rfl, rfl, ih⟩⟩

/-- A uniform-label class cannot realize both outgoing labels at any root. -/
theorem uniform_no_positive {X : Type u} {C : Set (X → Bool)} (b : Bool)
    (uniform : ∀ c ∈ C, ∀ x, c x = b) (n : Nat) (t : Tree X (n + 1)) :
    ¬ PathConsistent C t := by
  cases t with
  | branch x l r =>
      intro h
      cases b with
      | false =>
          obtain ⟨c, hc, hx⟩ := h.1
          have incompatible : (true : Bool) = false := by
            trace_state
            exact hx.symm.trans (uniform c hc x)
          cases incompatible
      | true =>
          obtain ⟨c, hc, hx⟩ := h.2.1
          have incompatible : (false : Bool) = true := by
            trace_state
            exact hx.symm.trans (uniform c hc x)
          cases incompatible

/-- After selecting the true edge, every remaining constant is true everywhere. -/
theorem true_restriction_uniform {X : Type u} (x : X) :
    ∀ c ∈ ({c ∈ constants X | c x = true} : Set (X → Bool)), ∀ y, c y = true := by
  intro c hc y
  rcases hc.1 with htrue | hfalse
  · simp only [htrue]
  · have incompatible : (false : Bool) = true := by
      trace_state
      simpa only [hfalse] using hc.2
    cases incompatible

/-- No complete path-consistently shattered tree for the constants exceeds depth one.
The proof does not enumerate a finite domain or assume one. -/
theorem constants_depth_le_one {X : Type u} {n : Nat} (t : Tree X n)
    (shattered : PathConsistent (constants X) t) : n ≤ 1 := by
  cases t with
  | leaf => exact Nat.zero_le 1
  | @branch n x l r =>
      cases n with
      | zero => exact Nat.le_refl 1
      | succ k =>
          have left_shattered :
              PathConsistent {c ∈ constants X | c x = true} l := by
            trace_state
            exact shattered.2.2.1
          have obstruction :
              ¬ PathConsistent {c ∈ constants X | c x = true} l := by
            trace_state
            exact uniform_no_positive true (true_restriction_uniform x) k l
          exact False.elim (obstruction left_shattered)

/-- Any chosen input gives a depth-one tree with both constant witnesses. -/
theorem constants_depth_one {X : Type u} (x : X) :
    PathConsistent (constants X) (Tree.branch x Tree.leaf Tree.leaf) := by
  exact ⟨⟨fun _ => true, Or.inl rfl, rfl⟩,
    ⟨fun _ => false, Or.inr rfl, rfl⟩,
    ⟨fun _ => true, Or.inl rfl, rfl⟩,
    ⟨fun _ => false, Or.inr rfl, rfl⟩⟩

/-- For every nonempty domain, depth one is attained and bounds every shattered depth. -/
theorem constants_exact_depth {X : Type u} [Nonempty X] :
    (∃ t : Tree X 1, PathConsistent (constants X) t) ∧
    (∀ (n : Nat) (t : Tree X n), PathConsistent (constants X) t → n ≤ 1) := by
  obtain ⟨x⟩ := ‹Nonempty X›
  exact ⟨⟨Tree.branch x Tree.leaf Tree.leaf, constants_depth_one x⟩,
    fun _ t ht => constants_depth_le_one t ht⟩

/-- A concrete repeated-input tree exposes the mismatch at depth two, on any inhabited domain. -/
theorem repeated_counterexample {X : Type u} (x : X) :
    BranchWise (constants X) (repeated x 2) ∧
    ¬ PathConsistent (constants X) (repeated x 2) := by
  constructor
  · exact branchWise_repeated x 2
  · intro h
    have impossible_bound : 2 ≤ 1 := by
      trace_state
      exact constants_depth_le_one (repeated x 2) h
    omega

-- This command block is part of the trusted, source-bound review evidence.
#print Tree
#print constants
#print BranchWise
#print BranchWise._f
#print PathConsistent
#print PathConsistent._f
#print repeated
#print repeated._f
#print branchWise_repeated
#print uniform_no_positive
#print true_restriction_uniform
#print constants_depth_le_one
#print constants_depth_one
#print constants_exact_depth
#print repeated_counterexample
#print axioms branchWise_repeated
#print axioms uniform_no_positive
#print axioms true_restriction_uniform
#print axioms constants_depth_le_one
#print axioms constants_depth_one
#print axioms constants_exact_depth
#print axioms repeated_counterexample

end Reconstruction
