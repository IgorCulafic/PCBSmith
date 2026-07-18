$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Cli = "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
$Python = "C:\Program Files\KiCad\10.0\bin\python.exe"

& $Cli version
Get-Item $Cli | Select-Object FullName, Length, @{n="FileVersion";e={$_.VersionInfo.FileVersion}}, @{n="ProductVersion";e={$_.VersionInfo.ProductVersion}}
Get-FileHash -Algorithm SHA256 $Cli

function Export-Masks([string]$Fixture, [string]$OutputName) {
    $out = Join-Path $Root $OutputName
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    & $Cli pcb export gerbers --output $out --layers "F.Mask,B.Mask" --no-protel-ext --no-x2 --no-netlist (Join-Path $Root $Fixture)
}

Export-Masks "probe-base.kicad_pcb" "out-replay-base"
Export-Masks "probe-global-open.kicad_pcb" "out-replay-global-open"
Export-Masks "probe-global-tented-shorthand.kicad_pcb" "out-replay-global-tented-shorthand"
Export-Masks "probe-via-default.kicad_pcb" "out-replay-via-default"
Export-Masks "probe-no-board-clearance.kicad_pcb" "out-replay-no-board-clearance"
Export-Masks "probe-minweb-zero.kicad_pcb" "out-replay-minweb-zero"
Export-Masks "probe-full-project.kicad_pcb" "out-replay-full-project"

& $Cli pcb drc --output (Join-Path $Root "drc-replay-full-project.txt") (Join-Path $Root "probe-full-project.kicad_pcb")

# This intentionally fails with exit 3 on KiCad 10.0.3 because
# `solder_mask_margin_ratio` is not accepted board syntax.
& $Cli pcb export gerbers --output (Join-Path $Root "out-replay-invalid-ratio") --layers "F.Mask" --no-protel-ext --no-x2 --no-netlist (Join-Path $Root "probe-invalid-ratio.kicad_pcb")

# Authoritative KiCad-API flip used to produce probe-api-flipped.kicad_pcb:
& $Python -c "import pcbnew; src=r'$Root\probe-base.kicad_pcb'; dst=r'$Root\probe-api-flipped-replay.kicad_pcb'; b=pcbnew.LoadBoard(src); fp=next(x for x in b.GetFootprints() if str(x.GetFPID().GetLibItemName())=='F-Rot-Probe'); fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT); pcbnew.SaveBoard(dst,b); print(fp.GetLayerName(), fp.GetOrientationDegrees(), [(str(p.GetNumber()), pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y), p.GetOrientationDegrees()) for p in fp.Pads()])"

& $Python (Join-Path $Root "analyze_gerbers.py")
