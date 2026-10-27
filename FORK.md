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
| `fix/62-element-map-version` | fix | ops#62 | - | `integration` `2af4d842d2` | `4782d97247` (fork PR 69), 2026-10-01 | a new base's `Document::onChanged` refreshes the element map version when `HistoryAlgorithm` changes |
| `feat/naming-table` | feat | ops#6, ops#63 | - | `integration` `4782d97247` | `c3e4da5153` (fork PR 71), 2026-10-02 | never (fork feature) |
| `feat/naming-trf` | feat | ops#6, ops#55 | - | `integration` `2af4d842d2` | `f356d6f416` (fork PR 70), 2026-10-02 | never (fork feature) |
| `feat/naming-map` | feat | ops#6, ops#64 | - | `feat/naming-table` `6c2085c074` (fork PR 71) | `4207e545d0` (fork PR 72), 2026-10-02 | a new base's `MappedName::hash` hashes data followed by postfix (ops#64); otherwise never (fork feature) |
| `feat/solver-fingerprint-cache` | feat | ops#90 | - | `integration` `4207e545d0` | `5987bb8041` (fork PR 74), 2026-10-02 | never (fork feature) |
| `feat/naming-intern-switch` | feat | ops#6 | - | `integration` `4207e545d0` | `0bade44a24` (fork PR 73), 2026-10-02 | never (fork feature) |
| `feat/naming-intern-readers` | feat | ops#6 | - | `integration` `0bade44a24` | `8951693731` (fork PR 76), 2026-10-02 | never (fork feature) |
| `feat/naming-intern-save` | feat | ops#6 | - | `integration` `8951693731` (branched at `4401e35c01`, fork PR 76's head) | `1df3c779aa` (fork PR 77), 2026-10-02 | never (fork feature) |
| `feat/naming-trf-steps` | feat | ops#6 | - | `integration` `8951693731` | `fae92bde64` (fork PR 75), 2026-10-02 | never (fork feature) |
| `fix/92-scenario-lists` | fix | ops#92, ops#94, ops#89 | - | `feat/naming-trf-steps` `4cba1ebdea` (stacked on fork PR 75) | `37c04b26f1` (fork PR 78), 2026-10-02 | never (fork tests) |
| `fix/91-trf-followups` | fix | ops#91, ops#95 | - | `integration` `37c04b26f1` | `c0d01ea729` (fork PR 79), 2026-10-02 | never (fork naming) |
| `fix/96-interning-review` | fix | ops#96, ops#97 | - | `integration` `37c04b26f1` | `527461eabb` (fork PR 81), 2026-10-02 | never (fork naming) |
| `fix/98-macos-about` | fix | ops#98 | - | `integration` `37c04b26f1` | `4cb1cf4671` (fork PR 83), 2026-10-02 | never (fork identity) |
| `infra/85-release-redraft` | infra | ops#85 | - | `integration` `37c04b26f1` | `0e56d912a2` (fork PR 82), 2026-10-02 | never |
| `feat/naming-intern-load` | feat | ops#6 | - | `integration` `1df3c779aa` | `488aab941e` (fork PR 80), 2026-10-02 | never (fork feature) |
| `fix/25-fallback-second-pass` | fix | ops#25 | - | `integration` `0e56d912a2` | `73031cb7fd` (fork PR 86), 2026-10-02 | a new base's V2 fallback names a face whose edges it names in the same pass |
| `fix/97-interning-load-notes` | fix | ops#97 | - | `integration` `488aab941e` | `c5b3dae032` (fork PR 85), 2026-10-02 | never (fork naming) |
| `fix/45-49-naming-bundle-b` | fix | ops#45, ops#49 | - | `integration` `73031cb7fd` | `2d10bfb7bc` (fork PR 87), 2026-10-02 | a new base names offsets independently of OCCT's face order and checks compound child ranges |
| `fix/26-33-maps-upstream-features` | fix | ops#26, ops#29, ops#33 | - | `integration` `0e56d912a2` | `27b82b9bbc` (fork PR 84), 2026-10-02 | a new base builds Helix, ShapeBinder and Part::Face with element maps |
| `feat/7-solver-default` | feat | ops#7 | - | `integration` `27b82b9bbc` | `26e3ca1638` (fork PR 88), 2026-10-03 | never (fork feature) |
| `fix/73-77-74-feature-bundle` | fix | ops#73, ops#77, ops#74 | - | `integration` `26e3ca1638` | `8686684521` (fork PR 89), 2026-10-03 | a two-sided up-to side that lands behind its face errors; the dead BaseFeature reorder removed; Part::Fillet/Chamfer erase UB removed |
| `feat/101-v2i-insert-speed` | feat | ops#101, ops#6 | - | `integration` `26e3ca1638` | `44592fd8cf` (fork PR 90), 2026-10-03 | never (fork naming) |
| `fix/42-53-variant-links` | fix | ops#42, ops#53 | - | `integration` `26e3ca1638` | `583b7a429b` (fork PR 91), 2026-10-03 | references through a Link follow its new target (joints on variant or retargeted links reopen); a variant link's sync recomputes its new copies |
| `fix/67-80-gui-minors` | fix | ops#67, ops#80 | - | `integration` `583b7a429b` | `f4bdbfaa11` (fork PR 92), 2026-10-03 | the base's Mass Properties panel removes a row whose subname contains a vertical bar (keep `TestMeasureGui`); its `TestConstraintPreselectionGui` counts axis hits |
| `fix/108-bbox-triangulation` | fix | ops#108 | - | `integration` `583b7a429b` | `a4068e7b60` (fork PR 93), 2026-10-03 | never (fork test harness) |
| `fix/44-v1-sketch-postfix` | fix | ops#44 | - | `integration` `a4068e7b60` | `6034a05826` (fork PR 94), 2026-10-03 | a new base builds V1 sketch edges, points and `makeElementWires`' wires without the document's hasher (upstream's `g1;SKT` names) |
| `fix/101-v2-open-walk` | fix | ops#101 | - | `integration` `a4068e7b60` | `6c82663a0f` (fork PR 95), 2026-10-03 | never (fork naming) |
| `fix/93-pattern-spacings2` | fix | ops#93 | - | `integration` `6c82663a0f` | `f152316458` (fork PR 96), 2026-10-03 | upstream's `LinearPatternExtension` gives `Spacings2` a default without the `0.0` entry |
| `fix/106-variant-topology` | fix | ops#106 | - | `integration` `6c82663a0f` | `3757a5ec6a` (fork PR 97), 2026-10-03 | never (fork code: the ops#42 retarget is the fork's) |
| `fix/88-solver-multimatch-reopen` | fix | ops#88 | - | `integration` `3757a5ec6a` | `5d00624adf` (fork PR 98), 2026-10-03 | never (fork test harness) |
| `feat/105-tier0-geometry-check` | feat | ops#105 | - | `integration` `5d00624adf` | `c518c48fc4` (fork PR 100), 2026-10-04 | never (fork naming: the reference solver is the fork's) |
| `feat/naming-index-format` | feat | ops#6 | - | `integration` `5d00624adf` | `cafab56b0c` (fork PR 99), 2026-10-04 | never (fork feature) |
| `fix/73-two-sided-inside-error` | fix | ops#73 | - | `integration` `c518c48fc4` | `c07df17bd7` (fork PR 101), 2026-10-04 | a two-sided up-to side whose face lies inside the other side errors on the one-prism path too |
| `fix/109-guard-check-saved` | fix | ops#109 | - | `integration` `cafab56b0c` | `70ab701491` (fork PR 103), 2026-10-04 | never (fork code: the ops#42 retarget and ops#106's guard are the fork's) |
| `fix/6-t2-review-followups` | fix | ops#6 | - | `integration` `cafab56b0c` | `31a5177dae` (fork PR 102), 2026-10-04 | never (fork feature) |
| `feat/6-q6-intern-default` | feat | ops#6 | - | `integration` `31a5177dae` | `475faba478` (fork PR 105), 2026-10-04 | never (fork feature) |
| `fix/56-cross-doc-marker` | fix | ops#56 | - | `integration` `475faba478` | `fd44457837` (fork PR 104), 2026-10-04 | never (fork naming code) |
| `fix/112-binder-support-index` | fix | ops#112 | - | `integration` `fd44457837` | `46b23b4235` (fork PR 106), 2026-10-04 | never (fork naming code) |
| `fix/113-114-gui-tests` | fix | ops#113, ops#114 | - | `integration` `46b23b4235` | `eb0131f1fa` (fork PR 107), 2026-10-04 | never (fork tests) |
| `fix/103-naming-revision-gate` | fix | ops#103 | - | `integration` `eb0131f1fa` | `4c8a6d7101` (fork PR 108), 2026-10-04 | never (fork naming code) |
| `fix/116-consumer-pass` | fix | ops#116 | - | `integration` `4c8a6d7101` | `45e27a79cc` (fork PR 109), 2026-10-05 | never (fork naming code) |
| `fix/97-save-side-limits` | fix | ops#97 | - | `integration` `45e27a79cc` | `1807cbb5ff` (fork PR 111), 2026-10-05 | never (fork naming code) |
| `fix/119-link-unregister` | fix | ops#119, ops#120 | - | `integration` `1807cbb5ff` | `e2372ffd85` (fork PR 110), 2026-10-05 | never (fork naming code) |
| `fix/123-missing-sub-reverse` | fix | ops#123 | - | `integration` `1807cbb5ff` | `ee0c358393` (fork PR 112), 2026-10-05 | never (fork naming code) |
| `fix/125-profile-link-dialog` | fix | ops#125 | - | `integration` `ee0c358393` | `b8175da50d` (fork PR 113), 2026-10-05 | when upstream's link dialog keeps stale sub-elements apart from new picks |
| `feat/127-failure-passthrough` | feat | ops#126, ops#127 | - | `integration` `b8175da50d` | `5b1e893ccd` (fork PR 114), 2026-10-05 | never (fork feature) |
| `feat/127-solver-warnings` | feat | ops#127, ops#107 | - | `integration` `5b1e893ccd` | `97d8ac7f33` (fork PR 115), 2026-10-06 | never (fork naming: the reference solver is the fork's) |
| `feat/127-body-reorder` | feat | ops#127, ops#94 | - | `integration` `97d8ac7f33` | `4c9c124aeb` (fork PR 116), 2026-10-06 | never (fork feature) |
| `feat/127-solver-guesses` | feat | ops#127, ops#107 | - | `integration` | `161447e4a0` (fork PR 117), 2026-10-06 | never (fork feature) |
| `feat/127-picker` | feat | ops#127, ops#125 | - | `feat/127-solver-guesses` `438e976e35` | `2eb8b6ec7a` (fork PR 118), 2026-10-06 | never (fork feature) |
| `fix/130-picker-followups` | fix | ops#130, ops#127 | - | `integration` `2eb8b6ec7a` | `1a1f9d51a9` (fork PR 120), 2026-10-06 | never (fork feature) |
| `feat/127-tree-bar` | feat | ops#127 | - | `integration` `4c9c124aeb` | `1cad8bead0` (fork PR 119), 2026-10-06 | never (fork feature) |
| `feat/127-edit-rollback` | feat | ops#127 | - | `integration` `1cad8bead0` | `b838560813` (fork PR 121), 2026-10-06 | never (fork feature) |
| `fix/139-edit-lock-commands` | fix | ops#139 | - | `feat/127-edit-rollback` `f9f5468453` (stacked on fork PR 121) | `e5d256f9ff` (fork PR 123), 2026-10-06 | never (fork feature) |
| `fix/135-mixed-drag` | fix | ops#135 | - | `fix/139-edit-lock-commands` `ee97064747` (stacked on fork PR 123) | `e7caa6e13c` (fork PR 124), 2026-10-06 | never (fork feature) |
| `fix/128-stale-subelement` | fix | ops#128 | - | `integration` `e7caa6e13c` | `c0892b56a8` (fork PR 125), 2026-10-06 | upstream's `SketchObject::checkSubName` (or `IndexedName::set`) rejects a name whose type isn't the whole text before its index |
| `fix/154-alias-recompute` | fix | ops#154 | - | `integration` `c0892b56a8` | `a419d6b97e` (fork PR 127), 2026-10-06 | upstream's fine-grained recompute follows a Spreadsheet alias edge (`Document::recompute` matching the property an edge's name resolves to, and alias edges kept by name); upstream main `93f831f895` has the bug |
| `fix/155-panel-field-refresh` | fix | ops#155 | - | `fix/154-alias-recompute` `d047f6c90e` (stacked on fork PR 127) | `3bebd8f1a4` (fork PR 128), 2026-10-06 | upstream's `ExpressionSpinBox` (or `ExpressionBinding`) refreshes a bound field when its property changes; upstream main `93f831f895` has the bug |
| `feat/127-guess-policy` | feat | ops#127, ops#133, ops#107 | - | `integration` `2eb8b6ec7a` | `872ffe8fc1` (fork PR 122), 2026-10-06 | never (fork feature) |
| `feat/131-park-projections` | feat | ops#131 | - | `feat/127-guess-policy` `5dde1ed1e0` (stacked on fork PR 122) | `e1823b66e8` (fork PR 126), 2026-10-06 | never (fork feature) |
| `feat/131-parked-marking` | feat | ops#131 | - | `feat/131-park-projections` `464c20fa17` (stacked on fork PR 126) | `8361a07aaf` (fork PR 133), 2026-10-06 | never (fork feature) |
| `fix/143-dressup-delete-key` | fix | ops#143 | - | `integration` `872ffe8fc1` | `1304cce8d0` (fork PR 129), 2026-10-06 | upstream's Std_Delete keeps the object in edit and the groups holding it |
| `fix/160-delete-guard-followups` | fix | ops#160 | - | `fix/143-dressup-delete-key` `262a5d8e9b` (stacked on fork PR 129) | `9759c05714` (fork PR 131), 2026-10-06 | upstream's Std_Delete deletes the rest of a mixed in-edit selection and keeps the object an edit was entered through |
| `carry/144-upstream-gui-fixes` | carry | ops#144 | `upstream PR 32611`: `69b04222cc` (main `6c90c20d38`; cherry-picked unchanged as `0b85071ed6`; its `[[nodiscard]]` commit `2cc82e4449` left out), `upstream PR 32478`: main `07b2d9973d` (as `6c5db7d14d`), `upstream PR 32813`: main `d36eff15a0` (as `7134d0d3be`); fork-only `47abc0c028`, `2d12a4fac7` | `integration` `872ffe8fc1` | `5cf6c77dc9` (fork PR 130), 2026-10-06 | a new base contains main `6c90c20d38`, `07b2d9973d` and `d36eff15a0` |
| `fix/159-expression-field-followups` | fix | ops#159, ops#157, ops#156 | - | `integration` `872ffe8fc1` | `076ad63187` (fork PR 132), 2026-10-06 | upstream's quantity fields show a unitless expression result in their unit and Std_Edit opens an edit transaction; the ops#155 refresh's own follow-ups leave with ops#155 |
| `fix/164-delete-guard-second-view` | fix | ops#164 | - | `integration` `9759c05714` | `d902dc50ae` (fork PR 134), 2026-10-06 | upstream's Std_Delete finds an edit shown in another view and deletes the rest of a mixed in-edit selection |
| `fix/161-broken-external-flag-nits` | fix | ops#161 | - | `integration` `5cf6c77dc9` | `0883f369ce` (fork PR 137), 2026-10-06 | the sketch's broken-link tooltip: one walk of the links per hover, and the elements named as old names |
| `fix/158-parked-target-id` | fix | ops#158 | - | `integration` `8361a07aaf` | `640c4fba6b` (fork PR 135), 2026-10-07 | never (fork feature) |
| `fix/166-parked-marking-nits` | fix | ops#166 | - | `integration` `0883f369ce` | `699c57a8cc` (fork PR 136), 2026-10-07 | never (fork feature) |
| `fix/165-rt-target-id` | fix | ops#165 | - | fork PR 135 `5c70af9d49` | `5071d55b23` (fork PR 138), 2026-10-07 | never (fork feature) |
| `feat/145-dimension-in-place` | feat | ops#145 | - | `integration` `640c4fba6b` | `4bcf3a3e1d` (fork PR 139), 2026-10-07 | never (fork feature). Changes upstream behaviour: opening a sketch no longer turns or fits the view by default (`OrientViewOnEdit`), a new dimension's value is typed at its label and Esc keeps the measured value (`DimensionValueInPlace`), the Dimension tool asks in placement order. Outside Sketcher: `Part/Gui/ViewProviderGridExtension.cpp` (grid guards). Upstream edits to `EditDatumDialog::exec` and `ViewProviderSketch::setEditViewer` will conflict |
| `feat/150-w1-reference-field` | feat | ops#150 | - | `integration` `640c4fba6b` | `ab57bc30de` (fork PR 140), 2026-10-07 | never (fork feature) |
| `fix/167-tier1-same-maker` | fix | ops#167 | - | `integration` `d902dc50ae` | `24a1199c52` (fork PR 141), 2026-10-07 | never (fork feature) |
| `feat/150-w2-single-entry-fields` | feat | ops#150 | - | `feat/150-w1-reference-field` `d0f23f9c6a` (stacked on fork PR 140) | `8020ec49c8` (fork PR 142), 2026-10-07 | never (fork feature) |
| `fix/168-own-twin-lift` | fix | ops#168 | - | `fix/167-tier1-same-maker` `50025eb6e9` (fork PR 141) | `3a47b52e13` (fork PR 143), 2026-10-07 | never (fork feature) |
| `feat/150-w3-profile-regions` | feat | ops#150 | - | `feat/150-w2-single-entry-fields` `10e7208c6e` (stacked on fork PR 142) | `99f0d46e4a` (fork PR 144), 2026-10-07 | never (fork feature) |
| `feat/152-hashname` | feat | ops#152 | - | `integration` `4bcf3a3e1d` | `1f6ccc6636` (fork PR 146), 2026-10-07 | never (fork feature). Upstream edits to `ExpressionParser::parse` (`src/App/Expression.cpp`) or to `AppSpreadsheet.cpp`'s init will conflict |
| `feat/152-display-app` | feat | ops#152 | - | `feat/152-hashname` `8977dcfb18` (fork PR 146) | `414b85b5c4` (fork PR 147), 2026-10-07 | never (fork feature). Upstream edits to `VariableExpression::_toString` (`src/App/Expression.cpp`) will conflict |
| `carry/152-fuzzy-autocomplete` | carry | ops#152 | `upstream PR 30531`: main `2b815ef77d` (cherry-picked unchanged as `10710a6ebc`) | `integration` `4bcf3a3e1d` | `0620397821` (fork PR 145), 2026-10-07 | a new base contains main `2b815ef77d` |
| `fix/170-pipe-hole-helix-panels` | fix | ops#170 | - | `integration` `ab57bc30de` | `dbd0b40f6f` (fork PR 151), 2026-10-07 | upstream fixes all seven (W6-W9 keep the behaviour, ops#150) |
| `fix/152-uses-undo` | fix | ops#152, ops#177, ops#179 | - | `integration` (after fork PRs 146, 147) | `437e9ba684` (fork PR 148), 2026-10-07 | when upstream fixes `PropertySheet::renameObjectIdentifiers` for undo copies and the `_ExprContainers` iteration in `PropertyExpressionEngine.cpp` (drop those parts); the uses helper stays (fork feature) |
| `feat/150-w4-pattern-originals` | feat | ops#150 | - | `integration` `dbd0b40f6f` | `d68294375b` (fork PR 154), 2026-10-07 | never (fork feature) |
| `fix/163-undo-dynamic-props` | fix | ops#163 | upstream issue 32285 (upstream commit f4665aa7b5) | `integration` `ab57bc30de` | `92fbbe9288` (fork PR 150), 2026-10-07 | a new base fixes upstream issue 32285 |
| `feat/152-completion` | feat | ops#152 | - | `integration` (after fork PRs 145, 146) | `74cabd709a` (fork PR 152), 2026-10-07 | never (fork feature); refit when upstream changes `ExpressionCompleter`'s fuzzy model |
| `fix/173-multi-circle-tier1` | fix | ops#173, ops#174 | - | `integration` (`fix/168-own-twin-lift` `f911f50fc3`) | `e31de021cc` (fork PR 149), 2026-10-07 | never (fork feature) |
| `feat/152-panel` | feat | ops#152 | - | `fix/152-uses-undo` `07b3b5894e` (stacked on fork PR 148) | `7b0de5eea3` (fork PR 155), 2026-10-07 | never (fork feature); refit when upstream changes `DockWindowManager`, `MainWindow::setupDockWindows`, `StdWorkbench::setupDockWindows` or `DlgAddProperty` |
| `feat/152-display-gui` | feat | ops#152 | - | `integration` `dbd0b40f6f` | `d4965681c6` (fork PR 153), 2026-10-07 | never (fork feature); refit when upstream changes the display sites (`PropertyItem.cpp`, `SheetModel.cpp`, `SheetTableView.cpp`, `InputField.cpp`, `ViewProviderSketch.cpp`; section 8.3) |
| `feat/150-w5-opacity` | feat | ops#150, ops#186 | - | `integration` `d68294375b` | `50485c0283` (fork PR 156), 2026-10-07 | never (fork feature) |
| `fix/185-variables-followups` | fix | ops#185, ops#188 | - | `integration` `d4965681c6` | `df1c89c675` (fork PR 158), 2026-10-07 | never (fork feature); goes with `feat/152-display-gui` and `feat/152-panel` |
| `fix/168-fix-keeps-names` | fix | ops#168 | - | `integration` `dbd0b40f6f` | `c10f794a1c` (fork PR 157), 2026-10-07 | never (fork feature) |
| `feat/150-w6-revolution-helix` | feat | ops#150 | - | `integration` `50485c0283` | `5540399399` (fork PR 159), 2026-10-07 | never (fork feature) |
| `fix/183-t1prime-followups` | fix | ops#183 | - | `integration` (`fix/173-multi-circle-tier1` `2c829d6ff0`) | `ec7262a329` (fork PR 161), 2026-10-07 | never (fork feature) |
| `fix/169-known-failure-lists` | fix | ops#169 | - | `integration` `df1c89c675` | `0d70bced95` (fork PR 162), 2026-10-07 | never (fork feature) |
| `feat/150-w7-loft-pipe-sections` | feat | ops#150 | - | `feat/150-w6-revolution-helix` `d5423e62b9` (stacked on fork PR 159) | `a949fff4df` (fork PR 163), 2026-10-07 | never (fork feature) |
| `fix/190-fixkeepingnames-followups` | fix | ops#190, ops#195 | - | `integration` `0d70bced95` | `57bb8bfe3c` (fork PR 164), 2026-10-07 | never (fork feature) |
| `fix/148-stale-previews` | fix | ops#148 | upstream issues 32414, 24326 | `integration` `ec7262a329` | `7e373c0303` (fork PR 165), 2026-10-07 | a new base fixes upstream issues 32414 and 24326 |
| `fix/146-esc-and-selection-filters` | fix | ops#146, ops#147 | upstream issues 23518, 30992, 28305, 26645 | `integration` `50485c0283` | `9dd9ca6159` (fork PR 160), 2026-10-07 | a new base fixes upstream issues 23518, 30992, 28305 and 26645, and the fork-only choices go with it or are dropped: Clarify Selection on `` ` ``, the filter off in sketch edit and only on element picks, its status-bar button, "No Selection Filters" never clearing a task's gate |
| `feat/150-w8-pipe-paths` | feat | ops#150 | - | `feat/150-w7-loft-pipe-sections` `d3a273613c` (stacked on fork PR 163) | `9c31a0250c` (fork PR 166), 2026-10-07 | never (fork feature) |
| `fix/196-197-followups` | fix | ops#196, ops#197 | - | `integration` `9dd9ca6159` | `bc94aa3404` (fork PR 167), 2026-10-07 | when upstream takes the ops#148 and ops#146 fixes (drop with them) |
| `feat/153-quick-measure` | feat | ops#153 | - | `integration` `9dd9ca6159` | `8e39a53440` (fork PR 168), 2026-10-07 | never (fork feature); refit when upstream changes `QuickMeasure::printResult` or `Measure::Measurement` |
| `feat/150-w9-hole-fields` | feat | ops#150 | - | `feat/150-w8-pipe-paths` `23a6d79be7` (stacked on fork PR 166) | `d162236575` (fork PR 169), 2026-10-07 | never (fork feature) |
| `fix/149-tree-edit-highlight` | fix | ops#149 | upstream issues 20599, 30499 | `integration` `9dd9ca6159` | `5e76a4a186` (fork PR 171), 2026-10-07 | a new base styles the item in edit beyond its background |
| `fix/150-w2-w3-tests` | fix | ops#150 | - | `feat/150-w9-hole-fields` `b66289dc18` (stacked on fork PR 169) | `5da114a060` (fork PR 172), 2026-10-07 | never (fork feature) |
| `fix/198-lcs-plane-placement` | fix | ops#198 | - | `fix/150-w2-w3-tests` `77cae0dfe6` (stacked on fork PR 172) | `84aefc7dba` (fork PR 175), 2026-10-07 | when upstream places a coordinate system's plane in it (`makePlnFromPlane`, `getLCS`) |
| `fix/200-datum-placement` | fix | ops#200 | - | `fix/198-lcs-plane-placement` `e9c7eebc28` (stacked on fork PR 175) | `71897501bf` (fork PR 177), 2026-10-07 | when upstream places a coordinate system's datum elements in it (Attacher, ShapeBinder) |
| `feat/194-keymap-a` | feat | ops#194 | - | `integration` `9dd9ca6159` (fork PR 160's head `531d325e43`) | `d9f9627dd4` (fork PR 170), 2026-10-07 | never (fork feature); refit when upstream changes `ShortcutManager`, `CommandManager::addCommand`, `Command::initAction` or the mapped commands' names |
| `fix/199-sketcher-autoconstraints` | fix | ops#199, ops#172, ops#175 | upstream issues 21334, 30707 | `integration` `5e76a4a186` | `4c741b93b4` (fork PR 176), 2026-10-07 | a new base's `filterRedundantAutoConstraints` keeps the auto constraints that add no redundancy, and `EditDatumDialog::accepted` re-reads the constraint |
| `fix/203-inplace-formula` | fix | ops#203 | none (fork code, ops#145) | `fix/199-sketcher-autoconstraints` `87b6c11675` (stacked on fork PR 176) | `392692de73` (fork PR 179), 2026-10-08 | never (fork code): the in-place field's `=` runs the formula editor and opens the field again |
| `fix/151-error-text` | fix | ops#151 | upstream issues 24567, 21334, 30707 | `integration` `9c31a0250c` | `e66ef51e79` (fork PR 173), 2026-10-08 | never (fork feature); the message changes go when a new base rewords them |
| `feat/149-next-problem` | feat | ops#149 | - | `fix/149-tree-edit-highlight` `db45d6e97c` (stacked on fork PR 171) | `b4a8adad3f` (fork PR 174), 2026-10-08 | never (fork feature) |
| `fix/208-hidden-ancestors` | fix | ops#208 | - | `feat/149-next-problem` `f2e204cb53` (stacked on fork PR 174) | `d99b067e11` (fork PR 180), 2026-10-08 | never (fork fix) |
| `fix/202-banner-followups` | fix | ops#202 | - | `fix/151-error-text` `a5c3ecd5d1` (stacked on fork PR 173) | `e0a7d17b4f` (fork PR 182), 2026-10-08 | never (fork fix) |
| `fix/206-lcs-dependents` | fix | ops#206, ops#207 | - | `integration` `4c741b93b4` | `621669a6ab` (fork PR 181), 2026-10-08 | when upstream recomputes a coordinate system's bare-linked dependants on its move and places its elements in paths through it |
| `fix/209-multirow-problems` | fix | ops#209 | - | `fix/208-hidden-ancestors` `9269739a90` (stacked on fork PR 180) | `5f617f718e` (fork PR 183), 2026-10-08 | never (fork fix) |
| `fix/211-inplace-formula-followups` | fix | ops#211 | none (fork code, ops#145) | `integration` `392692de73` | `06ab4c32e5` (fork PR 186), 2026-10-08 | never (fork code) |
| `feat/194-keymap-d` | feat | ops#194 | - | fork PR 170's head `f5186e0a21` (stacked) | `45ca797def` (fork PR 178), 2026-10-08 | never (fork feature); refit when upstream changes the sketch handlers' key handling (`registerPressedKey`), the tool widgets' labels or the mapped commands' names |
| `fix/184-originals-3d-pick` | fix | ops#184 | - | `integration` `b4a8adad3f` | `e8ad709d94` (fork PR 187), 2026-10-08 | never (fork feature: the Originals field is the fork's) |
| `feat/194-keymap-b` | feat | ops#194 | - | fork PR 178's head `0a839ecc4b` (stacked) | `2d2c878f05` (fork PR 185), 2026-10-08 | never (fork feature); refit when upstream adds commands with these names or keys, or changes the mapped commands' names |
| `feat/194-keymap-c` | feat | ops#194 | - | fork PR 185's head (stacked) | `dd587e77db` (fork PR 189), 2026-10-08 | never (fork feature); refit when upstream changes `Std_ClarifySelection`'s picking or adds a command on the backtick |
| `fix/182-187-189-pattern-minors` | fix | ops#182, ops#187, ops#189, ops#212 | - | `integration` `06ab4c32e5` | `57d4f3dd20` (fork PR 184), 2026-10-08 | when upstream keeps the shown feature by a weak pointer and computes an empty pattern in its edit (ops#182 is fork code: the roll-back bar) |
| `fix/205-datum-type-change` | fix | ops#205 | - | `integration` `45ca797def` | `b8c02a82e5` (fork PR 190), 2026-10-08 | a new base's `EditDatumDialog::accepted` changes the Radius/Diameter type through the property |
| `fix/162-reference-test-gaps` | fix | ops#162 | none (fork code, ops#150) | `integration` `45ca797def` | `35bfb296f7` (fork PR 191), 2026-10-08 | never (fork code) |
| `fix/216-unseen-key-release` | fix | ops#216 | - | `integration` `e8ad709d94` | `918b8fbf22` (fork PR 192), 2026-10-08 | never (fork fix) |
| `fix/215-reference-test-flakes` | fix | ops#215 | none (fork code, ops#150) | `integration` `e8ad709d94` | `a2e660570b` (fork PR 194), 2026-10-08 | never (fork code) |
| `fix/213-next-problem-start` | fix | ops#213 | - | `integration` `45ca797def` | `f66704e59b` (fork PR 188), 2026-10-08 | never (fork fix) |
| `fix/218-edit-end-shown-feature` | fix | ops#218 | - | `fix/182-187-189-pattern-minors` `588f42cef2` (stacked on fork PR 184) | `715d1d5e96` (fork PR 193), 2026-10-08 | never (fork fix) |
| `fix/217-select-other-polish` | fix | ops#217 | - | `fix/216-unseen-key-release` `5d86d00f6e` + `integration` `dd587e77db` (stacked on fork PR 192) | `498ff50527` (fork PR 197), 2026-10-08 | never (fork code) |
| `feat/194-keymap-b2` | feat | ops#194 | - | `integration` `dd587e77db` | `101952b663` (fork PR 195), 2026-10-08 | never (fork feature); refit when upstream changes `View3DInventorViewer::processSoEvent` or the arrow handling in `SoQTQuarterAdaptor` |
| `fix/214-originals-pick-history` | fix | ops#214 | - | `integration` `a2e660570b` | `0ad9fc0b74` (fork PR 196), 2026-10-08 | never (fork feature: the Originals field is the fork's) |
| `fix/193-revolution-update-view-off` | fix | ops#193 | - | `integration` `f66704e59b` | `d5e044c6a4` (fork PR 199), 2026-10-08 | when upstream's `updateUI` no longer returns on `blockUpdate` (the early return is upstream's, in `base`) |
| `fix/221-axis-combo-test-isolation` | fix | ops#221 | none (fork tests) | `integration` `d5e044c6a4` | `6aac1f53ee` (fork PR 200), 2026-10-08 | never (fork tests) |
| `fix/220-esc-autorepeat` | fix | ops#220 | - | `integration` `d5e044c6a4` | `2794a38da5` (fork PR 201), 2026-10-08 | never (fork fix) |
| `fix/204-autoconstraint-followups` | fix | ops#204 | - | `integration` `d5e044c6a4` | `819fdb26db` (fork PR 203), 2026-10-08 | when upstream's auto-constraint filter keeps the automatic constraints that bring no new redundancy |
| `feat/194-keymap-e` | feat | ops#194 | - | fork PR 197's head `df78c6e22b` (stacked) | `53033e161c` (fork PR 198), 2026-10-08 | never (fork feature); refit when upstream changes the sketch's edit-mode preselection (`EditModeCoinManager::detectPreselection`, `ViewProviderSketch::detectAndShowPreselection`) or `Std_ClarifySelection`'s picking |
| `fix/222-esc-record-followups` | fix | ops#222 | - | `fix/220-esc-autorepeat` `55d57d873e` + `integration` `d5e044c6a4` (stacked on fork PR 201) | `b3ae78d04e` (fork PR 205), 2026-10-08 | never (fork fix) |
| `fix/180-pipe-panel-followups` | fix | ops#180 | - | `integration` `d5e044c6a4` | `ea0d025ff5` (fork PR 204), 2026-10-08 | never (fork fix) |
| `fix/223-autoconstraint-review-followups` | fix | ops#223 | - | `integration` `819fdb26db` | `fb2a4a9229` (fork PR 206), 2026-10-08 | when upstream's auto-constraint filter keeps the automatic constraints that bring no new redundancy |
| `fix/219-originals-pick-geometry` | fix | ops#219 | none (fork code, ops#150) | `integration` `d5e044c6a4` | `144785fdd0` (fork PR 202), 2026-10-08 | never (fork code) |
| `fix/192-variables-text-hint` | fix | ops#192 | - | `integration` `fb2a4a9229` | `59652b168e` (fork PR 207), 2026-10-08 | never (fork feature: the Variables panel) |
| `fix/210-lcs-element-global-placement` | fix | ops#210 | - | `integration` `ea0d025ff5` | `3e711888ba` (fork PR 208), 2026-10-08 | when upstream's `getGlobalPlacement` places a coordinate system's elements in it |
| `fix/227-fem-axis-direction` | fix | ops#227 | - | `fix/210-lcs-element-global-placement` `dbfbb898d1` (stacked on fork PR 208) | `c5fd5fbf35` (fork PR 209), 2026-10-08 | when upstream's FEM `Constraint::getDirection` takes an App::Line's direction along its base direction |
| `fix/178-181-rename-move-transactions` | fix | ops#178, ops#181 | - | `integration` `fb2a4a9229` | `800c03ab49` (fork PR 210), 2026-10-08 | Rename part: when upstream's `PropertyEditor` Rename joins a booked transaction and guards its commit; `openPendingTransaction`: never (fork code, fork PR 148) |
| `fix/229-rename-value-rollback` | fix | ops#229 | - | `fix/178-181-rename-move-transactions` `5d982c82f5` (fork PR 210) | `79b75b8f45` (fork PR 212), 2026-10-08 | when upstream's `TransactionObject` keeps a rename and a value change of one property apart (one entry per property ID) |
| `fix/225-pipe-copy-followups` | fix | ops#225 | - | `integration` `144785fdd0` | `307ab9804d` (fork PR 211), 2026-10-08 | never (fork fix) |
| `fix/191-revolution-upto-face-first-solid` | fix | ops#191 | - | `integration` `307ab9804d` | `5b08371dd1` (fork PR 217), 2026-10-08 | when upstream's `Revolved::tryToRevolveToFace` revolves up to a face without a base solid |
| `fix/233-makecopy-external-constraints` | fix | ops#233 | - | `integration` `800c03ab49` | `5169738cd5` (fork PR 215), 2026-10-08 | never (fork fix) |
| `fix/140-sketcher-external-types` | fix | ops#140 | - | `integration` `800c03ab49` | `363bb33ea0` (fork PR 214), 2026-10-08 | when upstream keeps `ExternalTypes` parallel to `ExternalGeometry` and `breakLink` keeps shadows |
| `fix/237-pr214-followups` | fix | ops#237 | - | `fix/140-sketcher-external-types` `1218ee0079` | `1d0e0a37c1` (fork PR 218), 2026-10-08 | with `fix/140-sketcher-external-types` |
| `fix/231-property-editor-transactions` | fix | ops#231 | - | `integration` `800c03ab49` | `db8ad21ceb` (fork PR 213), 2026-10-08 | when upstream's `PropertyEditor` Add/Delete/Move Property and `DlgAddProperty` join a booked transaction and close only their own; `DocumentObject::renameDynamicProperty` completes a rename a handler threw after |
| `fix/235-transaction-rename-order` | fix | ops#235 | - | `integration` `79b75b8f45` (stacked on fork PR 213) | `ecb2ada10a` (fork PR 216), 2026-10-08 | when upstream's `TransactionObject::applyChn` applies entries in a defined order with per-entry error handling |
| `fix/239-revolution-first-solid-followups` | fix | ops#239 | - | `integration` `5169738cd5` | `6089fc009f` (fork PR 220), 2026-10-08 | with the ops#191 row: when upstream's `Revolved::tryToRevolveToFace` revolves up to a face without a base solid |
| `fix/242-revolution-small-base-trim` | fix | ops#242 | - | `fix/239-revolution-first-solid-followups` `f52c8a07bb` (fork PR 220) | `278b805640` (fork PR 221), 2026-10-08 | when upstream's `Revolved::tryToRevolveToFace` gives BRepFeat a base large enough for its up-to face trim |
| `fix/234-pipe-copy-step-followups` | fix | ops#234 | - | `fix/225-pipe-copy-followups` `97d11994a2` | `5206f693a5` (fork PR 219), 2026-10-08 | never (fork fix) |
| `fix/238-transaction-move-del-gaps` | fix | ops#238 | - | `integration` `ecb2ada10a` | `d93605a352` (fork PR 222), 2026-10-08 | when upstream's `Transaction` takes back moves into and out of objects created in the transaction and `moveDynamicProperty` completes a move a handler threw from |
| `fix/230-makecopy-recompute` | fix | ops#230 | - | `integration` `5169738cd5` | `7801f7c453` (fork PR 223), 2026-10-08 | never (fork fix) |
| `fix/236-makecopy-independent-copy` | fix | ops#236, ops#241 | - | `fix/230-makecopy-recompute` `88885d827d` (fork PR 223) | `2bc636bdc4` (fork PR 224), 2026-10-10 | never (fork fix) |
| `fix/243-pipe-recompute-failure` | fix | ops#243 | - | `integration` `2bc636bdc4` | `d360d8c798` (fork PR 226), 2026-10-10 | never (fork fix) |
| `fix/238-transaction-leftovers` | fix | ops#238 | - | `integration` `7801f7c453` | `618939feb7` (fork PR 225), 2026-10-10 | when upstream's `moveDynamicProperty` checks its target's document and keeps the first error, and `Transaction` orders moves back from another document after renames |
| `fix/246-sketcher-3d-edge-geoid` | fix | ops#246 | - | `integration` `2bc636bdc4` | `e84b56e208` (fork PR 228), 2026-10-10 | never (fork fix) |
| `fix/247-sketcher-copy-remap-elements` | fix | ops#247 | - | `integration` `2bc636bdc4` | `f2efbec84c` (fork PR 229), 2026-10-10 | never (fork fix) |
| `fix/250-projection-on-surface-subs` | fix | ops#250 | - | `integration` `d360d8c798` | `63c502ff6b` (fork PR 230), 2026-10-10 | never (fork fix) |
| `fix/244-independent-copy-picks` | fix | ops#244, ops#245 | - | `integration` `2bc636bdc4` | `161adb82e9` (fork PR 227), 2026-10-10 | never (fork fix) |
| `fix/249-part-fillet-stale-edges` | fix | ops#249 | - | `integration` `63c502ff6b` | `83a7885ab1` (fork PR 231), 2026-10-10 | never (fork fix) |
| `fix/260-external-both-ids` | fix | ops#260 | - | `integration` `161adb82e9` | `7532fd2eec` (fork PR 234), 2026-10-10 | never (fork fix) |
| `fix/251-shapebinder-silent-whole` | fix | ops#251 | - | `integration` `618939feb7` | `e2c6bc263d` (fork PR 232), 2026-10-10 | never (fork fix) |
| `fix/248-merge-external-pairing` | fix | ops#248 | - | `integration` `63c502ff6b` | `cf1c5b7b81` (fork PR 233), 2026-10-10 | never (fork fix) |
| `fix/257-part-fillet-edge-links` | fix | ops#257, ops#258 | - | `integration` `83a7885ab1` | `37e8bda261` (fork PR 236), 2026-10-10 | never (fork fix) |
| `fix/261-merge-external-flags` | fix | ops#261 | - | `fix/248-merge-external-pairing` `0dcb49ef80` (stacked on fork PR 233) | `42d9b6e641` (fork PR 238), 2026-10-10 | never (fork fix) |
| `fix/261-merge-expressions` | fix | ops#261 | - | `integration` `161adb82e9` | `e672115cd6` (fork PR 237), 2026-10-10 | never (fork fix) |
| `fix/240-upto-revolution-naming` | fix | ops#240 | - | `integration` `d360d8c798` | `0d49331cf0` (fork PR 235), 2026-10-11 | never (fork fix) |
| `fix/265-fillet-replace-object` | fix | ops#265 | - | `fix/257-part-fillet-edge-links` `614b36a033` (stacked on fork PR 236) | `8b3b308c48` (fork PR 240), 2026-10-11 | never (fork fix) |
| `fix/264-external-ids-per-kind` | fix | ops#264 | - | `integration` `cf1c5b7b81` | `911e04b577` (fork PR 241), 2026-10-11 | never (fork fix) |
| `fix/262-fillet-dialog-followups` | fix | ops#262 | - | `fix/265-fillet-replace-object` `ea656ad7b2` (stacked on fork PR 240) | `957d5e6bc0` (fork PR 242), 2026-10-11 | never (fork fix) |
| `fix/254-symmetric-upto-sector` | fix | ops#254 | - | `fix/240-upto-revolution-naming` `d6547787b9` (fork PR 235) | `23a45e0cf8` (fork PR 239), 2026-10-11 | never (fork fix) |
| `fix/244-binder-global-position` | fix | ops#244 | - | `integration` `e672115cd6` | `1e53a9110f` (fork PR 244), 2026-10-11 | never (fork fix) |
| `fix/244-copy-followups` | fix | ops#244 | - | `fix/244-binder-global-position` `09ebf571d3` (stacked on fork PR 244) | `c95e01f4a5` (fork PR 246), 2026-10-11 | never (fork fix) |
| `fix/268-replace-followups` | fix | ops#268 | - | `integration` `23a45e0cf8` | `ecd1e20a39` (fork PR 247), 2026-10-11 | never (fork fix) |
| `fix/part-minors-256-275` | fix | ops#268 ops#275 ops#256 | - | `fix/268-replace-followups` `75fb4ef8e1` (stacked on fork PR 247) | `7ed101a873` (fork PR 248), 2026-10-11 | never (fork fix) |
| `fix/pd-gui-minors-253-266` | fix | ops#253, ops#266, ops#252, ops#259 | - | `integration` `42d9b6e641` | `d47bd4ee85` (fork PR 245), 2026-10-11 | never (fork fix) |
| `fix/267-merge-copy-followups` | fix | ops#267 | - | `integration` `957d5e6bc0` | `766a1c0f7b` (fork PR 250), 2026-10-11 | never (fork fix) |
| `fix/269-external-kind-followups` | fix | ops#269 | - | `fix/267-merge-copy-followups` `d06f986efa` (stacked on fork PR 250) | `5bf91f795b` (fork PR 251), 2026-10-11 | never (fork fix) |
| `fix/273-part-binder-relink` | fix | ops#273 | - | `integration` `d47bd4ee85` | `80920dae5a` (fork PR 252), 2026-10-11 | never (fork fix) |
| `fix/naming-minors-124-138-176` | fix | ops#176 ops#138 ops#124 ops#268 | - | `integration` `7ed101a873` | `df6a4acece` (fork PR 249), 2026-10-11 | never (fork fix) |
| `fix/sketcher-minors-237-277-278-280` | fix | ops#280, ops#278, ops#277, ops#237, ops#281 | - | `integration` `5bf91f795b` | `24850925c7` (fork PR 253), 2026-10-11 | never (fork fix) |
| `fix/283-carbon-copy-local-mirror` | fix | ops#283 | - | `fix/sketcher-minors-237-277-278-280` `7baf19f5f7` (stacked on fork PR 253) | `000f6639bd` (fork PR 254), 2026-10-11 | never (fork fix) |
| `fix/276-partdesign-gui-minors` | fix | ops#276, ops#252, ops#253 | - | `integration` `000f6639bd` | `0f634bd007` (fork PR 255), 2026-10-11 | never (fork fix) |
| `fix/255-pad-twosided-names` | fix | ops#255 | - | `fix/254-symmetric-upto-sector` `ea7b468173` (stacked on fork PR 239) | `d9a3826388` (fork PR 243), 2026-10-11 | never (fork fix) |
| `fix/134-random-reorder-edits` | fix | ops#134, ops#286 | - | `integration` `000f6639bd` | `e5d14c301b` (fork PR 256), 2026-10-11 | never (fork tests) |
| `fix/284-continuation-collinear` | fix | ops#284 | - | `integration` `000f6639bd` | `7408058275` (fork PR 257), 2026-10-11 | never (fork fix) |
| `fix/284-followups` | fix | ops#284 | - | `fix/284-continuation-collinear` `1e91d07eef` (stacked on fork PR 257) | `551ce8b8a7` (fork PR 258), 2026-10-11 | never (fork fix) |
| `fix/263-multiface-upto-revolve` | fix | ops#263 | - | `integration` `d9a3826388` | `7205d63e11` (fork PR 259), 2026-10-11 | never (fork fix) |
| `fix/283-carbon-copy-followups` | fix | ops#283 | - | `integration` `0f634bd007` | `5a16b71918` (fork PR 260), 2026-10-11 | never (fork fix) |
| `fix/279-collide-one-distinct-ids` | fix | ops#279 | - | `integration` `551ce8b8a7` | `b14000077f` (fork PR 263), 2026-10-11 | never (fork fix) |
| `fix/237-externals-followups` | fix | ops#237 | - | `fix/283-carbon-copy-followups` `af6dd58324` (stacked on fork PR 260) | `0ee3ee9a56` (fork PR 262), 2026-10-11 | never (fork fix) |
| `fix/244-independent-primitive-copy` | fix | ops#244, ops#282 | - | `integration` `0f634bd007` | `e9571e3de2` (fork PR 261), 2026-10-11 | never (fork fix) |
| `fix/166-parked-deleted-mark` | fix | ops#166 | - | `integration` `551ce8b8a7` | `8a87fd8596` (fork PR 265), 2026-10-11 | never (fork fix) |
| `fix/171-parked-paste-source-doc` | fix | ops#171 | - | `fix/166-parked-deleted-mark` `cd1606625c` (fork PR 265) | `04564f6846` (fork PR 266), 2026-10-11 | never (fork fix) |
| `fix/255-followups` | fix | ops#255 | - | `integration` `d9a3826388` | `e4c9812861` (fork PR 264), 2026-10-11 | never (fork fix) |
| `fix/134-round2-nits` | fix | ops#134 | - | `integration` `e4c9812861` | `ce536037cf` (fork PR 271), 2026-10-11 | never (fork fix) |
| `fix/near-macro-release` | fix | ops#294 | - | `551ce8b8a7` | `0d04aa4856` (fork PR 272), 2026-10-11 | never (fork fix) |
| `fix/224-originals-pick-followups` | fix | ops#224 | none (fork code, ops#150; App `getOutList` flag: upstream code) | `integration` `551ce8b8a7` | `4ab57a8148` (fork PR 267), 2026-10-11 | never (fork code) |
| `fix/272-symmetric-across-plane` | fix | ops#272 | - | `integration` `e4c9812861` | `119afa60c2` (fork PR 268), 2026-10-11 | never (fork fix) |
| `fix/285-reorder-cycle-base` | fix | ops#285 | - | `integration` `0ee3ee9a56` | `9e69e1564f` (fork PR 270), 2026-10-11 | never (fork fix) |
| `fix/252-sketcher-minors` | fix | ops#252 | - | `integration` `0ee3ee9a56` | `7e1d79cd66` (fork PR 269), 2026-10-11 | never (fork fix) |
| `fix/276-migrate-element-links` | fix | ops#276 | - | `integration` `e4c9812861` | `1271eefb7b` (fork PR 274), 2026-10-11 | never (fork fix) |
| `fix/171-paste-uncopied-expression` | fix | ops#171 | - | `integration` `e4c9812861` | `918f8ba271` (fork PR 275), 2026-10-11 | never (fork fix) |
| `fix/292-refined-merged-side` | fix | ops#292 | - | `integration` `9e69e1564f` | `5c7276ebd4` (fork PR 276), 2026-10-11 | never (fork fix) |
| `feat/300-fillet-fallback` | feat | ops#300 | - | `integration` `7e1d79cd66` | `6f8eb7477e` (fork PR 278), 2026-10-12 | never (fork feature) |
| `infra/302-ci-timeout-near-guard` | infra | ops#302, ops#294 | - | `integration` `5c7276ebd4` | `e52e7f0bcd` (fork PR 280), 2026-10-12 | never |
| `fix/287-undecided-type-settled` | fix | ops#287 | - | `integration` `7e1d79cd66` | `e7f3b31c22` (fork PR 277), 2026-10-12 | never (fork fix) |
| `fix/297-fillet-validity` | fix | ops#297 | - | `feat/300-fillet-fallback` `07536f4ec8` (fork PR 278) | `32d41c43f1` (fork PR 281), 2026-10-12 | never (fork fix) |
| `feat/300-fillet-corners` | feat | ops#300 | - | `integration` `32d41c43f1` | `61925c451a` (fork PR 283), 2026-10-12 | never (fork feature) |
| `fix/291-reorder-missing-base` | fix | ops#291 | - | `integration` `e52e7f0bcd` | `5414cccbfd` (fork PR 282), 2026-10-12 | never (fork fix) |
| `fix/292-stale-role-links` | fix | ops#292 | - | `integration` `32d41c43f1` | `e1b79b6d9e` (fork PR 284), 2026-10-12 | never (fork fix) |
| `feat/300-fillet-corners-unequal` | feat | ops#300 | - | `integration` `61925c451a` | `e76ce293b2` (fork PR 285), 2026-10-12 | never (fork feature) |
| `feat/300-fillet-s2` | feat | ops#300 | - | `feat/300-fillet-corners-unequal` `9694566e98` (fork PR 285) | `a6ad24584a` (fork PR 286), 2026-10-12 | never (fork feature) |
| `feat/300-fillet-s3` | feat | ops#300 | - | `feat/300-fillet-s2` `e905ac5b46` (fork PR 286) | `4cd9e71421` (fork PR 288), 2026-10-12 | never (fork feature) |
| `fix/292-originals-birth` | fix | ops#292 | - | `fix/292-stale-role-links` (fork PR 284) | `4a00e641fc` (fork PR 287), 2026-10-12 | never (fork fix) |
| `fix/316-refine-locations` | fix | ops#316 | - | `integration` `4a00e641fc` | `09569c55bf` (fork PR 290), 2026-10-12 | never (fork fix) |
| `fix/310-partdesign-location-chains` | fix | ops#310 | - | `fix/316-refine-locations` (fork PR 290) | `746cbb6f2b` (fork PR 291), 2026-10-12 | never (fork fix) |
| `fix/308-cross-body-traps` | fix | ops#308 | - | `integration` `e76ce293b2` | `d624c532ae` (fork PR 289), 2026-10-12 | never (fork fix) |
| `infra/323-fork-release` | infra | ops#323 | - | `integration` `746cbb6f2b` | `75ae590158` (fork PR 293), 2026-10-12 | never |
| `infra/323-compat-gate` | infra | ops#323 | - | `infra/323-fork-release` (fork PR 293) `5a4244c019` | `9351e7c1c6` (fork PR 295), 2026-10-12 | never |
| `fix/319-expression-units` | fix | ops#319, ops#320 | - | `integration` `d624c532ae` | `318a1f8a91` (fork PR 292), 2026-10-12 | never (fork fix) |
| `fix/336-gate-binder-offset` | fix | ops#336 | - | `integration` `318a1f8a91` | `f602eac8ed` (fork PR 298), 2026-10-14 | never |
| `fix/318-attach-frames` | fix | ops#318 | - | `integration` `318a1f8a91` | `d85a820fc9` (fork PR 296), 2026-10-14 | never (fork fix) |
| `fix/318-expression-containers` | fix | ops#318 | - | `fix/318-attach-frames` `79dd9e9831` (stacked on fork PR 296) | `97d4942d03` (fork PR 297), 2026-10-14 | never (fork fix) |
| `fix/289-upto-face-through-profile` | fix | ops#289 | - | `integration` `97d4942d03` | `f9d26cf27a` (fork PR 273), 2026-10-14 | never (fork fix) |
| `fix/293-upto-face-crossed-twice` | fix | ops#293, ops#296 | - | `fix/289-upto-face-through-profile` `6e560b613d` (stacked on fork PR 273) | `647778546a` (fork PR 279), 2026-10-14 | never (fork fix) |
| `fix/338-revolution-followups` | fix | ops#338 | - | `integration` `647778546a` | `b8a85593d7` (fork PR 299), 2026-10-14 | never (fork fix) |
| `feat/305-studio-gates` | feat | ops#325 | - | `integration` `9351e7c1c6` | `6a842fd644` (fork PR 294), 2026-10-14 | never (fork feature) |
| `feat/325-placement-follow` | feat | ops#325, ops#331, ops#324 | - | `feat/305-studio-gates` `e2c718b08a` (stacked on fork PR 294) | `d2f792a682` (fork PR 300), 2026-10-14 | never (fork feature) |
| `feat/325-1b2` | feat | ops#325, ops#314 | - | `integration` `d2f792a682` | `35fbb72308` (fork PR 301), 2026-10-14 | never (fork feature) |
| `feat/325-2a` | feat | ops#325, ops#311 | - | `feat/325-1b2` `5e4ebf2999` (fork PR 301, merged) | `a31fd26aee` (fork PR 302), 2026-10-16 | never (fork feature) |
| `feat/325-2b` | feat | ops#325 | - | `feat/325-2a` `a44ed1dddf` (fork PR 302, merged) | `bf94ac043f` (fork PR 303), 2026-10-17 | never (fork feature) |
| `feat/325-3a` | feat | ops#325 | - | `feat/325-2b` `dca26b0787` (fork PR 303) | `0c1a444ea5` (fork PR 304), 2026-10-17 | never (fork feature) |
| `feat/325-3b` | feat | ops#325 | - | `feat/325-3a` `0be7f310ec` (fork PR 304) | `ae33af5c9c` (fork PR 305), 2026-10-17 | never (fork feature) |
| `fix/342-container-moves` | fix | ops#342 | - | `feat/325-3b` `add23ca198` (fork PR 305) | `9439811c0a` (fork PR 306), 2026-10-17 | never (fork feature) |
| `feat/325-4-split` | feat | ops#325 | - | `integration` `ae33af5c9c` | `f16dbf43bc` (fork PR 308), 2026-10-17 | never (fork feature) |
| `fix/293-q4-tolbase` | fix | ops#293 | - | `integration` `35fbb72308` | `fc14bb9328` (fork PR 307), 2026-10-17 | never (fork fix) |
| `feat/317-describe` | feat | ops#317 | - | `integration` `9439811c0a` | `7e427b347f` (fork PR 310), 2026-10-17 | never (fork feature) |
| `feat/317-onshape-translate` | feat | ops#317 | - | `integration` `9439811c0a` | `d2d57cc48f` (fork PR 309), 2026-10-17 | never (fork feature) |
| `fix/296-upto-face` | fix | ops#304, ops#299 | - | `integration` `d2d57cc48f` | `242c9698d0` (fork PR 311), 2026-10-17 | never (fork fix) |
| `infra/323-compat-b2` | infra | ops#323 | - | `integration` `d2d57cc48f` | `aa54e80f1e` (fork PR 312), 2026-10-17 | never |
| `feat/317-panel-types` | feat | ops#317 | - | `integration` `7e427b347f` | `3dee143ed4` (fork PR 313), 2026-10-17 | never (fork feature) |
| `fix/303-fillet-limits` | fix | ops#303, ops#315 | - | `integration` `aa54e80f1e` | `035baf1bc5` (fork PR 314), 2026-10-17 | never (fork fix) |
| `infra/343-compat-record` | infra | ops#343 | - | `integration` `aa54e80f1e` | `e9c2084ad6` (fork PR 316), 2026-10-17 | never |
| `feat/317-copy-import` | feat | ops#317 | - | `integration` `aa54e80f1e` | `fe5cda1980` (fork PR 315), 2026-10-17 | never (fork feature) |
| `fix/345-dressup-base-tolerances` | fix | ops#345 | - | `integration` `e9c2084ad6` | `8f31aaece8` (fork PR 318), 2026-10-17 | never (fork fix) |
| `feat/317-import-gui` | feat | ops#317 | - | `feat/317-copy-import` `afd57d50cc` (stacked on fork PR 315) + `integration` `e9c2084ad6` | `b363563e2f` (fork PR 317), 2026-10-17 | never (fork feature) |
| `fix/crash-triage` | fix | ops#333, ops#329 | - | `integration` `e9c2084ad6` | `33628cc4d3` (fork PR 319), 2026-10-17 | never (fork fix) |
| `feat/317-oracle-test` | feat | ops#317 | - | `integration` `8f31aaece8` | `33bae7bd4e` (fork PR 320), 2026-10-17 | never (fork feature) |
| `fix/337-attach-poll` | fix | ops#337, ops#332 | - | `integration` `8f31aaece8` | `855d0c0932` (fork PR 323), 2026-10-17 | never (fork fix) |
| `fix/347-upto-tolerances` | fix | ops#347 | - | `integration` `33628cc4d3` | `1b1161843c` (fork PR 321), 2026-10-17 | never (fork fix) |
| `fix/322-basefeature-follows` | fix | ops#322 | - | `integration` `33bae7bd4e` | `a47e001660` (fork PR 322), 2026-10-17 | never (fork fix) |
| `fix/348-varsetcopy-add-property` | fix | ops#348 | - | `integration` `a47e001660` | `b2b1911afc` (fork PR 325), 2026-10-17 | never (fork fix) |
| `fix/353-empty-prism` | fix | ops#353 | fork PR 321 | `fix/347-upto-tolerances` `04ac2ed1bc` | `96ca14805a` (fork PR 324), 2026-10-17 | never (fork fix) |
| `fix/356-upto-overhang` | fix | ops#356 | fork PR 324 | `fix/353-empty-prism` `f1bbcf8b83` | `23165bc6b0` (fork PR 326), 2026-10-17 | never (fork fix) |
| `feat/335-derived-survivors` | feat | ops#335 | - | `integration` `23165bc6b0` | `8d6875f298` (fork PR 327), 2026-10-18 | never (fork feature) |
| `fix/354-refine-in-place` | fix | ops#354 | - | `integration` `23165bc6b0` | `27364d2839` (fork PR 328), 2026-10-18 | never (fork fix) |
| `fix/357-upto-split-followups` | fix | ops#357 | - | `fix/354-refine-in-place` `eaffb0a7cd` (stacked on fork PR 328) | `37ace26da0` (fork PR 331), 2026-10-18 | never (fork fix) |
| `fix/327-cross-body-gui` | fix | ops#327, ops#321, ops#301 | - | `integration` `27364d2839` | `c0ae7379e3` (fork PR 329), 2026-10-18 | never (fork fix) |
| `fix/330-newer-file-lows` | fix | ops#330 | - | `integration` `8d6875f298` | `62575f717f` (fork PR 332), 2026-10-18 | never (fork fix) |
| `fix/362-multifuse-refined-edges` | fix | ops#362 | - | `integration` `62575f717f` | `8d7db92190` (fork PR 333), 2026-10-18 | never (fork fix) |
| `fix/349-cycles-and-poll` | fix | ops#349, ops#352 | - | `integration` `23165bc6b0` | `2c10a1584e` (fork PR 330), 2026-10-18 | never (fork fix) |
| `test/359-derived-survivor-tests` | test | ops#359 | - | `integration` `2c10a1584e` | `4575e65657` (fork PR 334), 2026-10-18 | never (fork tests) |
| `fix/368-startup-newer-file` | fix | ops#368 | - | `integration` `8d7db92190` | `ffd6b0b0a8` (fork PR 335), 2026-10-18 | never (fork fix) |
| `fix/358-offset-gen-evidence` | fix | ops#358 | - | `integration` `4575e65657` | `16c2e39572` (fork PR 336), 2026-10-18 | never (fork fix) |
| `fix/367-migrate-warnings` | fix | ops#367 | - | `integration` `ffd6b0b0a8` | `ee101f5f1e` (fork PR 338), 2026-10-18 | never (fork fix) |
| `feat/351-pipe-end-names` | feat | ops#351 | - | `integration` `4575e65657` | `2e2bb138ba` (fork PR 337), 2026-10-19 | never (fork feature) |
| `fix/244-copy-picks` | fix | ops#244 | - | `integration` `2e2bb138ba` | `23b0fe87d3` (fork PR 343), 2026-10-19 | never (fork fix) |
| `fix/303-dropped-base-parts` | fix | ops#303 | - | `integration` `2e2bb138ba` | `b810473540` (fork PR 341), 2026-10-19 | never (fork fix) |
| `infra/388-release-env` | infra | ops#388 | upstream PR 30068, `fed6d0db9b`, `19eb9fe7d3`, `2354b07b52`, `ec6852e6ca` | `integration` `2e2bb138ba` | `953f76e711` (fork PR 342), 2026-10-19 | upstream commits: at a base that has them; the release check: never |
| `fix/365-main-thread-hooks` | fix | ops#365 | - | `integration` `2e2bb138ba` | `41762ed4ec` (fork PR 347), 2026-10-19 | never (fork fix) |
| `carry/389-upstream-fixes-a` | carry | ops#389 | `upstream PR 32301`: main `5986d3145c` and `a69f2974c2` (as `f26be439d5`, `e5ae44eee1`), main `32c8c3bf0e` (as `0677366c92`), `upstream PR 32850`: main `7ff88754d3` (as `86720dbdf2`, test list adapted, linkage from `994ec17340`), `upstream PR 32794` head `c3b93063b5` (ported as `33f762c097`, warning made visible; `f8c1a8d88d` checks only after a merge), `upstream PR 32879` head `520011f9c5` (ported as `32cb410ab8`); fork-only `b1d7df9f1e` (ops#372), tests `a605ad7fc2`, review round 1 `6375f04287`, round 2 `0f09a496bb`, `60471ebf2e`, `e6161fe9fb`, round 3 `fe5f2d5c34`, `4e4d104eda` | `integration` `2e2bb138ba` | `19b2300169` (fork PR 345), 2026-10-20 | a new base contains main `5986d3145c`, `a69f2974c2`, `32c8c3bf0e`, `7ff88754d3` and upstream PRs 32794 and 32879 (or their replacements) |
| `carry/390-upstream-fixes-b` | carry | ops#390 | main `c1c0b50621` (`upstream PR 33177`, as `48a080990e`), `84ae7a7c8e` (`upstream PR 33054`, as `53f6cbc354`, with its gtest), `33d332e273` (`upstream PR 33055`, ported as `783fb930b3`), `0b6ffa245a` (`upstream PR 33045`, as `806d29a36a`), `dc53a2036d` (`upstream PR 32989`, as `bf45940f9b`), `55c36e8c03` (`upstream PR 32457`, as `23dd6ca004`), `fab8e1af6a`, `5f05c77ea9`, `0ecfd89f62`, `3d899008bf`, `100bd750ce` (`upstream PR 33046`, as `414f9254b7`, `67ff785b7e`, `76bbef8d25`, ported `f06d776720`, `3926e51091`), `upstream PR 33716` head `cd588f4212` (open, approved; as `af569107fd`), `upstream PR 33209` head `0c1d1eaee0` (as `6244affe0b`), `e9b474306f` (`upstream PR 33402`, as `67b19c059f`), `084379651a` (`upstream PR 32459`, as `4c29d5c456`), `44a68a0046` (`upstream PR 32737`, ported as `17ede50493`); tests `ffd69ae7e0`, `985f77cff5` | `integration` `953f76e711` | `b0b066502e` (fork PR 349), 2026-10-20 | a new base contains these commits (upstream PRs 33716 and 33209 or their replacements) |
| `fix/393-dressup-pocket` | fix | ops#393 | - | `integration` `2e2bb138ba` (needs `fix/303-dropped-base-parts`, fork PR 341) | `4f191bb942` (fork PR 346), 2026-10-20 | never (fork fix) |
| `fix/121-notification-reentry` | fix | ops#121 | - | `integration` `41762ed4ec` | `ca745351d9` (fork PR 350), 2026-10-20 | never (fork fix) |
| `feat/391-warning-load` | feat | ops#391 | - | `integration` `41762ed4ec` | `6c8d6ea5b6` (fork PR 348), 2026-10-20 | never (fork feature) |
| `fix/424-propertyeditor-focus-macos` | fix | ops#424 | main `15883e6f4c` (as `2f06336e66`) | `integration` `6c8d6ea5b6` | `4dab87cac2` (fork PR 353), 2026-10-21 | a new base contains `15883e6f4c` |
| `fix/382-vtk-output-window` | fix | ops#382 | - | `integration` `19b2300169` | `01a7681c2f` (fork PR 351), 2026-10-21 | never (fork fix) |
| `fix/360-upto-cap-names` | fix | ops#360 | - | `integration` `2e2bb138ba` | `c4b4011a87` (fork PR 340), 2026-10-21 | never (fork fix) |
| `fix/375-sweep-end-names` | fix | ops#375 | - | `integration` `c4b4011a87` | `2b1690e050` (fork PR 352), 2026-10-21 | never (fork fix) |
| `fix/414-mass-properties` | fix | ops#414 | - | `integration` `6c8d6ea5b6` | `72e19a4705` (fork PR 354), 2026-10-21 | never (fork fix) |
| `feat/293-d2-first-contact` | feat | ops#293 | - | `integration` `4f191bb942` | `df872a5f80` (fork PR 357), 2026-10-22 | never (fork feature) |
| `fix/378-geometric-index` | fix | ops#378 | - | `integration` `72e19a4705` | `e8ababd393` (fork PR 355), 2026-10-22 | never (fork fix) |
| `fix/361-elementary-upto` | fix | ops#361 | - | `integration` `df872a5f80` | `2d2ac2ac5b` (fork PR 359), 2026-10-22 | never (fork fix) |
| `polish/pd-followups` | polish | ops#395, ops#405, ops#410 | - | `integration` `df872a5f80` | `7fe252a1b5` (fork PR 360), 2026-10-23 | never (fork feature) |
| `fix/446-merged-neighbours` | fix | ops#446 | - | `integration` `7fe252a1b5` | `13bc96d0ad` (fork PR 361), 2026-10-23 | never (fork fix) |
| `fix/447-makehelix-accuracy` | fix | ops#447 | - | `integration` `2d2ac2ac5b` | `eb39b884e5` (fork PR 364), 2026-10-23 | never (fork fix) |
| `infra/418-gen0-script` | infra | ops#418 | none | `integration` `7fe252a1b5` | `30dabfe2f2` (fork PR 365), 2026-10-23 | never |
| `fix/450-upto-followups` | fix | ops#450 | - | `integration` `2d2ac2ac5b` | `0cb0a470c0` (fork PR 362), 2026-10-23 | never (fork fix) |
| `fix/453-refine-element-map` | fix | ops#453 | - | `integration` `2d2ac2ac5b` | `31c71a7276` (fork PR 363), 2026-10-23 | never (fork fix) |
| `fix/421-sweep-corner` | fix | ops#421 | - | `integration` `31c71a7276` | `f6b19b43f5` (fork PR 358), 2026-10-23 | never (fork fix) |
| `fix/454-missing-generator` | fix | ops#454 | - | `integration` `30dabfe2f2` | `1764323b4f` (fork PR 368), 2026-10-23 | never (fork fix) |
| `fix/457-hole-polish` | fix | ops#457, ops#404 | - | `integration` `31c71a7276` | `a024b9ae8f` (fork PR 372), 2026-10-23 | never (fork fix) |
| `perf/310-b-boolean-locations` | fix | ops#310 | - | `integration` `31c71a7276` | `e82321a38b` (fork PR 367), 2026-10-24 | never (fork fix) |
| `fix/428-massprops-callers` | fix | ops#428, ops#426 | - | `integration` `e82321a38b` | `7385573b2f` (fork PR 371), 2026-10-24 | never (fork fix) |
| `infra/460-release-gen0` | infra | ops#460 | none | `integration` `7385573b2f` | `47d7c1233d` (fork PR 374), 2026-10-24 | never |
| `perf/310-c1-base-check` | fix | ops#310 | - | `integration` `7385573b2f` | `9cec95bc89` (fork PR 370), 2026-10-24 | never (fork fix) |
| `perf/474-refine-voids-vouch` | fix | ops#474 | - | `integration` `9cec95bc89` | `b42c494538` (fork PR 375), 2026-10-24 | never (fork fix) |
| `fix/448-sweep-planar-degree` | fix | ops#448 | - | `integration` `9cec95bc89` | `e5b90e2b34` (fork PR 373), 2026-10-24 | a new base sets MakePipeShell's max degree 14 and segments 1000 in Part sweeps and PartDesign Pipe, and Part::Sweep and PartDesign Pipe warn (Wire.makePipeShell and Part.makeSweepSurface log) above 0.1 mm tolerance |
| `feat/370-pipe-corners` | feat | ops#370, ops#381 | - | `integration` `e5b90e2b34` | `a977c44242` (fork PR 344), 2026-10-25 | never (fork feature) |
| `feat/379-pipe-end-names` | feat | ops#379 | - | `feat/370-pipe-corners` `3544e12841` (stacked on fork PR 344) | `4cd3f452d4` (fork PR 356), 2026-10-25 | never (fork feature) |
| `feat/415-pipe-leg-names` | feat | ops#415, ops#455 | - | `feat/379-pipe-end-names` `76627462b0` (stacked on fork PR 356) | `9a89cbf946` (fork PR 369), 2026-10-25 | never (fork feature) |
| `fix/472-lost-void-check` | fix | ops#472 | - | `integration` `b42c494538` | `770da0fde7` (fork PR 376), 2026-10-25 | never (fork fix) |
| `fix/487-failed-feature-base` | fix | ops#487 | - | `integration` `770da0fde7` | `677837eddc` (fork PR 378), 2026-10-25 | never (fork fix) |
| `fix/465-sweep-frenet-followups` | fix | ops#465, ops#439 | - | `integration` `770da0fde7` | `f6e81feebb` (fork PR 377), 2026-10-25 | SweepFrenet looks at samples without a frame, with two more in each straight knot span: a turn-over, jump or unsteady frame of OCCT's Frenet on a straight or nearly straight stretch inside an edge leaves Frenet as a turn-over does (on planar spines, for the plane's normal as binormal); corrected Frenet is no longer refused for loose tolerances |
| `feat/corpus-foundation` | feature | ops#506 | - | `integration` `677837eddc` | `12baa6cda7` (fork PR 381), 2026-10-26 | never (fork tests) |
| `infra/398-release-followups` | infra | ops#398 | - | `integration` `f6e81feebb` | `95538c7728` (fork PR 382), 2026-10-26 | never (fork infra) |
| `corpus/ports-a-d` | feature | ops#506 | - | `integration` `12baa6cda7` | `69d24e907a` (fork PR 385), 2026-10-26 | never (fork tests) |
| `corpus/ports-b-e` | feature | ops#501, ops#504 | - | `integration` `69d24e907a` | `9ede5b31d9` (fork PR 387), 2026-10-27 | never (fork tests) |
| `infra/macos-cli-timeout` | infra | ops#302 | - | `integration` `69d24e907a` | (fork PR 389) | never |

