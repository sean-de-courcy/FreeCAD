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
| `feat/127-guess-policy` | feat | ops#127, ops#133, ops#107 | - | `integration` `2eb8b6ec7a` | (fork PR 122) | never (fork feature) |

## Fork-only commits in carried topics

| Commit | Topic | What | Drop or revisit when |
|---|---|---|---|
| `9e1049b3b7` | `carry/wirejoiner` | Tests: adapt `WireJoinerTest.setOpenWiresOnly` to V2 naming: the compared wires get the same tag (V2 split pieces carry the result's tag). It also limited the "has a mapped name" check to edges (V2 left the result's vertices unnamed); `fix/21-faceless-vertices` restored the vertex check (ops#21). | Dropped with the topic. |
| `5e89db8043` | `carry/polyline-fillet` | Test: `TestPolylineFilletGui` (in `TestSketcherGui`; the upstream PR has none) draws a polyline with the tool's fillet option and checks it keeps every clicked point (ops#10). | When the topic is dropped, keep the test (it moves to its own topic) unless upstream adds one. |
| `17f67653f2` | `carry/constraint-names` | Test: `TestAutoScaleNamesGui` (in `TestSketcherGui`; the upstream PR has none) sets a sketch's only dimension through the datum dialog and checks that the auto-scale keeps every constraint's name (ops#11). | When the topic is dropped, keep the test (it moves to its own topic) unless upstream adds one. |
| `47abc0c028` | `carry/144-upstream-gui-fixes` | The tree flag of upstream PR 32478 also follows broken external links (`?Edge2`) and names them in the tooltip: here a sketch with a missing external element fails before its external geometry is rebuilt (ops#72), so nothing is flagged `Missing` (ops#144). Also covers upstream issue 32102. | When the topic is dropped, keep the commit (it moves to its own topic) unless upstream's flag covers broken links by then. |
| `2d12a4fac7` | `carry/144-upstream-gui-fixes` | Tests: `TestSketchBrokenExternalTreeGui` (the tree flag; upstream issue 32102) and `TestSketchEditCameraGui` (upstream PR 32611's bounding box in edit), in `TestSketcherGui`; the upstream PRs have none (ops#144). | When the topic is dropped, keep the tests (they move with the fork-only commit) unless upstream adds them. |
