# Edit fuzz for Part Studios (ops#640, block F)

A seeded random walk of user edits on a designed Part Studio. After every step it checks that the document as edited
(an incremental recompute) equals a full recompute from scratch. Designed geometry only, built by the script.

- `fuzz.py`: builds a one-part studio of 41 entries in the history: pads, pockets, a slot, a through-all hole and a counterbore Hole,
  bosses, a revolve, a groove, ribs, linear, polar and mirror patterns, a draft, fillets and chamfers. Every sketch is fully constrained
  with named datums. Each step is drawn from the seed: 75 % a random in-range change of one of 47 parameters (sketch datums or feature
  properties), 25 % a one-step `PartDesign.studioMove`.
  After each step it compares the result with a full recompute of a saved, reopened copy (every object touched): validity, solid,
  face and edge counts, volume to 1e-6, every face's element name with its area and centre, each feature's volume and state,
  and the error and warning lists. It also times the incremental recompute.
- `FUZZ_HEAL=1` undoes a step that turns a feature red, and checks that the undo restores the part as it was before the step.
  Without it, red states pile up within a few dozen steps and hide later finds.
- `reduce.py`: replays a seed log's steps on a fresh studio and minimises them to the smallest prefix that still fails:
  `RED_TARGET=<object>` (it ends Invalid), or `RED_MODE=revert` (the last step and its undo don't restore the part).
- `repro_f1.py`, `repro_f2.py`: the designed reproducers of ops#814 and ops#818.

Run (FreeCADCmd from a build, `FREECAD_USER_HOME` an absolute folder that exists):

```
FUZZ_SEED=1 FUZZ_STEPS=200 FUZZ_HEAL=1 FUZZ_OUT=/abs/out FreeCADCmd tools/fuzz/fuzz.py
RED_LOG=/abs/out/seed1.jsonl RED_LAST=<step> RED_MODE=revert FreeCADCmd tools/fuzz/reduce.py
```

Options: `FUZZ_STOP=<k>` saves the document after step k; `FUZZ_ONLY=param|move` keeps one kind of step without changing the random
stream; `FUZZ_TAG` names the outputs. A failing step saves its incremental state as `<tag>-fail<k>.FCStd`. One seed of 200 steps
takes about 5 minutes on a Mac, so this is a tool, not a CI test.