## Fork-only commits in carried topics

| Commit | Topic | What | Drop or revisit when |
|---|---|---|---|
| `9e1049b3b7` | `carry/wirejoiner` | Tests: adapt `WireJoinerTest.setOpenWiresOnly` to V2 naming: the compared wires get the same tag (V2 split pieces carry the result's tag). It also limited the "has a mapped name" check to edges (V2 left the result's vertices unnamed); `fix/21-faceless-vertices` restored the vertex check (ops#21). | Dropped with the topic. |
| `5e89db8043` | `carry/polyline-fillet` | Test: `TestPolylineFilletGui` (in `TestSketcherGui`; the upstream PR has none) draws a polyline with the tool's fillet option and checks it keeps every clicked point (ops#10). | When the topic is dropped, keep the test (it moves to its own topic) unless upstream adds one. |
| `17f67653f2` | `carry/constraint-names` | Test: `TestAutoScaleNamesGui` (in `TestSketcherGui`; the upstream PR has none) sets a sketch's only dimension through the datum dialog and checks that the auto-scale keeps every constraint's name (ops#11). | When the topic is dropped, keep the test (it moves to its own topic) unless upstream adds one. |
| `47abc0c028` | `carry/144-upstream-gui-fixes` | The tree flag of upstream PR 32478 also follows broken external links (`?Edge2`) and names them in the tooltip: here a sketch with a missing external element fails before its external geometry is rebuilt (ops#72), so nothing is flagged `Missing` (ops#144). Also covers upstream issue 32102. | When the topic is dropped, keep the commit (it moves to its own topic) unless upstream's flag covers broken links by then. |
| `2d12a4fac7` | `carry/144-upstream-gui-fixes` | Tests: `TestSketchBrokenExternalTreeGui` (the tree flag; upstream issue 32102) and `TestSketchEditCameraGui` (upstream PR 32611's bounding box in edit), in `TestSketcherGui`; the upstream PRs have none (ops#144). | When the topic is dropped, keep the tests (they move with the fork-only commit) unless upstream adds them. |
