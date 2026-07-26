# AeroSense-2F R001 exact-part freeze

Status: **frozen_for_concept**

| Reference | MPN | Function | Lifecycle | 3D/CAD state |
|---|---|---|---|---|
| U1 | RP2040 | USB-capable MCU | production | installed_exact_package |
| U2 | W25Q16JVSSIQ | 16-Mbit QSPI boot flash | mass_production | installed_exact_package |
| U3 | AP2112K-3.3TRG1 | 600-mA 3.3-V LDO | active | installed_exact_package |
| U4 | TUSB320LAIRWBR | Type-C UFP current-advertisement detector | active | installed_exact_package |
| U5 U6 | TPS2553DBVR | independent adjustable current-limited fan switch | active | installed_exact_package |
| U7 | USBLC6-2SC6 | USB D+/D- ESD array | active_volume_production | installed_exact_package |
| U8 | SHT45-AD1B-R3 | ambient temperature and humidity sensor | active | dimensioned_exact_package_envelope_required |
| J1 | USB4105-GF-A | USB-C 2.0 top-mount receptacle | active | installed_exact_connector |
| DS1 | 4440 | 0.91-inch 128x32 I2C OLED module | active_orderable | dimensioned_complete_module_model_required |
| J3 | DM3AT-SF-PEJM5 | push-push microSD socket with detect | active | installed_exact_connector |
| J4 J5 | 47053-1000 | four-pin vertical PWM fan header | active | installed_exact_connector_family |
| FAN1 FAN2 | NF-A4x20 5V PWM | selected external 5-V four-wire PWM fan | current_product | external_envelope_recorded |
| SW1 SW2 SW3 | B3F-1000 | 6x6-mm through-hole user buttons | in_production | installed_exact_family |
| J6 | TC2030-IDC-NL | six-pin no-legs SWD programming interface | current_product | access_envelope_only |

## Open evidence actions before schematic release

- Retain exact TPS2553 R_ILIM calculation and tolerance bounds.
- Confirm Adafruit 4440 onboard I2C pull-up values from retained CAD.
- Create and preflight the dimensioned SHT45 package-envelope model.
- Create and preflight the dimensioned Adafruit 4440 module model.
- Retain USB4105 and DM3AT exact mating/access drawings with hashes.

This freeze authorizes concept feasibility only. It is not a BOM release.
