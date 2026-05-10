# KiCad Setup For PCBSmith

PCBSmith uses KiCad as the real EDA backend. The safest local setup is to install the current stable KiCad release, then point PCBSmith at the exact `kicad-cli.exe` you want it to use.

## Recommended Windows Setup

1. Install KiCad from the official KiCad installer.
2. Find `kicad-cli.exe`. Common locations are:
   - `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`
   - `C:\Program Files\KiCad\9.0\bin\kicad-cli.exe`
   - `C:\Program Files\KiCad\8.0\bin\kicad-cli.exe`
3. In PowerShell, set the explicit path for the current terminal:

```powershell
$env:PCBSMITH_KICAD_CLI = "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
```

4. Check readiness:

```powershell
python -m pcbsmith.cli kicad-doctor
```

Expected success:

```text
KiCad CLI: C:\Program Files\KiCad\10.0\bin\kicad-cli.exe (PCBSMITH_KICAD_CLI)
KiCad version: 10.0.1
KiCad backend ready
```

## Validate A Generated Project

Create or export a KiCad handoff project:

```powershell
python -m pcbsmith.cli kicad-new .\kicad-demo --name "LED Blinker"
```

Then run KiCad's ERC and DRC through PCBSmith:

```powershell
python -m pcbsmith.cli kicad-validate .\kicad-demo
```

The command writes machine-readable reports to:

```text
.\kicad-demo\.pcbsmith\kicad-reports\
```

Use this when debugging without executing KiCad:

```powershell
python -m pcbsmith.cli kicad-validate .\kicad-demo --skip-execution
```

## Notes

The old PySide GUI remains a prototype and command test harness. KiCad is the CAD editor/backend path for real schematic, PCB, ERC, DRC, and manufacturing behavior.
