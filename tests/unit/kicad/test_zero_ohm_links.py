import pytest

from pcbsmith.kicad.library import parse_sexpr
from pcbsmith.kicad.native_edits import atom, child, children, reference
from pcbsmith.kicad.zero_ohm_links import ZeroOhmLink, plan_zero_ohm_links


@pytest.fixture
def source(tmp_path):
    # Synthetic flat label-stub fixture. Native board acceptance is separate.
    p = tmp_path / "test.kicad_pcb"
    p.write_text("""(kicad_pcb
      (footprint "Test:R" (layer "F.Cu") (at 10 10 0) (uuid "r1") (path "/s1")
        (property "Reference" "R1" (at 0 -2 0)) (property "Value" "1k" (at 0 2 0))
        (pad "1" smd rect (at -1.7 0 0) (size .8 1.75) (layers "F.Cu") (net "/N"))
        (pad "2" smd rect (at 1.7 0 0) (size .8 1.75) (layers "F.Cu") (net "/N")))
      (segment (start 8.3 10) (end 8.3 20) (width .8) (layer "F.Cu") (net "/N") (uuid "a"))
      (segment (start 8.3 20) (end 30 20) (width .8) (layer "F.Cu") (net "/N") (uuid "b"))
      (segment (start 30 20) (end 30 10) (width .8) (layer "F.Cu") (net "/N") (uuid "c"))
      (segment (start 30 10) (end 11.7 10) (width .8) (layer "F.Cu") (net "/N") (uuid "d")))""")
    p.with_suffix(".kicad_sch").write_text("""(kicad_sch (uuid "root")
      (lib_symbols (symbol "Test:R" (symbol "R_1_1"
       (pin passive line (at 0 3.81 270) (number "1"))
       (pin passive line (at 0 -3.81 90) (number "2")))))
      (symbol (lib_id "Test:R") (at 20 20 0) (uuid "s1")
       (property "Reference" "R1" (at 22 20 0)) (property "Value" "1k" (at 22 22 0))
       (instances (project "test" (path "/" (reference "R1") (unit 1)))))
      (wire (pts (xy 20 16.19) (xy 20 12)) (uuid "w1"))
      (label "N" (at 20 12 0) (uuid "l1"))
      (wire (pts (xy 20 23.81) (xy 20 28)) (uuid "w2"))
      (label "N" (at 20 28 0) (uuid "l2")))""")
    return p


def link(**kw):
    return ZeroOhmLink(
        **(
            dict(
                reference="R2",
                template_reference="R1",
                net_name="/N",
                position_mm=(20, 20),
                axis_screen_deg=0,
                schematic_position_mm=(50, 50),
                keep_pad=("R1", "1"),
            )
            | kw
        )
    )


def test_link_splits_copper_and_schematic_deterministically(source):
    original = source.read_bytes()
    a, extra, records = plan_zero_ohm_links(source, original, (link(),))
    assert a == plan_zero_ohm_links(source, original, (link(),))[0]
    assert source.read_bytes() == original
    fps = {reference(f): f for f in children(parse_sexpr(a.decode()), "footprint")}
    nets = [atom(child(p, "net")[1]) for p in children(fps["R2"], "pad")]
    assert len(set(nets)) == 2
    sch = parse_sexpr(extra["test.kicad_sch"].decode())
    assert len(children(sch, "symbol")) == 2
    assert {atom(label[1]) for label in children(sch, "label")} == {"N", "N_LINK1"}
    assert records[0]["reference"] == "R2"


@pytest.mark.parametrize(
    "change,match",
    [
        ({"reference": "R1"}, "already exists"),
        ({"position_mm": (20, 21)}, "exactly one"),
        ({"axis_screen_deg": 45}, "inline"),
    ],
)
def test_rejects_ambiguous_or_invalid_link(source, change, match):
    with pytest.raises(ValueError, match=match):
        plan_zero_ohm_links(source, source.read_bytes(), (link(**change),))
