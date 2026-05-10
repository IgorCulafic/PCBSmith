# PCBSmith KiCad Part Resolution Plan

## Steps

1. Add KiCad binding metadata to catalog entries.
2. Add a resolver that checks bindings against KiCad library index manifests.
3. Add a CLI command for resolving one catalog entry.
4. Filter known generated-symbol mismatch warnings out of PCBSmith ERC report files.
5. Add focused unit and CLI tests.
6. Add a resolver smoke test to `tools/dev_check.py`.
