# PCBSmith test project — AeroSense-2F

**Project:** USB-C environmental monitor and dual-fan controller
**Prompt revision:** R001, engineering-reviewed 2026-07-26
**Board class:** Medium-complexity, rectangular, two-layer
**Test purpose:** First joint Phase 17 production-workflow and Phase 18
manufacturing-output exercise after generator migration

## 0. Authority and workflow

This document is the revised project authority. Requirements containing
**must**, **shall**, an exact value, or an exact part number are hard unless a
later recorded approval changes them. Wording such as **prefer**, **ideally**,
or **if achievable** is a preference.

Do not start schematic or PCB generation until:

1. exact-part discovery has frozen the fan electrical envelope, USB-C
   receptacle, Type-C current detector, fan power switches, OLED module,
   microSD socket, fan headers, buttons and LEDs;
2. footprints, mating access, height, lifecycle, purchasability and 3D-model
   evidence are retained for those parts;
3. the 70 mm × 50 mm feasibility and concept-placement review has passed; and
4. the user has approved the concept package.

If a hard constraint is infeasible, stop and report the conflict with at least
two spirit-preserving alternatives. Do not silently enlarge the board, move an
edge interface, omit a connector or downgrade a requirement.

## 1. Purpose and operating modes

The board shall:

- measure ambient temperature and relative humidity with an SHT45;
- display current readings, fan state and faults on a 128 × 32 I²C OLED;
- control two independent 5 V four-wire PWM fans;
- measure each fan's tachometer output;
- optionally log periodic measurements to a mandatory microSD socket; and
- enumerate over USB 2.0 full-speed as a CDC-ACM serial device for
  configuration and live telemetry.

There is no battery or hold-up supply. Removing USB power immediately removes
board power.

The third button toggles logging. Functions for buttons one and two and the
status LEDs shall be proposed during concept review and frozen before
schematic approval.

CSV logging and ten-second flushing are firmware requirements. They reduce
recent buffered-data loss but do not guarantee filesystem integrity if power
is removed during a card write. Firmware and power-removal testing shall be
reported separately from PCB electrical acceptance.

## 2. USB-C power policy

### 2.1 Sink attachment and available-current detection

- The receptacle shall be a USB-C sink/UFP with one 5.1 kΩ Rd termination from
  each CC pin to ground.
- Rd establishes sink attachment; it does not guarantee 1.5 A.
- The board shall include a sink-side Type-C CC/current-advertisement detector
  capable of distinguishing Default USB current from 1.5 A and 3.0 A source
  advertisements.
- USB Power Delivery is not required because the board uses only 5 V.
- The current detector's exact part shall be selected from current,
  orderable, documented devices with a retained datasheet and CAD evidence.

### 2.2 Power states

- At Default USB current, the board may power the MCU, sensor, OLED and
  microSD interface, but both fan rails shall remain disabled.
- The fan rails may be enabled only after the board has detected a source
  advertisement of at least 1.5 A.
- Both fan power-switch enable inputs shall have hardware defaults that keep
  them off during reset, boot, brownout, missing firmware or a floating MCU
  pin.
- USB suspend and resume current behavior is a firmware/system verification
  obligation. The fans shall be off during suspend.
- If available current is insufficient, firmware shall expose a visible fault
  state and continue logic-only operation where USB rules permit.

### 2.3 Current budget

The design envelope is:

- 500 mA maximum design current per fan connector, including the accepted
  startup/locked-rotor envelope;
- 200 mA maximum reserved for MCU, flash, sensor, OLED, microSD, LEDs,
  regulators and losses; and
- 1.2 A total board design current when both fans are enabled.

The exact selected fans must operate from 5 V and provide evidence that their
running, startup and locked-rotor behavior fits this envelope. A generic
"standard PC fan" claim is insufficient because many four-wire PC fans require
12 V.

## 3. Electrical architecture

### 3.1 Rails

- Input: USB-C VBUS, nominal 5 V, allowed source range per applicable USB-C
  authority.
- Logic: one 3.3 V rail from an LDO rated for at least 600 mA.
- Fans: two independently switched 5 V outputs, `5V_FAN1_SW` and
  `5V_FAN2_SW`.
- Fans shall never be powered from 3.3 V.
- Fan switching or startup shall not cause MCU reset or loss of the 3.3 V
  rail under the accepted current envelope.

