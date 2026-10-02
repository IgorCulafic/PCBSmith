Local AI assets go here: models, LoRAs, generated RAG indexes, and KoboldCPP files.

Large model artifacts are ignored by git.

Copy `local-ai-config.example.json` to the ignored `local-ai-config.json` for
machine settings, or use `PCBSMITH_LOCAL_AI_*` environment variables. Keep API
keys in the environment. The machine configuration is not a release asset.

The small `kicad_footprints` and `kicad_symbols` collections are required
runtime data. Their source and license notices accompany software builds;
model weights, LoRAs, indexes, papers and private caches do not.
