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
| `fix/229-rename-value-rollback` | fix | ops#229 | - | `fix/178-181-rename-move-transactions` `5d982c82f5` (fork PR 210) | (fork PR 212) | when upstream's `TransactionObject` keeps a rename and a value change of one property apart (one entry per property ID) |

## Fork-only commits in carried topics

| Commit | Topic | What | Drop or revisit when |
|---|---|---|---|
| `9e1049b3b7` | `carry/wirejoiner` | Tests: adapt `WireJoinerTest.setOpenWiresOnly` to V2 naming: the compared wires get the same tag (V2 split pieces carry the result's tag). It also limited the "has a mapped name" check to edges (V2 left the result's vertices unnamed); `fix/21-faceless-vertices` restored the vertex check (ops#21). | Dropped with the topic. |
| `5e89db8043` | `carry/polyline-fillet` | Test: `TestPolylineFilletGui` (in `TestSketcherGui`; the upstream PR has none) draws a polyline with the tool's fillet option and checks it keeps every clicked point (ops#10). | When the topic is dropped, keep the test (it moves to its own topic) unless upstream adds one. |
| `17f67653f2` | `carry/constraint-names` | Test: `TestAutoScaleNamesGui` (in `TestSketcherGui`; the upstream PR has none) sets a sketch's only dimension through the datum dialog and checks that the auto-scale keeps every constraint's name (ops#11). | When the topic is dropped, keep the test (it moves to its own topic) unless upstream adds one. |
| `47abc0c028` | `carry/144-upstream-gui-fixes` | The tree flag of upstream PR 32478 also follows broken external links (`?Edge2`) and names them in the tooltip: here a sketch with a missing external element fails before its external geometry is rebuilt (ops#72), so nothing is flagged `Missing` (ops#144). Also covers upstream issue 32102. | When the topic is dropped, keep the commit (it moves to its own topic) unless upstream's flag covers broken links by then. |
| `2d12a4fac7` | `carry/144-upstream-gui-fixes` | Tests: `TestSketchBrokenExternalTreeGui` (the tree flag; upstream issue 32102) and `TestSketchEditCameraGui` (upstream PR 32611's bounding box in edit), in `TestSketcherGui`; the upstream PRs have none (ops#144). | When the topic is dropped, keep the tests (they move with the fork-only commit) unless upstream adds them. |
