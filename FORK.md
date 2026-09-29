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
| `infra/fork-md` | infra | ops#4 | - | `integration` `e1459baf2d` | `b4e1a97e35` (fork PR 6), 2026-09-28 | never |
| `fix/23-app-gtests` | fix | ops#23 | - | `integration` `e1459baf2d` | `53d927998a` (fork PR 7), 2026-09-28 | a new base fixes `MappedName::compare` and has V2 expectations in the ElementMap gtests |
| `fix/28-extrusion-top-face-name` | fix | ops#28 | - | `integration` `e1459baf2d` | `f34168b953` (fork PR 8), 2026-09-28 | the base's V2 fallback names partners of unmapped inputs |
| `fix/16-retag-decode-cache` | fix | ops#16 | - | `integration` `53d927998a` | `8a62d174c6` (fork PR 10), 2026-09-28 | a new base's `ElementMap::retagElementMap` leaves the decode cache alone and its V2 `setPyObject` tags Python features' new elements |
| `infra/ci-speed` | infra | ops#31 | - | `integration` `8a62d174c6` | `3dfeec5dc6` (fork PR 9), 2026-09-28 | never |
| `fix/17-map-history-algorithm` | fix | ops#17 | - | `fix/16-retag-decode-cache` `d5673ef901` (stacked on fork PR 10) | `ef27cddb23` (fork PR 11), 2026-09-28 | a new base's `Data::ElementMap` holds its history algorithm by value, not a pointer to a shape's field |
| `fix/24-compound-unmapped-children` | fix | ops#24 | - | `integration` `8a62d174c6` | `7c5527237e` (fork PR 12), 2026-09-28 | a new base's V2 `ElementMap::addChildElements` names the elements of children without an element map |
| `infra/ccache-windows-size` | infra | ops#37 | - | `integration` `ef27cddb23` | `17b75bac6a` (fork PR 15), 2026-09-28 | never |
| `fix/32-feature-result-tags` | fix | ops#32 | - | `integration` `ef27cddb23` | (fork PR 14) | a new base's Part and PartDesign features build their results with `makeTopoShape` (own ID in V2, the document's algorithm), and map-less shapes and their sub-shapes carry the document's algorithm |

## Fork-only commits in carried topics

| Commit | Topic | What | Drop or revisit when |
|---|---|---|---|
| `9e1049b3b7` | `carry/wirejoiner` | Tests: adapt `WireJoinerTest.setOpenWiresOnly` to V2 naming. The "has a mapped name" check covers edges only (V2 leaves the result's vertices unnamed, ops#21), and the compared wires get the same tag (V2 split pieces carry the result's tag). | ops#21 is fixed: restore the vertex check. Dropped with the topic. |
