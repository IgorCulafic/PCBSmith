# PCBSmith Phase 2 Component Catalog Design

Date: 2026-05-09
Status: Draft for user review
Previous milestone: `docs/superpowers/specs/2026-05-08-pcbsmith-phase-1b-design.md`

## Decision

Phase 2 builds the component library foundation that PCBSmith needs before
text-to-PCB and LLM-assisted design can be trustworthy. The app should move from
a flat hardcoded symbol list toward a searchable, tagged, user-preference-aware
component catalog.

The first catalog uses generic real package variants for common starter parts.
Examples include `Resistor 0603`, `Capacitor 0805`, `LED 0603`, and
`Pin Header 1x02 P2.54mm`. These are not vague placeholders: each usable entry
must map to real symbols, real footprints where needed, and enough metadata for
the UI and future AI tools to explain and place it safely.

Exact manufacturer part numbers are deferred for simple passives and basic
parts. Chips, modules, and specialized components later need exact designations,
pinouts, package mappings, and sourcing metadata because mistakes there carry
more risk.

## Phase 2 Scope

Phase 2 includes:

- A PCBSmith-native component catalog model above raw symbols and footprints.
- A curated built-in Basic Components catalog group.
- Generic real component variants for starter PCB work.
- Multiple normalized tags per component for type, family, package, mounting
  style, electrical role, beginner/common status, and search aliases.
- A searchable library panel that can match names, families, package sizes, and
  tags.
- Preferred-parts profiles with global defaults and per-project overrides.
- Basic component shortcuts for the most common schematic actions.
- A service layer that UI code and future AI tools can both use to search,
  inspect, and place supported catalog entries.
- Structured missing-part requests when a needed component is unavailable.
- Developer-mode library proposals as a separate path from normal user placement.
- Catalog validation tests and project persistence tests.

Phase 2 excludes:

- Importing LibrePCB, KiCad, or any other external library format.
- Bundling KiCad-derived data.
- Manufacturer part number catalogs for simple passives.
- Full BOM/procurement workflows.
- Circuit simulation, SPICE model management, or simulation-ready component
  models.
- PCB layout editing, footprint placement on boards, routing, SVG, laser-ready
  PCB outputs, Gerber, PDF, or manufacturing export work.
- A full draw.io-style library manager UI. Phase 2 should build the data model
  and first useful browser; richer library management can come later.
- AI provider integration or natural-language design generation.

## Catalog Strategy

PCBSmith owns one internal catalog schema. The built-in starter catalog uses that
schema directly. Outside ecosystems such as LibrePCB and KiCad are future source
formats that may feed PCBSmith through adapters, but their quirks should not leak
into the UI, project model, schematic editor, or AI tool surface.

LibrePCB is the preferred future import candidate because its official libraries
are CC0 and its library model is intentionally structured. KiCad remains on the
table because its library ecosystem is large and mature, but KiCad integration is
deferred and should live behind an adapter with explicit licensing review before
any data is bundled or redistributed.

Useful references:

- LibrePCB license: https://librepcb.org/license/
- LibrePCB library concept: https://librepcb.org/features/library-concept/
- LibrePCB library repositories: https://github.com/LibrePCB-Libraries
- LibrePCB library documentation: https://developers.librepcb.org/df/d4f/doc_library.html
- KiCad libraries: https://kicad.github.io/
- KiCad library license: https://www.kicad.org/libraries/license/
- Falstad/CircuitJS about and license: https://www.falstad.com/circuit/about.html

Falstad/CircuitJS is useful later as simulation inspiration, but it is not a PCB
component library source for symbols, footprints, and manufacturing data.

## Architecture

The existing Phase 1B architecture remains `ui -> services -> core`.

`core/` should define durable, UI-free catalog types. The existing `Symbol` and
`Footprint` models remain low-level schematic and layout primitives. The new
catalog model sits above them and describes components the user can choose.

`services/` should own built-in catalog loading, search, validation, preference
resolution, and missing-part request creation. UI code and future AI tools should
call the same service APIs instead of reaching into raw symbol dictionaries.

