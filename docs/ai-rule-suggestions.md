# AI Rule-Change Suggestion Log

Governance: `docs/pcb-design-rules.md` is the authoritative rulebook. Once
rule confinement is enabled, AI reviewers and revision loops must NOT edit
the rulebook or the check implementations directly. Instead, a proposed rule
change, new rule, or relaxation is appended here as a dated entry; a human
reviews and either promotes it into the rulebook (with a machine check) or
rejects it with a note. Until then, entries below also serve as a changelog
of AI-originated rules that were applied directly with user permission.

Entry format:

```
## YYYY-MM-DD <short title>
- status: proposed | promoted | rejected
- proposed_by: <model / check / session>
- rule: <existing rule id, or "new">
- suggestion: <what should change and the exact proposed wording>
- evidence: <the design/revision and observation that motivated it>
- decision_note: <filled by the human>
```

---

## 2026-07-02 Trailing connectors close the row at the right edge
- status: promoted (applied directly with user permission, commit `05f55a4`)
- proposed_by: claude-fable-5 visual review of outputs/lm2596-buck-r004
- rule: 1.1
- suggestion: Multi-connector boards place the first connector at the left
  edge and all further connectors at the right edge so power enters one side
  and exits the other.
- evidence: r004 placed P2 adjacent to P1, forcing VOUT to traverse the full
  board and return.
- decision_note: user-approved direct edit; promoted into rule 1.1 and the
  placer.

## 2026-07-02 Power nets weight the placement ordering cost
- status: promoted (applied directly with user permission, commit `05f55a4`)
- proposed_by: claude-fable-5 visual review of outputs/lm2596-buck-r004
- rule: 3.1 / 3.2
- suggestion: Weight power-net span 3x in the row-ordering cost so the
  switching path places contiguously (1-D loop minimisation).
- evidence: r004 interleaved CIN/COUT far from U1/D1/L1, producing a long
  switching loop despite a DRC pass.
- decision_note: user-approved direct edit; promoted with the
  switching-cluster geometric check as the enforcement ratchet.
