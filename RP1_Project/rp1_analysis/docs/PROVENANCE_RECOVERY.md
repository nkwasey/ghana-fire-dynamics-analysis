# SaTScan integration state and recovery

An accepted `RESULTS_VALIDATED` / `INTEGRATED` secondary run has two complete
validated external result families, derived sources matching the raw results,
consistent registries and status, no governed `EXTERNAL_RESULTS_REQUIRED.txt`
marker, and no active integration transition. Inspection, ordinary reuse and
closeout use the same lifecycle checks. Inspection is read-only.

## New integration

The writer preflights the exact governed marker paths before publishing new
authorities. It acquires one run-local transition directory, snapshots existing
governed authority and marker bytes and timestamps, and stages all replacement
payloads. It does not change raw external result files or unrelated markers.

The active directory is
`04_secondary_concentration/.satscan_integration_transaction/`. Its journal and
verified backups make a stopped transition visible and recoverable. Payloads use
short indexed names to avoid duplicating long Windows run paths. Publication,
marker cleanup and terminal-status writing belong to the same transition; the
terminal status is written last and the resulting sources are checked again.

The terminal commit is a same-parent directory rename to
`.satscan_integration_commit/`. The sealed directory retains the transition
receipt and backups. Its `READY_TO_COMMIT` journal describes the verified state
immediately before that atomic seal; placement under the commit name records
that the seal completed. The terminal seal completes the write. For a run without a commit
receipt, acceptance depends on the remaining validation checks.

Ordinary write or deletion failures restore the complete pre-transition governed
state. A failed rollback or interrupted process leaves the active directory in
place. Every acceptance route then fails with `recovery required`, including
when a terminal-status file was already written. Separate atomic file writes
alone are not treated as a multi-file commit.

## Recover a stopped unsealed transition

First ensure that the original integration process has stopped. Preserve a copy
and hashes of the affected run, including the hidden transition directory, in
the objective Workspace. Do not run recovery concurrently with integration.

From `RP1_Project/rp1_analysis` in the intended source environment:

```bash
python scripts/recover_satscan_integration.py --secondary-run-id example_sec
```

This explicit command verifies the journal identity, backup hashes and governed
target paths. It restores the pre-transition bytes, permissions and timestamps,
removes newly published authority files, and removes the active transition only
after rollback succeeds. It refuses unexpected edits to authoritative files or
missing/corrupt backup evidence. Such evidence must be preserved for review;
the command does not guess what an operator intended to change.

Before any restoration write, recovery validates the whole journal: recognized
fields and transaction state, a complete unique target set derived from the verified
pre-transition registry, mandatory boolean existence flags, typed metadata,
and every required backup and staged-payload hash. Empty/dropped/duplicate
entries, unknown material, unsafe filesystem nodes and malformed metadata fail
without changing the governed files or clearing the recovery evidence. After
restoration, every declared pre-state file/absence and its metadata is checked
before the active transition is removed. A restoration I/O or verification
failure keeps the transition available for a later verified retry.

An initial `PREPARING` journal has no published authority writes. It can be
cleared only while the recorded run and registry still describe the pending
state and any completed partial backups still match the current targets.
Relabelling a partly published transition as preparation is not a repair.

After `RP1_SATSCAN_RECOVERY=ROLLED_BACK`, inspect the pending run and retry normal
04-02 integration. The two complete external families are validated again.
If the transition journal itself is missing or malformed, preserve that tree and
prepare a new run from its governed inputs rather than deleting the active
directory merely to bypass the acceptance gate.

## Conflicts in sealed runs

A validated run containing pending markers is inconsistent. Inspection
reports the conflict and preserves files. Rollback applies only to an unsealed
transaction with verified backups.
Inspection also reads recorded completion state before classifying absent raw
results: `RESULTS_VALIDATED` with missing result families is a conflict, while a
genuine pending preparation may still report `EXTERNAL_RESULTS_REQUIRED`.

Preserve the original source/configuration snapshot, run and hashes. Record the
conflicting markers and a review decision in a separate Workspace reconciliation
record. A corrected execution should use a fresh run family generated from the
intended governed inputs, with genuine result families and new execution
evidence. Preserve copied result files and their input and engine attestations.
Reuse of a valid sealed run is idempotent.