### 3.2 USB data and protection

- USB 2.0 full-speed D+ and D− connect from receptacle to ESD array to 27 Ω
  series resistors to RP2040.
- The two 27 Ω resistors shall be placed close to RP2040 USB_DP and USB_DM.
- The ESD array shall be topologically between the connector and MCU and
  located as close as practical to the connector pins.
- USBLC6-2SC6 may be used for D+/D− only if its exact package, pinout and
  current lifecycle evidence pass.
- VBUS shall have a separately selected transient/ESD device suitable for the
  5 V bus. CC pins shall receive protection consistent with the selected
  Type-C current detector's reference design.
- Connector shield termination shall be explicitly designed and reviewed; it
  shall not be left accidental or inferred from the footprint.

### 3.3 RP2040 minimum system

- MCU: Raspberry Pi RP2040, QFN-56, exact part.
- Follow the current official Raspberry Pi minimal/reference design rather
  than a manually shortened substitute.
- Include the required VREG_IN, VREG_OUT, DVDD, IOVDD, USB_VDD and ADC_AVDD
  supply connections, filtering and decoupling.
- Use approximately one 100 nF local decoupling capacitor per applicable
  supply pin except where the official two-layer reference design explicitly
  documents a shared capacitor.
- Decoupling acceptance is based on the complete supply-and-return loop, not
  capacitor-center distance alone.
- The QFN exposed ground pad shall use the official/reference land pattern,
  ground connection, via strategy and paste treatment.
- Provide edge-accessible SWD and deliberate BOOTSEL/reset access.

### 3.4 Flash and crystal

- QSPI flash: at least 2 MB, SOIC-8 permitted, exact orderable part selected
  before schematic freeze.
- The flash circuit, pull-up/DNP policy and routing shall follow the current
  RP2040 reference guidance.
- Prefer the officially recommended 12 MHz crystal circuit. If
  ABM8-272-T3 is selected, retain its 1 kΩ series resistor and two 15 pF C0G/NP0
  load capacitors as shown in the reference design.
- Any substitute crystal requires recalculation of load capacitance using its
  specified CL and retained PCB/parasitic assumptions. Do not carry 15 pF
  capacitors to an unrelated crystal by default.

### 3.5 Fan power and signals

- Each fan connector shall support 5 V at 500 mA design current.
- Prefer one independently current-limited, thermally protected high-side
  switch per fan so one fault does not necessarily disable the other fan.
- Each switch shall be rated above the accepted continuous/startup envelope
  and shall expose an open-drain, active-low fault indication to the MCU.
- TPS2051B and AP2151 are not approved defaults for this envelope because
  their documented continuous output rating is 500 mA per device. They may
  only be used one per fan if all continuous, startup, thermal and limit
  conditions pass.
- Each PWM output shall be an open-drain sink. Push-pull drive is forbidden.
- Each tachometer input shall accept the selected fan's open-collector output,
  use a documented pull-up to 3.3 V and include any required series
  resistance/filtering/protection.
- PWM, tachometer or fault paths shall not back-power an unpowered fan rail.
- Do not add a generic flyback diode as though the electronically commutated
  fan were a relay coil. Provide local ceramic and bulk bypassing at each
  connector and add cable-transient/TVS protection only when justified by the
  selected fan, switch and hot-plug evidence.
- Nominal PWM frequency: 25 kHz.

### 3.6 Sensor

- Sensor: Sensirion SHT45-AD1B, exact part, four-pin 1.5 mm × 1.5 mm DFN.
- Use the current Sensirion land pattern and paste guidance.
- The optional central die pad shall not be soldered unless later exact
  authority explicitly requires it.
- Keep the sensing opening free of solder, flux, conformal coating, adhesive
  and silkscreen.
- The assembly package shall include humidity-sensor storage, contamination,
  reflow and cleaning notes derived from Sensirion's current handling/design-in
  guidance.
- Use one authoritative 5 mm physical isolation region around the footprint:
  no power switch, LDO, fan connector power pin, switching trace/pour, crystal,
  OLED heat source or other component may enter it.
- Place the sensor near a board edge exposed to ambient airflow and as far as
  feasible from heat-generating circuitry. "Thermally downstream" shall only
  be used if an airflow direction has been declared.

