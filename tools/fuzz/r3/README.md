# R3 batch for oracle 26 (ops#640)

- `T1.json`, `T2.json`, `T3.json`, `T5f.json`, `T5c.json`: each template as an ordered Onshape feature list. Every number is
  an expression over NAMED parameters (`#name`; defaults in `params`). Make the parameters Onshape variables and
  regenerate per row; never replay the edits.
- `rows.txt`: one state per line, `T<n> {p:v,...} edit_tail | FreeCAD: <why> V=<mm3> A=<mm2> red=<features>`. `edit_tail` is the
  walk's last edit (context only). The rows are the truth walk's BEYOND states (past a formula's limit, or within
  1e-3 mm of a case boundary), at most 60, an even share per template. Report per row: V, A, face count, each feature's state.
- Regenerate: `python3 make_r3.py templates .` and `python3 make_r3.py rows . <truth jsonl>...`. The walks are `truth.py`.
