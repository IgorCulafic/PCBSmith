from pcbsmith.board_job import input_identity


def test_private_asset_resolution_and_bytes_are_effective_inputs(tmp_path, monkeypatch):
    monkeypatch.delenv("PCBSMITH_PRIVATE_ASSET_ROOT", raising=False)
    args = ("--board", "absent.kicad_pcb", "--output", "one")
    before = input_identity("pcbsmith.production_routing", args)
    root = tmp_path / "private"
    root.mkdir()
    monkeypatch.setenv("PCBSMITH_PRIVATE_ASSET_ROOT", str(root))
    empty = input_identity("pcbsmith.production_routing", args)
    assert empty != before
    asset = root / "part.kicad_mod"
    asset.write_bytes(b"first")
    installed = input_identity("pcbsmith.production_routing", args)
    assert installed != empty
    asset.write_bytes(b"second")
    changed = input_identity("pcbsmith.production_routing", args)
    assert changed != installed
    assert changed == input_identity("pcbsmith.production_routing", args[:-1] + ("two",))
    (root / "unrelated.log").write_text("not a native dependency")
    assert changed == input_identity("pcbsmith.production_routing", args)
