# Explicit pre-route placement recovery — September 28

The user approved rotating LaserStep3 D1 by 180 degrees and moving R3 from board-local (23,58) to (23,46). The source remains the retained unrouted board after its successful label correction. The first partial automatic route remains failed and immutable.

The shared revision owner now accepts `unrouted_placement`: requested component poses and annotations only, with no existing tracks, arcs, vias or zones. The source-bound reviewed vector remains mandatory. Native ERC, DRC violations and schematic parity remain mandatory; only pre-route opens are deferred. Candidate replay, preservation checks and native checks on apply remain in force.

The shared job owner accepts an explicit, hashed `placement_followup_plan` after successful annotation-only edits. It binds the existing board, dependency hashes and exact poses before preparation. The same root, original clock, correction count, attempts and continuation history remain retained. A previous placement edit cannot qualify. Each preparation/edit operation remains limited to one attempt in the new scope. The automatic router retains its lifetime two-attempt limit and requires the exact failed token and changed effective inputs.

This is an explicitly authorized new placement scope, not a reset or automatic retry. No manual routing or jumper insertion support was added. Future use requires its own explicit authorization and resolved-blocker evidence.

Focused unit checks cover successful candidate/replay/apply preservation, stale or altered plans/sources/requests, previous placement rejection, existing copper rejection, and no duplicate pose operation. Synthetic native substitutes in unit tests are not KiCad qualification. Real board checks are retained with the subsequent board attempt. Initial fixture errors and the discovered duplicate-history validation failure are preserved alongside the corrected run under `outputs/placement-recovery-platform-2026-09-28`.

Final focused tests, Ruff, mypy and the static producer audit pass. The audit still contains 213 classified entries and zero issues. This does not claim a complete repository test run or board acceptance.
