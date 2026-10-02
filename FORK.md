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
| `fix/32-feature-result-tags` | fix | ops#32 | - | `integration` `ef27cddb23` | `d68d671704` (fork PR 14), 2026-09-28 | a new base's Part and PartDesign features build their results with `makeTopoShape` (own ID in V2, the document's algorithm), and map-less shapes and their sub-shapes carry the document's algorithm |
| `fix/34-retag-copy-on-write` | fix | ops#34 | - | `integration` `d68d671704` | `79900a5d13` (fork PR 13), 2026-09-29 | a new base's V2 `TopoShape::reTagElementMap` retags a copy of a shared element map |
| `fix/38-retag-later-names` | fix | ops#38 | - | `fix/34-retag-copy-on-write` `92d2bc402f` (stacked on fork PR 13) | `50e3c9974a` (fork PR 16), 2026-09-29 | a new base's V2 `ElementMap::retagElementMap` retags every name of an element, not only its first |
| `fix/35-body-maplless-tip` | fix | ops#35 | - | `fix/34-retag-copy-on-write` `92d2bc402f` (stacked on fork PR 13) | `578719b853` (fork PR 17), 2026-09-29 | a new base's `PropertyPartShape::setValue` names another object's map-less shape (V2) and V1's `reTagElementMap` copies before retagging |
| `fix/18-update-all-references` | fix | ops#18 | - | `fix/38-retag-later-names` `3bc926af25` (stacked on fork PR 16) | `0075d4a0db` (fork PR 18), 2026-09-29 | a new base's `PropertyLinkBase::updateAllElementReferences` runs (no inverted null check) |
| `fix/43-applyfillet-float-asserts` | fix | ops#43 | - | `integration` `0075d4a0db` | `63238ba44b` (fork PR 19), 2026-09-29 | a new base's `TestTopologicalNamingProblem` compares bounding boxes within tolerance |
| `fix/23-part-sketcher-gtests` | fix | ops#23 | - | `integration` `0075d4a0db` | `1027f33402` (fork PR 20), 2026-09-29 | a new base has V2 expectations in the Part and Sketcher naming gtests |
| `infra/ccache-macos-size` | infra | ops#48 | - | `integration` `1027f33402` | `6a7697fba9` (fork PR 22), 2026-09-29 | never |
| `fix/46-generated-group-type` | fix | ops#46 | - | `integration` `1027f33402` | `ac1596508c` (fork PR 23), 2026-09-29 | a new base gives each member of a V2 generated group its own type |
| `fix/47-bspline-face-names` | fix | ops#47 | - | `fix/46-generated-group-type` `1da0597359` (stacked on fork PR 23) | `012c1bec8e` (fork PR 24), 2026-09-29 | a new base's `makeElementBSplineFace` names its V2 face as generated from the input edges and passes `keepBezier` through when splitting a closed edge |
| `fix/40-xlink-shadows` | fix | ops#40 | - | `integration` `63238ba44b` | `530de69c35` (fork PR 21), 2026-09-29 | a new base's `PropertyXLink::restoreLink` and `detach` keep the saved shadows |
| `fix/19-name-dump` | fix | ops#19 | - | `integration` `012c1bec8e` | `cc4dae6627` (fork PR 25), 2026-09-29 | never (fork tests and the seed wrapper) |
| `fix/19-naming-order` | fix | ops#19 | - | `fix/19-name-dump` `a2e376f6f9` (stacked on fork PR 25) | `ea53409351` (fork PR 26), 2026-09-29 | a new base writes V2 names in a defined order and sorts their list fields |
| `infra/ccache-windows-2g` | infra | ops#51 | - | `integration` `ea53409351` | `168dddb8a9` (fork PR 27), 2026-09-30 | never |
| `fix/39-copied-input-tags` | fix | ops#39 | - | `integration` `ea53409351` | `c4be03798e` (fork PR 28), 2026-09-30 | a new base's PartDesign Boolean, Transformed and Pipe build V2 results with their own ID, and `Part::Mirroring` keeps the names of a placed source |
| `feat/scenarios` | feat | ops#5 | - | `integration` `168dddb8a9` | `11d4740c80` (fork PR 29), 2026-09-30 | never (fork tests); the `NamingMultiMatch` switch when the Phase 4 checkpoint decides the multi-match flags |
| `fix/5-score-lines` | fix | ops#5 | - | `integration` `11d4740c80` | `826ad36e22` (fork PR 30), 2026-09-30 | never (fork tests) |
| `fix/52-masker-tag-collision` | fix | ops#52 | - | `integration` `826ad36e22` | `0e0a3239c1` (fork PR 31), 2026-09-30 | never (fork tests) |
| `fix/21-faceless-vertices` | fix | ops#21 | - | `integration` `826ad36e22` | `003d9452cd` (fork PR 32), 2026-09-30 | a new base's V2 `makeShapeWithElementMap` names a vertex without history and without a named face from its edges |
| `feat/scenarios-2` | feat | ops#5 | - | `fix/52-masker-tag-collision` `c617fd1538` (stacked on fork PR 31) | `397c4dd172` (fork PR 33), 2026-09-30 | never (fork tests) |
| `fix/23-map-counts` | fix | ops#23 | - | `feat/scenarios-2` `27035b42d7` (merged as fork PR 33) | `341696754f` (fork PR 34), 2026-09-30 | a new base's pattern and naming tests check names without counting the map |
| `fix/41-maplless-retag` | fix | ops#41 | - | `integration` `397c4dd172` | `3cff80eb71` (fork PR 35), 2026-09-30 | a new base's V2 `TopoShape::reTagElementMap` names another object's shape without an element map |
| `fix/23-fillet-relink` | fix | ops#23 | - | `fix/23-map-counts` `c63d279c79` (stacked on fork PR 34) | `777be76005` (fork PR 36), 2026-09-30 | never (fork tests); its ops#7 list entries leave when Task 2 relinks to a map-less base |
| `infra/ccache-prune` | infra | ops#57, ops#58, ops#59 | - | `integration` `777be76005` | `b298ed7160` (fork PR 37), 2026-09-30 | never |
| `feat/scenarios-3` | feat | ops#5 | - | `integration` `777be76005` | `fff257dde8` (fork PR 38), 2026-09-30 | never (fork tests) |
| `feat/scenarios-4` | feat | ops#5 | - | `feat/scenarios-3` `469242d629` (stacked on fork PR 38) | `846adf50d0` (fork PR 40), 2026-09-30 | never (fork tests) |
| `fix/12-pd-fillet-tolerance` | fix | ops#12 | - | `integration` `777be76005` | `158154064a` (fork PR 39), 2026-09-30 | upstream stops limiting fillet and chamfer tolerances after `BRepAlgo::IsValid`, and fails a result the repair can't make valid |
| `fix/61-binder-facemaker` | fix | ops#61 | - | `integration` `846adf50d0` | `a36ea876c9` (fork PR 41), 2026-09-30 | a new base whose naming PR restores the `_Version >= 3` face-maker gate in `SubShapeBinder::update` |
| `fix/13-preview-null-crash` | fix | ops#13 | - | `integration` `158154064a` | `33f83dec42` (fork PR 42), 2026-09-30 | a new base whose `ViewProviderPreviewExtension` checks its nodes before `extensionAttach()` |
| `feat/scenarios-5` | feat | ops#5 | - | `integration` `158154064a` | `ac43f08826` (fork PR 43), 2026-09-30 | never (fork tests) |
| `carry/polyline-fillet` | carry | ops#10 | `upstream PR 32430`: `f705304460` (cherry-picked unchanged as `03629c6744`) | `integration` `a36ea876c9` | `6a6d9ed29b` (fork PR 44), 2026-09-30 | a new base contains `upstream PR 32430` |
| `carry/constraint-names` | carry | ops#11 | `upstream PR 32947`: `15ce0c8d3f` (main: `9f17ec6861`; cherry-picked unchanged as `6d1ce2205d`) | `integration` `33f83dec42` | `c81649b0bc` (fork PR 45), 2026-09-30 | a new base contains `upstream PR 32947` (main `9f17ec6861`) |
| `feat/scenarios-5b` | feat | ops#5 | - | `integration` `ac43f08826` | `322d30842f` (fork PR 46), 2026-09-30 | never (fork tests) |
| `fix/14-windows-test-path` | fix | ops#14 | - | `integration` `322d30842f` | `d067e0ed44` (fork PR 47), 2026-09-30 | a new base builds the Windows test PATH without a configure-time glob of `build/Mod/*` |
| `feat/naming-id` | feat | ops#6 | - | `integration` `322d30842f` | `2e1653d882` (fork PR 49), 2026-09-30 | never (fork feature) |
| `feat/solver-evidence` | feat | ops#7 | - | `integration` `2e1653d882` | `29ee051d75` (fork PR 50), 2026-10-01 | never (fork feature) |
| `fix/82-dressup-insert` | fix | ops#82 | - | `integration` `29ee051d75` | `e66195d824` (fork PR 55), 2026-10-01 | a new base's `DressUp::onChanged` moves `BaseFeature` only when `Base` is linked to another object |
| `feat/solver-headers` | feat | ops#7 | - | `feat/solver-evidence` `e681348502` (fork PR 50) | `da9a48830c` (fork PR 51), 2026-10-01 | never (fork feature) |
| `fix/83-windows-near-macro` | fix | ops#83 | - | `integration` `29ee051d75` | `fe2cabbdf1` (fork PR 52), 2026-10-01 | a new base has no lambda named `near` in these tests |
| `fix/84-dressup-panel-accept` | fix | ops#84 | - | `fix/82-dressup-insert` `6e3ad93d91` (stacked on fork PR 55) | `b3034b9aa5` (fork PR 56), 2026-10-01 | a new base's dress-up task panel keeps `Base`, its list and `BaseFeature` on the same shape after an insert |
| `fix/79-strict-vertex-match` | fix | ops#79, ops#20 | - | `integration` `29ee051d75` | `66a2d6ff47` (fork PR 53), 2026-10-01 | a new base's V2 `doNamesMatch` stops accepting a vertex on one shared ID when several candidates do, and warns on guessed references |
| `infra/identity` | infra | ops#15 | - | `fix/83-windows-near-macro` `caa75a92e2` (stacked on fork PR 52) | `79a0abfb78` (fork PR 48), 2026-10-01 | never (fork identity) |
| `fix/60-consumers-getfaces` | fix | ops#60, ops#65 | - | `integration` `66a2d6ff47` | `1de0634ad8` (fork PR 58), 2026-10-01 | a new base's `DressUp::getFaces` fails on a missing face and pairs each sub-name with its own shadow |
| `feat/solver-core` | feat | ops#7 | - | `feat/solver-headers` `96418bd25c` (fork PR 51) | `3249276a50` (fork PR 54), 2026-10-01 | never (fork feature) |
| `feat/solver-geometry` | feat | ops#7 | - | `feat/solver-core` `503a9b2ba2` (fork PR 54) | `15d80f6f76` (fork PR 57), 2026-10-01 | never (fork feature) |
| `feat/solver-consumers` | feat | ops#7, ops#66, ops#68 | - | `feat/solver-geometry` `f674615613` (fork PR 57) | `3d6266c1c8` (fork PR 59), 2026-10-01 | never (fork feature) |
| `feat/solver-relink` | feat | ops#7 | - | `feat/solver-consumers` `e140c865e1` (fork PR 59) | `0cb280a74d` (fork PR 60), 2026-10-01 | never (fork feature) |
| `fix/69-consumers-loud` | fix | ops#69, ops#70, ops#71 | - | `integration` `0cb280a74d` | `fa4ec55a11` (fork PR 61), 2026-10-01 | a new base's SubShapeBinder, `ProfileBased::getProfileShape`, Loft and Pipe fail on a missing sub-element and name it |
| `fix/72-sketch-external-loud` | fix | ops#72, ops#75 | - | `integration` `0cb280a74d` | `004b400470` (fork PR 62), 2026-10-01 | a new base's sketch fails on a missing external geometry reference and keeps the link, its frozen geometry and constraints (also on opening it) |
| `fix/55-duplicate-count` | fix | ops#55 | - | `integration` `004b400470` | `6b0289adb6` (fork PR 64), 2026-10-01 | tests: V2 duplicate counts and pattern instance names (gtests); two patterns of one original whose references move between them (scenarios, listed as known failures for Task 1) |
| `fix/86-sketcher-partdesign-guard` | fix | ops#86 | - | `integration` `004b400470` | `806324817d` (fork PR 65), 2026-10-01 | tests: the Sketcher tests' PartDesign guard (`BUILD_PART_DESIGN`), and V2/ops#72 expectations for the three of them that then failed |
| `feat/solver-splits` | feat | ops#7 | - | `integration` `0cb280a74d` | `3218449813` (fork PR 63), 2026-10-01 | never (fork feature) |
| `feat/solver-splits-arcs` | feat | ops#7 | - | `feat/solver-splits` `0ce71ded00` (fork PR 63) | `ae3c586008` (fork PR 66), 2026-10-01 | never (fork feature) |
| `fix/27-v2-element-history` | fix | ops#27 | - | `integration` `806324817d` | `5054da5c2b` (fork PR 67), 2026-10-01 | the base's `getElementHistory` reads V2 names' sections |
| `feat/solver-gate` | feat | ops#7, ops#87 | - | `feat/solver-splits-arcs` `0ce556ea66` (fork PR 66) | `2af4d842d2` (fork PR 68), 2026-10-01 | never (fork feature) |
| `fix/62-element-map-version` | fix | ops#62 | - | `integration` `2af4d842d2` | (fork PR 69) | a new base's `Document::onChanged` refreshes the element map version when `HistoryAlgorithm` changes |

## Fork-only commits in carried topics

| Commit | Topic | What | Drop or revisit when |
|---|---|---|---|
| `9e1049b3b7` | `carry/wirejoiner` | Tests: adapt `WireJoinerTest.setOpenWiresOnly` to V2 naming: the compared wires get the same tag (V2 split pieces carry the result's tag). It also limited the "has a mapped name" check to edges (V2 left the result's vertices unnamed); `fix/21-faceless-vertices` restored the vertex check (ops#21). | Dropped with the topic. |
| `5e89db8043` | `carry/polyline-fillet` | Test: `TestPolylineFilletGui` (in `TestSketcherGui`; the upstream PR has none) draws a polyline with the tool's fillet option and checks it keeps every clicked point (ops#10). | When the topic is dropped, keep the test (it moves to its own topic) unless upstream adds one. |
| `17f67653f2` | `carry/constraint-names` | Test: `TestAutoScaleNamesGui` (in `TestSketcherGui`; the upstream PR has none) sets a sketch's only dimension through the datum dialog and checks that the auto-scale keeps every constraint's name (ops#11). | When the topic is dropped, keep the test (it moves to its own topic) unless upstream adds one. |