### 3.7 OLED and microSD

- OLED: exact currently purchasable 128 × 32, SSD1306-compatible, four-pin
  I²C module selected before concept freeze.
- The OLED must operate natively at 3.3 V. Record whether it includes I²C
  pull-ups and avoid unintended duplicate pull-ups.
- microSD shall use a bare push-push socket, not a breakout module.
- Select the exact socket before concept freeze and retain its card insertion,
  push-ejection, courtyard, height and 3D mating envelope.
- Wire the card in SPI mode with CS, CLK, MOSI and MISO.
- Include card-detect if the selected socket provides it.
- Provide local bulk and high-frequency decoupling at the socket and reserve
  source-series damping footprints where exact edge-rate analysis recommends
  them.
- The edge-accessible card opening shall receive ESD protection appropriate to
  the selected socket and interface.

## 4. Component-selection authority

| Function | Authority |
|---|---|
| RP2040 | Exact part, no substitution |
| SHT45-AD1B | Exact part, no substitution |
| QSPI flash | PCBSmith selects exact compatible, orderable part |
| Crystal | Prefer exact RP2040 reference part/circuit; substitution requires recalculation |
| USB-C receptacle | Select one exact mid-mount USB 2.0 receptacle before concept freeze |
| Type-C current detector | PCBSmith selects exact sink-capable detector |
| USB data ESD | USBLC6-2SC6 preferred; equivalent allowed with evidence |
| VBUS/CC protection | PCBSmith selects exact devices from interface authority |
| OLED | PCBSmith selects exact 3.3 V-native module |
| microSD | PCBSmith selects exact bare push-push socket |
| 5 V fans | Exact fan or exact interface-envelope evidence required before schematic freeze |
| Fan headers | PCBSmith selects exact shrouded connector and mating orientation |
| Fan power switches | PCBSmith selects exact parts after fan/startup envelope is frozen |
| PWM sinks | PCBSmith selects exact orderable dual or two single N-MOS devices |
| LDO | AP2112K-3.3 preferred; equivalent ≥600 mA device allowed |
| Buttons and LEDs | PCBSmith selects exact orderable parts after concept approval |

All BOM parts shall have retained manufacturer lifecycle and purchasability
evidence dated to the generation. A temporarily unavailable supplier API is a
blocked/unknown result, not permission to claim that a part is current.

Allowed passive sizes are 0402 through 0805. Flag every 0402 line in the BOM.
QFN-56 and SHT45 DFN assembly need not be hand-solderable. All other choices
should remain reasonably reworkable where the electrical and mechanical
requirements permit.

## 5. Mechanical constraints

- Rectangular outline: 70 mm × 50 mm hard maximum for the first feasibility
  attempt.
- Standard 1.6 mm FR4.
- Four symmetric M3 NPTH mounting holes, 3.2 mm drill, hole centers 3 mm from
  their corresponding X and Y edges.
- No component body or courtyard within 4 mm of a mounting-hole center.
- Retain at least 1.5 mm copper clearance from each finished hole edge unless
  the fabrication authority requires more.
- USB-C: left edge, mating face outward through X = 0. Shell overhang no more
  than 1.0 mm; all electrical pads and mechanical support tabs remain on
  supported PCB material.
- OLED: top side, upright in the declared normal viewing orientation.
- Three top-side buttons with at least 6 mm center-to-center spacing and clear
  finger access.
- Fan connectors: exact right-angle or vertical orientation shall be selected
  before concept approval. Edge overhang up to 1.5 mm is allowed only for a
  connector whose mating geometry requires it; pads and retained support
  remain on PCB material.
- microSD: edge-accessible, with the full card insertion/ejection swept volume
  outside the component keepouts and not directed into the board interior.
- SWD: accessible without removing the OLED or disconnecting fans.
- Maximum assembled component height: 12 mm.

### Feasibility fallback

The concept package shall first test 70 mm × 50 mm. If it cannot satisfy
courtyards, mating access, sensor isolation, USB routing, fan power corridors
and ground continuity, stop before schematic/board generation and present:

1. an 80 mm × 55 mm rectangular alternative; and
2. a second alternative that preserves 70 mm × 50 mm by changing only
   non-hard placement or module choices.

The user must approve an alternative before the hard outline changes.

## 6. Placement intent

