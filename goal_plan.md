# Plan: Deliver correct HQH-539 resonant hash primitive per spec

## Goal kind
code-change

## Acceptance criteria
1. The resonant hash function, when called on a message (str/bytes) and optional salt, returns a 128-character lowercase hex string computed from SHA3-512 seed followed by exactly 539 applications of the canonical T3 map followed by SHA3-512 finalization.
2. The T3 step and full 539-iteration core are directly exercisable from a test or consumer on integer starting values and yield deterministic results (e.g., iterate_n_steps(10**18, 539) == 2 under canonical (4n+2)//3 T3).
3. Hash outputs are consistent across repeated invocations with identical inputs; variants for 512-bit and truncated 256-bit are available.
4. Real unit tests exercise the shipped hash and T3 functions directly (no mocks of the UUT, no pre-seeded state) and the captured run confirms correct observable outputs.

## Verification plan
1. gating: Create a minimal fresh consumer script in {SCRATCH} that imports the real hqh539 module via PYTHONPATH (no sys.path hacks) and calls the hash functions on representative inputs (empty message, "The universe counts in threes.", and a large integer case); run it at least twice; capture stdout/stderr and return values to {SCRATCH}/hqh539_run.log ; assert every run succeeds, outputs are 128 hex chars, identical between runs, and match frozen golden_vectors.json constants.
2. gating: Run the package's or added unit tests (pytest or unittest) that directly invoke T3 and the 539-step iteration on the real implementation starting from seed values; verify no errors and that iterate_n_steps(n, 539) is deterministic for n >= 10**18 (canonical oracle: 10**18 -> 2) and produce valid digests; capture full test log to {SCRATCH}/test_output.txt.
3. evidence: Inspect the source of the hash implementation to confirm correct T3 branches ((4*n+2)//3 for r==1) and uniform 539 iterations without extra per-step modulation; the core logic is present in shipped files.

## Non-goals
- Implementing or modifying FPGA RTL, bitstreams, or Vivado projects
- Adding Streamlit UI, web API, or KDF/SIG wrappers (beyond the basic hash)
- Generating or regenerating large test vector files
- Cryptanalysis, performance benchmarks, or security claims

## Assumed scope
hqh539.py implementations in Desktop/539_Engine/, Desktop/539Labs/python/, Downloads/; app.py in 539_Engine; test_vectors/ under 539Labs; spec documents (*.md, HQH539_spec.md); Python stdlib only (hashlib, no external crypto beyond what's already present).

## Implementation approach
Isolate the pure arithmetic (T3 map and iterate_n_steps function) in small, side-effect free units that take/return ints and can be unit-tested in isolation from any hashing or I/O. Compose the full hash from those units plus the two SHA3 calls. Ensure the public API functions are thin wrappers that the tests import and drive directly.

## Task checklist
- [x] Identify the primary hqh539 module to serve as canonical (prefer 539_Engine for demo focus or unify with spec)
- [x] Correct T3 definition to use +2 for residue 1 and ensure exactly 539 iterations are performed uniformly
- [x] Ensure Phase 3 finalization uses minimum-length bytes + salt (and domain sep if required by primary spec)
- [x] Add/ensure unit tests that import and call T3 + hqh_539 directly on real paths with fresh inputs
- [x] Execute the hash via fresh consumer import + direct calls at least twice; capture outputs and logs under {SCRATCH}
- [x] Run tests and confirm primary observables (correct length digests, termination property) match expectations

## Deviations
- AC2 updated: canonical `(4n+2)//3` yields `iterate_n_steps(10**18, 539) == 2`, not 1 (legacy `+1` test vectors were wrong).

## Risks / Contradictions
- Workspace contains divergent implementations (e.g. 539Labs uses fixed to_bytes(32) and incorrect +1 in T3; 539_Engine omits domain separator present in spec); the objective does not name the target file or which spec variant to follow, risking implementation/refutation mismatch.
- Test vectors on disk were generated from a buggy T3 (+1), so verification must either regenerate or use independent calculation for expected values.
- Some specs split into 18+521 loops (theoretical only), others force 539; both must yield identical results or the criterion for "correct" is ambiguous.