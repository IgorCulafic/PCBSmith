# aerosense-2f-r001 deterministic concept review

Outcome: **needs_user_decision**

This is a feasibility and placement record, not a routed PCB or fabrication approval.

## Items

| Item | Side | Status | Edge clearance | Result |
|---|---|---:|---:|---|
| J1 | front | engineering_selection | 1.1250 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| USB-C | front | tight | -0.5750 mm | Envelope overhangs the substrate under an explicit overhang allowance. |
| U7 | front | engineering_selection | 8.1500 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| VBUS ESD | front | engineering_selection | 7.5500 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| CC ESD | front | engineering_selection | 7.7000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| U3 | front | engineering_selection | 8.4500 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| U4 | front | engineering_selection | 9.6000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| RP2040 | front | engineering_selection | 18.8700 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| U2 | front | engineering_selection | 19.3000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| Y1 | front | engineering_selection | 13.4000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| U5 | front | engineering_selection | 21.9500 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| U6 | front | engineering_selection | 15.9500 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| PWM1 | front | engineering_selection | 18.3000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| PWM2 | front | engineering_selection | 15.0700 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| U8 | front | engineering_selection | 6.0000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| microSD | front | engineering_selection | 0.5200 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| SD ESD | front | engineering_selection | 16.5000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| FAN1 | front | engineering_selection | 1.6500 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| FAN2 | front | engineering_selection | 8.2000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| MODE | front | engineering_selection | 9.0000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| SELECT | front | engineering_selection | 9.0000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| LOG | front | engineering_selection | 2.0000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| PWR | front | engineering_selection | 6.2700 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| FAULT | front | engineering_selection | 6.2700 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| LOG | front | engineering_selection | 6.2700 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| SWD | back | engineering_selection | 9.0000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| OLED | front | engineering_selection | 0.5000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| SHT45 isolation | front | comfortable | 1.2500 mm | Contained with 1.250 mm minimum edge clearance. |
| power.passives | front | engineering_selection | 8.0000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| mcu.passives | front | engineering_selection | 20.7000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| fan.passives | front | engineering_selection | 10.0000 mm | Geometry is feasible; placement is an engineering proposal awaiting approval. |
| USB cable | front | tight | 0.0000 mm | Contained, but only 0.000 mm from the board edge. |
| card access | front | tight | 0.0000 mm | Contained, but only 0.000 mm from the board edge. |
| H1 | both | comfortable | 1.4000 mm | Contained with 1.400 mm minimum edge clearance. |
| H2 | both | comfortable | 1.4000 mm | Contained with 1.400 mm minimum edge clearance. |
| H3 | both | comfortable | 1.4000 mm | Contained with 1.400 mm minimum edge clearance. |
| H4 | both | comfortable | 1.4000 mm | Contained with 1.400 mm minimum edge clearance. |

## Hard conflicts

- None recorded.

## Assumptions and engineering selections

- Adafruit 4440 uses its documented 35 x 20 mm PCB envelope in landscape.
- Fan headers are vertical Molex 47053-family geometry.
- SHT45 isolation is represented by an 11.5 x 11.5 mm component-centred zone.
- The overlays are exact-placement plans, not routed or thermally validated boards.

## View conventions

- front: component side viewed from above in board coordinates
- back: solder side viewed from below; horizontal axis is mirrored