- **Left edge:** USB-C, ESD, CC/current detector and VBUS protection.
- **Center-left:** RP2040, QSPI flash, crystal, reference decoupling, BOOTSEL,
  reset and SWD escape.
- **Ambient edge/corner:** SHT45 isolation zone, away from OLED, LDO and fan
  power.
- **User-facing top region:** OLED, three buttons and two or three labeled
  status LEDs.
- **Right or upper-right edge:** two fan connectors with their independent
  switches, local bypassing, PWM sinks and fault/tach conditioning.
- **Remaining accessible edge near MCU SPI pins:** microSD socket.

These are functional zones, not fixed coordinates. The concept-placement
package shall show exact selected footprints, courtyards, board-edge mating
envelopes, mounting-hole keepouts and the 5 mm sensor isolation region.

## 7. Routing and layout priorities

### 7.1 USB

- Route connector → ESD → 27 Ω resistors → RP2040 with no stubs.
- Prefer no vias.
- Keep D+ and D− short, adjacent and over a continuous reference.
- Use nominal 90 Ω differential geometry calculated from the selected
  two-layer stack-up, while acknowledging that no controlled-impedance
  fabrication tier is requested.
- Maximum D+/D− skew target: 0.5 mm. Do not add unnecessary serpentine
  meanders merely to obtain a cosmetically smaller mismatch.
- Retain a short ESD return path and inspect the USB return-current corridor.

### 7.2 Ground and return paths

- Maximize bottom-layer ground continuity.
- Route signals primarily on top; bottom-layer signal segments shall be short,
  reviewed crossings that do not divide the principal return plane.
- No signal shall cross a real ground-pour split without an intentional
  return-path solution.
- Add stitching vias where they materially reconnect return regions, at layer
  transitions, around edge discontinuities and near USB protection. A nominal
  5 mm perimeter spacing is a guideline, not an unconditional quota.
- Ground and exposed-pad via placement shall avoid paste wicking and assembly
  defects.

### 7.3 Power and buses

- Size each fan path for the full accepted 500 mA envelope on 1 oz copper.
- Retain complete VBUS-to-switch-to-connector and connector-return current-path
  evidence, including neck-downs, pads, vias, pours and protection devices.
- Predict fan-path temperature rise below 10 °C under the declared envelope,
  retaining method and assumptions. IPC-2221 may be retained as a legacy
  comparison, but the production result shall use the project's current-path
  authority and shall not treat calculation alone as measured thermal proof.
- Keep fan startup and switching return currents away from the SHT45, crystal,
  USB pair and microSD bus.
- Keep microSD SPI routes short and direct; 15 mm is a preferred target, not a
  reason to violate mating access or sensor isolation.
- Operate microSD at no more than 25 MHz for this prototype unless later signal
  evidence authorizes more.
- I²C pull-up values shall be calculated from the complete bus capacitance,
  device limits and any pull-ups already present on the OLED module.

### 7.4 Test points

Provide labeled test points for:

- VBUS;
- 3V3;
- `5V_FAN1_SW`;
- `5V_FAN2_SW`;
- GND;
- PWM1 and PWM2;
- TACH1 and TACH2;
- both fan fault signals; and
- USB-current-advertisement state signals if exposed by the selected detector.

## 8. Fabrication and assembly

- KiCad 10 project, validated with the repository-pinned KiCad 10 CLI.
- Two copper layers, 1 oz copper each.
- 1.6 mm FR4.
- Minimum track width: 0.153 mm.
- Minimum clearance: 0.153 mm.
- Minimum via: 0.3 mm drill / 0.6 mm pad.
- ENIG finish.
- Green solder mask and white silkscreen on both sides.
- Machine assembly for QFN, DFN, flash and small passives.
- Through-hole connectors and buttons are preferred where compatible with the
  selected exact parts.
- Five prototypes.
- No panelization requested.
- No manufacturer-specific release is authorized initially. Generate the
  manufacturer-neutral Phase 18 package and keep later fabrication/assembly
  readiness dependent on the actual evidence and approvals.

## 9. Required deliverables

