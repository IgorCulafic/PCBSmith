from __future__ import annotations

from pathlib import Path

from pcbsmith.services.kicad_backend import default_kicad_cli_candidates, find_kicad_cli


def test_find_kicad_cli_prefers_explicit_environment_path() -> None:
    install = find_kicad_cli(
        env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
        which=lambda _name: None,
        candidate_paths=(),
    )

    assert install is not None
    assert install.cli_path == Path("C:/Tools/KiCad/bin/kicad-cli.exe")
    assert install.source == "PCBSMITH_KICAD_CLI"


def test_find_kicad_cli_uses_path_lookup_when_environment_is_empty() -> None:
    install = find_kicad_cli(
        env={},
        which=lambda name: f"C:/Program Files/KiCad/bin/{name}.exe",
        candidate_paths=(),
    )

    assert install is not None
    assert install.cli_path == Path("C:/Program Files/KiCad/bin/kicad-cli.exe")
    assert install.source == "PATH"


def test_find_kicad_cli_uses_existing_candidate_path() -> None:
    candidate = Path("C:/Program Files/KiCad/9.0/bin/kicad-cli.exe")

    install = find_kicad_cli(
        env={},
        which=lambda _name: None,
        candidate_paths=(candidate,),
        exists=lambda path: path == candidate,
    )

    assert install is not None
    assert install.cli_path == candidate
    assert install.source == "known install path"


def test_default_kicad_cli_candidates_include_kicad_10() -> None:
    assert Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe") in (
        default_kicad_cli_candidates()
    )


def test_find_kicad_cli_returns_none_when_unavailable() -> None:
    install = find_kicad_cli(
        env={},
        which=lambda _name: None,
        candidate_paths=(Path("C:/missing/kicad-cli.exe"),),
        exists=lambda _path: False,
    )

    assert install is None
