# Explicit recovery after a pre-native concept stop

User authorized the repair on 2026-09-12 after approving CircleBlink's presented layout. The job had a completed stop diagnostic and no native attempts. Ordinary continuation could only recover later stages with retained preparation, so it could not start the first candidate.

`ContinuationRequest.pre_native_recovery` now binds a `PreNativeLayoutApproval` file and its SHA-256. The approval names the current explicit authorization and hash-matching SVG, PNG and structured JSON inputs. Eligibility requires an unchanged stopped predecessor, the completed original diagnostic, no prior continuation, zero attempts/corrections and no native schematic/PCB anywhere under the job root. The resolution sources and all existing root/path/evidence checks remain mandatory.

The request declares independent finite evaluation/execution caps with the existing verification reserve. It must include native-preparation, predesign-prepare, predesign-approve and placement; optional routing/local repair operations are explicitly listed. Every operation still needs the contained worker and normal production checks, can run only once, and a failed operation enters the diagnostic. No correction cycles, automatic renewal, new root or reset is granted. This does not turn a user layout approval into engineering or manufacturing acceptance.

Validation: 147 affected runtime, timing, continuation, diagnostic and audit tests pass. Ruff passes for the owner and new test file; scoped mypy passes for the owner. The caller audit passes with 205 classified callers. Six previously unclassified metadata/supervisor writers in board_job.py were individually reviewed and classified; no native producer was added. Formatting and an existing overly narrow inferred list type were corrected in the same owner. No full repository-wide suite is claimed.

Evidence, original source/policy backups and exact diff are retained in outputs/pre-native-recovery-repair-2026-09-12. Platform work took place while CircleBlink stayed stopped; no timing was relabeled and no board was prepared during the repair. Live recovery is recorded separately on CircleBlink's original root.


## Exact missing-input and Windows interruption follow-ups

The first live native-preparation command encountered a missing spec before creating any native files. The shared owner now permits one exact-command retry only for that retained FileNotFoundError, after validating and pinning the corrected spec. It records the previous diagnostic, failed attempt, corrected input and stderr hashes without adding time or correction cycles. Invalid spec, changed retry input, existing native output, another operation or another failure remain blocked. The subsequent real native preparation and placement passed.

The later visual-render worker failed with WinError 5 replacing the shared ledger while rendering its front-low view. Its previous top/bottom/perspective views and native candidate remain retained. The exact lock holder is unknown. The existing atomic_write owner now retries the same flushed temporary file only for Windows access/sharing errors 5/32/33: at most four rename attempts with 0.05/0.1/0.2-second delays. It never deletes the destination to force replacement; persistent and unrelated failures propagate. This does not renew a job, reset a retry or approve a board.

Final scoped verification: 174 tests pass (zero failures/skips), covering the job/runtime/timing/continuation/diagnostic owners, file transactions and nine transient/persistent/unrelated rename failure cases. Ruff and scoped mypy pass; the caller audit passes with 205 classified callers. Exact successor diff and results are completion-complete.json, change-complete.patch, tests-atomic-complete.xml and audit-complete.json under the repair evidence directory. Earlier source-bound records remain unchanged. The live Windows interruption has not been rerun; its diagnostic is complete and the same CircleBlink root stays stopped.


## Routing input binding follow-up

The resumed CircleBlink placement review passed all 32 actual inspections. A subsequent routing preflight exposed a dependency lookup gap: production_routing checks detached geometry outside the project-local footprint scope. The exact custom footprints were retained locally but not visible to that lookup. The existing asset installer now retains those bytes under ai_assets/private-circleblink; the scoped worker uses PCBSMITH_PRIVATE_ASSET_ROOT. No CAD or routing rules changed.

The retry identity previously ignored this environment dependency. Its shared input_identity now includes the configured private asset root and hashes of native symbol/footprint/model files, so a changed actual dependency is visible without dummy edits to route inputs. A new regression verifies root introduction, file installation/change, ignored unrelated logs and unchanged identity on output-directory changes. The affected 106-test set, Ruff, scoped mypy and 205-caller audit passed; evidence is under outputs/circleblink-2026-09-12/routing-recovery-2026-09-12/asset-binding-*. The approved retry then entered the actual router; its separate search-budget result is retained, not relabeled as a library failure or success.
