# FreeCAD-CH

FreeCAD-CH is a personal FreeCAD fork for Crawlspace Habitats LLC. It is built on
`upstream PR 31040` (V2 topological naming) and adds carried upstream changes, its own
fixes, and CI for Windows and macOS. It is not a FreeCAD release and is not meant for
general use. `ops#N` refers to the fork's private tracker.

This file lists what the fork adds to its base: every topic merged into `integration`,
and every commit in a carried topic that its upstream source doesn't have.

## Base

`base` (`9bf8437a11`) is:
- the head of `upstream PR 31040` (`fd2b469a32`, merge base with main `1ae6ec1fed`);
- main's build environment (OCCT 8.0.1, Qt 6.11), cherry-picked: `upstream PR 29611`
  (`dd4158418a`), 17 of the 18 commits of `upstream PR 32431` (`d1e6b37214` had nothing
  to change) and two pixi-only commits;
- two fixes to the PR's own code for C++23 and OCCT 8: `61d1ee763c` (MappedName's
  string section fields default to `"0"`) and `9bf8437a11` (OCCT includes in
  `SketchObject.cpp`).

## Topics

Each topic reaches `integration` through an in-fork PR with CI on Windows and macOS,
as a `--no-ff` merge, and its PR adds the topic's row here. "Starts from" is where the
branch was cut; a topic that starts from `integration` builds on the topics merged
before it. A topic's merge commit is the first-parent commit on `integration` that
names it.

| Topic | Type | Issue | Upstream source | Starts from | Merged | Drop when |
|---|---|---|---|---|---|---|
| `infra/ci` | infra | ops#8 | - | `base` | `b69bf98d21` (fork PR 1), 2026-09-28 | never; redo the trim on a new base |
| `infra/known-failures` | infra | ops#22 | - | `integration` `b69bf98d21` (needs `infra/ci`) | `cebac682fc` (fork PR 3), 2026-09-28 | never; each list file leaves with its issue |
| `carry/wirejoiner` | carry | ops#9 | `upstream PR 32943`: `3eeaee52fd`, `055ce2e59c` (cherry-picked unchanged as `6c3437ffb9`, `89a037fde4`) | `base` | `9ee6fe36ff` (fork PR 2), 2026-09-28 | a new base contains `upstream PR 32943` |
| `fix/23-elementmapversion-guards` | fix | ops#23 | - | `integration` `cebac682fc` (needs `infra/known-failures`) | `e1459baf2d` (fork PR 5), 2026-09-28 | a new base's naming tests no longer use `ElementMapVersion` |
| `infra/fork-md` | infra | ops#4 | - | `integration` `e1459baf2d` | adds this file | never |
| `fix/16-retag-decode-cache` | fix | ops#16 | - | `integration` `53d927998a` | fork PR 10, open | a new base's `ElementMap::retagElementMap` leaves the decode cache alone and its V2 `setPyObject` tags Python features' new elements |

## Fork-only commits in carried topics

| Commit | Topic | What | Drop or revisit when |
|---|---|---|---|
| `9e1049b3b7` | `carry/wirejoiner` | Tests: adapt `WireJoinerTest.setOpenWiresOnly` to V2 naming. The "has a mapped name" check covers edges only (V2 leaves the result's vertices unnamed, ops#21), and the compared wires get the same tag (V2 split pieces carry the result's tag). | ops#21 is fixed: restore the vertex check. Dropped with the topic. |