`ui/` should replace the flat symbol list with a first searchable component
browser. The browser can stay simple in Phase 2, but it should use the catalog
service so future catalog behavior does not require widget-specific rewrites.

Likely model responsibilities:

- `ComponentFamily`: broad part family such as resistor, capacitor, LED, diode,
  connector, button, switch, power symbol, or later IC.
- `ComponentVariant`: a usable generic real variant such as `Resistor 0603` or
  `Pin Header 1x02 P2.54mm`.
- `CatalogEntry`: connects a variant to a symbol, optional footprint, tags,
  aliases, placement defaults, and source metadata.
- `CatalogGroup`: named group such as Basic Components, Basic SMD Passives,
  Headers, or Through-hole Beginner Parts.
- `PreferredPartsProfile`: enabled groups and per-entry visibility choices.
- `CatalogSearchQuery`: normalized search text, tags, group filters, and
  preferred-only state.
- `MissingPartRequest`: structured record of an unavailable component request.
- `DeveloperLibraryProposal`: developer-mode proposal for adding or adapting a
  new component entry.

Normal user placement must use `CatalogEntry` objects, not raw symbol ids.
Symbols and footprints remain implementation details of the catalog.

## Basic Components Group

Phase 2 ships with a curated Basic Components group enabled by default. It should
cover the first practical set for beginner schematic work:

- Resistors.
- Capacitors.
- LEDs.
- Diodes.
- Push buttons.
- Switches.
- Basic pin headers and connectors.
- Power symbols.
- Ground symbols.

Wire remains a tool, not a component, but it should stay near the Basic
Components shortcuts because it is part of the core schematic workflow.

The toolbar should keep the fastest path visible: select, wire, resistor,
capacitor, LED, label, no-connect, and a More Components action that opens or
focuses the searchable browser. Buttons, switches, connectors, and less common
items can start in the browser unless a later usability pass shows they deserve
toolbar space.

## Tags And Search

Each catalog entry can have multiple tags. Tags should be normalized to predictable
lowercase tokens so the same component can be found through different user and AI
phrasing.

Recommended tag categories include:

- Type: `resistor`, `capacitor`, `led`, `diode`, `switch`, `button`, `connector`.
- Family: `passive`, `indicator`, `input`, `power`, `connector`.
- Mounting: `smd`, `through-hole`.
- Package: `0603`, `0805`, `1206`, `p2.54mm`.
- Practical status: `basic`, `beginner`, `common`.
- Electrical role: `pull-up`, `pull-down`, `decoupling`, `indicator`, `power`.
- Future domains: `logic`, `audio`, `sensor`, `rf`, `simulation`.

The search bar should match:

- Display name.
- Family name.
- Package name.
- Tags.
- Aliases and common phrases.

Useful searches should include `0603`, `led`, `header`, `smd`, `through hole`,
`power`, and `button`.

## Preferred Parts

PCBSmith should support preferred-parts profiles from the beginning because the
catalog will grow quickly.

There are two preference levels:

- Global defaults for the user's normal workspace.
- Per-project overrides for project-specific needs.

Resolution should be simple and predictable:

1. Start with PCBSmith's built-in default profile.
2. Apply global user preferences when present.
3. Apply the open project's overrides when present.
4. Show matching visible entries in the library browser.

Existing projects should continue opening with the built-in default profile. New
project data can add a small preferences section for enabled groups and explicit
entry visibility overrides. Preferences should not duplicate built-in catalog
entry definitions inside each project.

## User And AI Flow

For users, the library panel becomes a searchable component browser with category
filters, tags, and preferred-parts controls. A preferred-only toggle helps users
keep the visible list small. The More Components action should focus this browser
when the toolbar shortcuts are not enough.

For future AI behavior, the rule is that the AI uses the same catalog service as
the UI. It can search components, inspect metadata, place supported entries, and
explain why it chose them. It should not invent hidden symbols, create raw JSON,
or edit project files directly.

If a requested component is missing, the AI may create a `MissingPartRequest`.
In developer mode, it may also create a `DeveloperLibraryProposal`. Neither path
turns into a normal usable component until reviewed and accepted by PCBSmith's
library process.

