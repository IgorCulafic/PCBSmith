# Nexar OAuth And Live Smoke Plan

Date: 2026-05-20

## Objective

Add the minimum live-check boundary for Nexar supply search while keeping normal
PCBSmith generation fully offline and safe by default.

## Official API Notes

Nexar documentation describes OAuth2 access tokens for API queries. For supply
queries, Nexar recommends the client credentials grant with:

- token endpoint: `https://identity.nexar.com/connect/token`
- `grant_type=client_credentials`
- client ID and client secret from the Nexar portal
- `scope=supply.domain`

Access tokens are then sent to the GraphQL API as bearer tokens.

## Implemented In This Slice

- `NexarClientCredentialsTokenProvider` with injected form transport.
- `UrlLibNexarTransport` for explicit JSON/form POSTs using the Python standard
  library.
- `pcbsmith evidence-nexar-smoke`, an opt-in live smoke command.
- The smoke command skips without network access unless both
  `PCBSMITH_NEXAR_CLIENT_ID` and `PCBSMITH_NEXAR_CLIENT_SECRET` are set.

## Non-Goals

- No credential storage.
- No automatic live network call from generation commands.
- No datasheet download from the smoke command.
- No parsing of Nexar metadata into trusted facts.
- No component support-status upgrade from live provider metadata.

## Verification

- Unit tests cover token exchange payload and malformed token response handling.
- Integration tests cover safe skip behavior when credentials are absent.
- Full project lint, typing, and unit/integration tests must pass.