- Original prompt, examination, refined authority and feasibility report.
- Approved front/back concept-placement images.
- KiCad 10 schematic, project and routed PCB.
- Retained custom symbols, footprints, local rules and 3D models.
- Connected functional-sheet schematic review package.
- ERC, schematic/PCB parity and DRC reports.
- Applicability-to-execution and component-review evidence.
- Exact route, KiCad read-back and netlist-equivalence evidence.
- Full standardized placement and final-review images, including required
  high-resolution/tiled, 2D layer-specific and populated/bare 3D views.
- Human inspection record for the canonical review package.
- Gerbers and Gerber job file.
- Excellon drills, drill report and drill map.
- IPC-D-356 netlist.
- Manufacturer-part-number BOM.
- Pick-and-place files.
- Front and back assembly drawings.
- Interactive HTML BOM.
- Stack-up and fabrication notes.
- DFM/DFT report.
- VBUS and both fan-path current evidence.
- Hash-verified manufacturer-neutral manufacturing ZIP.
- Explicitly separate:
  `package_generated`, `fabrication_ready`, and `assembly_ready`.

## 10. Silkscreen and artwork

No custom artwork is supplied. The artwork stage shall produce an explicit
not-applicable/clean-skip result rather than waiting, failing or inventing art.

Silkscreen is limited to:

- reference designators;
- pin-1 and polarity markers;
- `USB`, `FAN1`, `FAN2`, `SD` and `SWD` interface labels;
- button/LED function labels after those functions are frozen; and
- `AeroSense-2F` with board revision.

Silkscreen shall not cover pads, sensor opening, card/connector mating regions,
mounting keepouts or required assembly markings.

## 11. PCB acceptance criteria

- The exact prompt and approved concept are traceable to the saved board.
- The 70 mm × 50 mm outline passes feasibility or a user-approved alternative
  is retained before generation.
- Every edge interface is correctly oriented, accessible and within its
  controlled overhang/support envelope.
- No body, courtyard, mating envelope or mounting keepout overlaps.
- RP2040 QFN-56 and SHT45 DFN-4 land, mask and paste geometry pass exact-part
  verification.
- The SHT45 central die-pad policy and 5 mm isolation region are satisfied.
- The complete RP2040 reference power, clock, flash, BOOTSEL/reset and USB
  circuits are present.
- D+ and D− contain the required 27 Ω series resistors and route through ESD in
  the correct topological order.
- Both PWM outputs are proven open-drain and default off.
- Both tachometer inputs and fan-fault inputs have defined, voltage-compatible
  states.
- Type-C source-current advertisement is detected, and hardware defaults keep
  fans disabled without adequate current.
- Fan startup/switching does not violate the accepted source and rail budgets.
- Every routable net has real saved copper; carrier presence is followed by
  exact-route, read-back and netlist-equivalence verification.
- KiCad ERC, schematic parity and PCB DRC are clean.
- Required 3D models resolve, align and remain below the 12 mm height limit.
- The final standardized review package is conformant, complete and visually
  inspected.
- BOM lifecycle/purchasability evidence contains no known NRND/EOL selection;
  unknown provider state remains explicitly blocked.
- The manufacturing archive and every retained artifact pass revision and
  hash-identity verification.

## 12. Firmware/system acceptance kept separate from PCB acceptance

The PCB shall support these behaviors, but they require firmware and bench
testing and shall not be inferred from schematic or DRC:

- CDC-ACM enumeration and serial telemetry;
- Type-C current-state interpretation;
- fans disabled at default current and during USB suspend;
- 25 kHz PWM control and tachometer RPM calculation;
- fan-fault display and reporting;
- button behavior;
- CSV logging, ten-second flush policy and card-removal handling;
- brownout and abrupt-power-removal behavior; and
- operation with one and two selected fans over startup, stall and normal-load
  conditions.

## 13. Primary design authorities

- Raspberry Pi, *Hardware design with RP2040*:
  https://datasheets.raspberrypi.com/rp2040/hardware-design-with-rp2040.pdf
- Sensirion, *Datasheet SHT4x*:
  https://sensirion.com/media/documents/33FD6951/6555C40E/Sensirion_Datasheet_SHT4x.pdf
- USB-IF, *USB Type-C Cable and Connector Specification*:
  https://www.usb.org/document-library/usb-type-cr-cable-and-connector-specification-release-24

The exact selected component datasheets, lifecycle records, footprints,
mechanical drawings, 3D models and supplier evidence become additional
project-specific authorities during intake.
