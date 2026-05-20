# Nexar Provider Adapter Plan

Date: 2026-05-20

## Objective

Add the first concrete evidence provider adapter for Nexar/Octopart supply data,
using mocked transport tests only. The adapter should translate a PCBSmith
evidence acquisition request into provider candidates that the existing
cache-writer layer can decide whether to download.

## Official API Notes

Nexar's support documentation describes:

- GraphQL as the API style.
- `https://api.nexar.com/graphql/` as the main API endpoint.
- `https://identity.nexar.com/connect/token` as the token endpoint.
- OAuth2 bearer-token authorization.
- Supply operations such as `supSearchMpn`.
- Datasheet-related fields on `SupPart`, including `documentCollections` and
  `bestDatasheet`, depending on plan access.

## Non-Goals

- No live API call in tests.
- No client ID/client secret handling in this slice.
- No OAuth token fetcher in this slice; inject a token provider instead.
- No API-key or credential storage.
- No datasheet download inside the provider.
- No extracted facts or support-status upgrade from provider metadata.

## Tasks

1. Add red tests for:
   - GraphQL POST body and authorization header.
   - request query selection from part number or free-text query.
   - mapping Nexar `supSearchMpn` results to `EvidenceSourceCandidate`.
   - empty result handling.
   - GraphQL error handling.
2. Implement `src/pcbsmith/evidence/nexar.py`.
3. Export the adapter from `pcbsmith.evidence`.
4. Run targeted evidence tests, ruff, mypy, and full unit/integration tests.

## Status Ledger

Implemented after this slice:

- A real adapter boundary matching the documented Nexar GraphQL/OAuth request
  style.
- Mock-transport tests proving request and mapping behavior.

Still not implemented after this slice:

- Real credentials.
- Live Nexar request execution.
- OAuth token exchange.
- Datasheet parsing.
- Extracted fact validation.

