# Assembly robustness walk (design B, ops#640)

Seeded random edit walk over a designed assembly: Blk (a PartDesign box) grounded, Pin (sketch + pad,
circle or hexagon) fastened top face onto Blk's top face, a linear pattern of the Pin along a Blk X edge.

**Edits:** Blk sizes, fillet add/radius/suppress, a top pocket (AR2), Pin sizes, a circle<->hexagon
profile swap in the same sketch (R1.8), pattern count and spacing, mate offset, delete a copy, delete
the seed + undo (AR5), undo, save + reopen.

**After each step:**
- the solve converges;
- placements match the closed form (CENTROID connectors, copy i = seed + i·d along the edge);
- undo and reopen restore the snapshot;
- a fresh document built from the parameter vector matches.

**Verdicts:** OK, LOUD, BEYOND (past a geometric limit), SILENT (the target), EXC. A walk stops at the
first SILENT or EXC.

    bash tests/asmwalk/run.sh <checkout> <seed> <steps> [edit kinds, comma list]

The log is `work/asmwalk/runs/s<seed>.jsonl`; `summ.py` prints it. Environment:
- `ASMWALK_OFFSET=onshape` expects the offset along the first pick (ops#826 fixed);
- `ASMWALK_PROFILE_W` is the profile-swap weight.

Probes (one-off repros):
- `probe_offset.py`: ops#826;
- `probe_invalid_offset.py`: ops#827;
- `probe_ar.py`: oracle AR1/AR2.

Known: the headless undo stack holds 20 steps, and the walk tracks only that many.
