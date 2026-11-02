# Gate evidence scope migration — shadow phase

This change is **diagnostic only**. It does not reduce the existing formal release checks or authorize cloud sending.

## What is available

- `release_service.status()` retains its original authoritative `decision`.
- `experience` groups visible blockers for a simpler user interface.
- `dependency_diagnostics` calculates proposed gate-specific fingerprints.
- `receipt_binding_shadow` reports G3/G5 receipts matching the current case/purpose/recipient tuple and whether old `bound_versions` match. It labels *possible migration candidates*, not verified reusable evidence.
- All diagnostic objects are explicitly marked non-authoritative. Never use them in gateway, grant issuance, or `authorize_dispatch`.

## Why G9 is not reused yet

The formal G9 isolation receipt currently binds the request hash and named G8 confirmation, as well as build, firewall, supply-chain and deployment evidence. A reusable deployment proof requires a **new signed and revocable contract**, plus a separate request-specific legal confirmation. A hash alone cannot establish either.

## Required before actual reuse

1. Define versioned receipt contracts for G3, G5, and deployment-level G9, including issuer, audience, purpose, target, validity period, revocation and evidence byte integrity.
2. Preserve case-specific G1/G2 and every-request G6/G7/G8/G10 checks where necessary.
3. Run shadow comparisons over an authorized synthetic fixture corpus; investigate each old/new mismatch.
4. Add mutation, expiry, revocation, cross-recipient, cross-purpose, key-rotation and replay regression tests.
5. Obtain legal and security sign-off before switching any authoritative verification path.
6. Never remove the product-wide `formal_dispatch=blocked` latch by migrating proof formats.

## Verification

Run `pytest -q tests/test_gate_experience.py tests/test_gate_evidence_scope.py`, then the full suite. These checks have not yet been executed in the connected GitHub environment.
