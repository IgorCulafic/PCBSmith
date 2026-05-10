# PCBSmith AI Proposal Bundle Plan

## Steps

1. Add a proposal bundle service that validates candidate plans before staging.
2. Copy the source PCBSmith project into a new output folder.
3. Apply the candidate plan only to the staged copy.
4. Run the existing KiCad review bundle from the staged copy.
5. Add a CLI command and focused tests.
6. Add the proposal bundle to the dev-check smoke path.
