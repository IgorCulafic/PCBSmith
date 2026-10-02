# Native no-connect binding repair — 2026-10-01

The first double-sided laser coupon exposed a native integration defect before routing.
KiCad XML exports explicit no-connect terminals as synthetic one-terminal nets, but
the KiCad 10.0.6 schematic-parity check expects their PCB pads to be netless in this
case. The original three registration pads had zero ERC/geometric DRC findings and
three parity warnings. Naming three isolated nets cleared parity but introduced three
isolated-label ERC warnings. Both candidates and checks remain retained; neither is
an accepted board. Adding pin-type metadata alone did not resolve the original issue.

The shared netlist parser now omits only native terminals explicitly marked
`no_connect` on an isolated synthetic net. It never infers no-connect from the net
name alone, and rejects no-connect pins on connected nets. The native source-intent
owner still checks discarded terminals for declared pin intent and duplicates.
Existing canonical netlist schemas are unchanged.

The shared board revision owner now supports `unrouted_no_connects` with an exact
`no_connect_terminals` list. Its planner re-exports the source schematic, checks the
explicit native pin intent and exact old synthetic net, and removes only that binding.
It rejects existing routed copper/zones, locked or ambiguous pads and unrelated nets.
All pad geometry and object identities are preserved; native ERC/DRC/parity, protected
object checks, replay and explicit apply remain mandatory. No manual routing,
generator invocation, disabled electrical rule or positive inspection is introduced.

Evidence is retained under `outputs/laser-next-tests-2026-10-01`:

- `registration-platform-scope.json` and `registration-platform-completion.json`:
  separate 1,800-second platform allowance, exact duration and code hashes.
- `registration-final-tests-2.xml`: final focused regression, including real KiCad
  generation, source-preserving local repair, replay and apply. The native fixture
  checks ERC, DRC and parity, not just mocked outcomes.
- `registration-final-tests.xml`: eight failed negative tests from a missing closing
  parenthesis in their synthetic fixture; corrected results remain separately retained.
- `workflow-audit-registration-final.json`: 213 classified callers, no findings.
- Ruff and mypy pass for the changed shared owners. No accepted historical archive
  or job ledger was rewritten. Synthetic/diagnostic fixtures are not deliveries.

The user explicitly approved one finite recovery of the same coupon job after the
diagnostic checkpoint, limited to the three registration-pad bindings, automatic
routing and exports. Production recovery and handover require their own evidence;
this platform report grants neither. Original preparation, correction and timing
history remain intact.
