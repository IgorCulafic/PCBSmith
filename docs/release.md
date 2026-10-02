# Release procedure

## Software
1. Use the frozen complete environment and run tools/verify.py --profile deep
   --output NEW_DIAGNOSTICS_DIRECTORY. Read every gate result, native opt-in and
   skip; a partial diagnostic run is not the full release gate.
2. Build locally with uv build --out-dir NEW_ARCHIVE_DIRECTORY. Inspect both
   archives with tools/check_distribution.py and retain its entry lists and hashes.
   Inspect an installed wheel outside the checkout for CLI help, core project
   operations, bundled assets and GUI startup. Optional full KiCad libraries are
   required for board-specific operations, not for help.
3. Review intended source changes, lockfile/license notices, package version and
   tests. Bind the final archive hashes to the reviewed source revision/working-tree
   manifest. Rebuild if source or packaged documentation changed.
4. Select exact public files and obtain the applicable release decision before
   pushing/uploading/publishing. This implementation performed no remote release.

The allowlist excludes papers, experiments, native output boards, model weights,
private reference books and machine configuration. This does not by itself classify
every source comment or README sentence for public disclosure. Review release content.

## Board/assembly
A clean enabled-rule ERC/DRC result is one input. Retain exact native inputs and
configuration, nonmutating process receipts, routing completeness, read-back/netlist
equivalence, measured visual subjects, model suitability, manufacturing identities,
Gerber/drill/BOM/POS producer lineage and semantic validation. Replay production
readiness/release at packaging time. Independent CAM comparison, approved part
packages/pinout, process capability and actual assembly remain separate obligations.

A package marked blocked must retain its blockers. A software test asserting an
approval does not authorize fabrication. Required human, fabricator and assembler
approvals bind the exact package; any artifact change invalidates them.

## Current release gaps
Native Windows/mixed-DPI/assistive technology testing, remote CI provisioning,
independent CAM checks, selected hardware/firmware and physical measurements remain
unverified. DR7 needs two real new-board proofs. W10/Montenegro and accepted R005/R006
retain the boundaries in [current state](current-state.md).
