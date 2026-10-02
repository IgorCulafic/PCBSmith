# Current public software state

Updated 2026-10-02. This snapshot brings the maintained software forward from the July public branch. Private manuscripts, experiment histories, machine configuration and local board delivery archives are not part of this update.

## Supported work

- Native KiCad preparation, source-bound component/package/model review and editable dimensioned vector planning before placement.
- Pinned Freerouting for ordinary routing, with finite retries and preserved job history; manual routing requires explicit authorization.
- Bounded local PCB edits, source preservation, project-local library closure and qualified same-footprint SMD substitution.
- Mandatory native ERC/DRC/connectivity/parity and actual source-bound visual inspection before release and handover.
- Portable interactive BOM and editable vector/preview in new handovers.
- Single- and two-sided direct-copper laser isolation SVGs, retained-background or local-clear variants, and exact copper/edge separation checks within the supported straight-track/simple-pad scope.
- Shared verification, crash-safe project transactions, editor reliability improvements and version-pinned dependency metadata.

## Recent corrections

Project-local footprints now remain in scope during routing preparation; front-only routing handles its no-via policy; native no-connect repairs retain exact identities; final renders require current native evidence and preserve diagnostics. Laser artwork keeps complete native source bindings for two-sided drill/CAM handovers.

## Limits and remaining work

Passing software or CAD checks does not qualify physical fabrication. Laser settings, copper widths, electroplating shrinkage/barrel continuity, coating alignment, purchased-part fit and circuit operation need measurements on the exact revision. Broader native desktop interaction and the remaining prospective workflow proof remain open. No universal autorouting success or manufacturing approval is claimed.

The recent trace-limit and plated-hole coupons passed their scoped local CAD handovers; their actual fabrication tests remain open. Delivery archives and raw evidence are retained locally, not distributed in this software update.

Use [production usage](production-usage.md) for supported entry points, [development](development.md) for verification, and the [implementation index](implementation/README.md) for selected engineering records. Historical documents retain their original scope and may reference private local evidence that is not included here.