## External Library Adapter Readiness

Phase 2 does not implement external imports, but the catalog should be shaped so
LibrePCB and KiCad can work later without clashing with PCBSmith's own data.

The adapter-ready rules are:

- PCBSmith keeps one internal schema.
- Source-specific importers convert into that schema.
- Imported entries enter a quarantine or review layer first.
- Approved imports become normal catalog entries with source metadata.
- IDs are namespaced from the beginning, such as `pcbs:resistor_0603`,
  `librepcb:...`, or `kicad:...`.
- Duplicate detection can later compare source id, family, pin count, package,
  footprint, tags, and aliases.
- Removing one source, including KiCad-derived content, should not break native
  PCBSmith entries.

This keeps KiCad available as a future option without forcing Phase 2 to solve
KiCad licensing, format conversion, or redistribution decisions now.

## Persistence

Project files should remain backward compatible.

The existing `Project` model should gain optional catalog preference data in a
way that defaults to the built-in profile when omitted. The schematic model
should continue storing placed symbols and their selected footprint ids as it
does today. Phase 2 placement resolves a `CatalogEntry` into the existing
symbol/footprint fields instead of requiring a schematic file format change.
Future phases can add durable catalog references to placed symbols after there
is a migration plan.

Preference persistence should record stable ids for enabled groups and explicit
entry visibility overrides. It should not serialize the full built-in catalog into
project files.

## Error Handling

The app should fail kindly when catalog operations cannot complete.

Examples:

- Unknown catalog id.
- Catalog entry points to a missing symbol.
- Catalog entry points to a missing required footprint.
- Search query has no matches.
- A user or AI asks for a missing component.
- A developer proposal is incomplete or invalid.

Recoverable errors should leave the current schematic unchanged and surface a
clear message in the UI or service result. Missing components should produce
structured requests rather than fake components.

## Testing

Required automated coverage:

- Catalog model validation.
- Built-in catalog validation.
- Tag normalization and search matching.
- Search by name, family, package, tag, and alias.
- Preferred-profile resolution across built-in defaults, global preferences, and
  project overrides.
- Backward compatibility for projects without catalog preference data.
- Placement from a catalog entry through the same service path the UI will use.
- Rejection of unknown or invalid catalog entries.
- Missing-part request creation.
- Developer proposal validation staying separate from normal catalog entries.
- Import boundary checks remain valid: core/services/cli do not import Qt or UI.

Manual verification should confirm that the GUI launches, existing projects still
open, the library browser searches and filters components, preferred-only filtering
works, toolbar shortcuts still place common schematic items, and the More
Components action exposes the wider catalog.

## Acceptance Criteria

Phase 2 is accepted when:

- The app has a real component catalog model above raw symbols and footprints.
- Basic Components are available through catalog entries.
- Components support multiple normalized tags.
- The library panel can search by name, family, package, tag, and alias.
- Users can filter to preferred entries.
- Preferred-parts settings support global defaults and per-project overrides.
- The UI can place selected catalog components.
- Basic shortcuts remain available for resistor, capacitor, LED, wire, label, and
  no-connect workflows.
- The service layer can search, inspect, and place only supported catalog entries.
- Missing components produce structured missing-part requests.
- Developer-mode proposals remain separate from usable normal-user catalog entries.
- Existing Phase 0, Phase 1A, and Phase 1B projects still open.
- Tests cover validation, search, preferences, placement, missing-part behavior,
  and persistence.

## Risks

The main risk is growing a library system that is too broad for a single phase.
The response is to implement the PCBSmith-native catalog foundation and a small
curated starter group first, while deferring external imports and rich library
management.

Another risk is letting future KiCad or LibrePCB details leak into the core app.
The response is to keep one internal schema and treat external libraries as source
formats behind adapters.

Search can become confusing if tags are inconsistent. The response is to normalize
tags and aliases during catalog validation and cover the expected beginner queries
with tests.

AI workflows can become unsafe if the model can invent components. The response is
to make the AI use catalog service operations only, with missing-part requests as
the sanctioned path for unavailable components.
