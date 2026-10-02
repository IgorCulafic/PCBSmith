# Third-party runtime material

PCBSmith source is AGPL-3.0-or-later; the complete GNU AGPL version 3 text is
in `LICENSE`. Dependencies installed separately retain their own licenses.

The bounded symbol and footprint collection under `ai_assets/kicad_symbols`
and `ai_assets/kicad_footprints` originates from the KiCad community libraries.
It is included as `pcbsmith/assets` in the wheel. KiCad library material uses
CC-BY-SA 4.0 with the electronic-design exception described in the retained
`LICENSE.md` files and the [upstream license](https://www.kicad.org/libraries/license/).
The exception for generated designs does not replace the license obligations
for redistribution of a library collection.

Original library and item names are encoded in each asset filename. The
footprint `SOURCES.md` records the local KiCad 10.0.3 source and identifies the
two locally authored `Test__` fixtures. Those fixtures are PCBSmith source
material, not official KiCad land patterns. Symbols are extracted library
items; symbol inheritance can be flattened by the exporter. Bundling an
asset does not establish that its package or pin mapping is qualified for a
particular board.

Full installed KiCad libraries and executables are external prerequisites
for generators that request parts beyond this bounded collection. Models,
books, private asset caches, papers and experiment bundles are excluded from
software distributions. Review redistribution rights for any newly added
third-party asset before adding it to the inclusion list.
