# SPDX-License-Identifier: LGPL-2.1-or-later
"""Class D cases of ops#549: a reference to a feature that fails after an edit, resolved on the
base shape FailureContinuation passes through (`passThroughBase`, ops#126).

The model: a Body with a block 20 x 10 x 10 (sketch `Base` on XY, rectangle (0, 0)-(20, 10),
padded 10). On it one feature that fails after the edit:
- `Slot`, a Pocket 4 deep from a sketch at the block's top, rectangle (5, 3)-(15, 7);
- `Boss`, a Pad 5 high from a sketch at the block's top, the same rectangle;
- `Stub`, a Pad 5 long whose profile is the block's right face (x = 20);
- `Sweep`, an additive Pipe whose profile is the block's right face, along a line of 10 in +x;
- `Boss` 0.1 high (`ThinBoss...`), or on the whole top (`ThinSlab...`): its top face is 0.1 above the
  block's, inside tier 3's reach;
- `RingSweepStops`: the issue's own shape (a Pipe round a closed ring from a plate's face), whose
  corner vertex carries the profile sketch's bare vertex name, which the plate has at another place.
The edit makes the feature fail with its own error (a Pocket or Pad of length 0, a Pipe whose spine
is relinked to an empty sketch), so its output is its base, passed through. The `fix` step undoes the
failing change (the geometry and its IDs as they were): the feature computes again.

Consumers on the failing feature: datum points (Vertex), sketches and datum planes (FlatFace), and
dress-up edges (a Fillet's Base). Each one names one of three kinds of element:
- made by the failed feature (the slot's floor and walls, the boss's top, the stub's and sweep's end):
  after the edit no element of the passed-through shape is it. The expectation (the element at its
  place on the edited model) finds nothing there, so the harness scores a held reference `wrong`
  and a break `broken`, the right result;
- the block's element, which the feature changed (the block's top face around the slot or the
  boss): the block's whole top face holds the expectation's point and plane, so a reference held
  on it is `correct`;
- the block's element, which the feature carried unchanged (an outer corner, an outer top edge):
  the same element, `correct` when held.
After `fix` every reference is expected on its element of the feature again (the build's places).

`...BlockTaller` makes the block 12 high in the same recompute (the failing feature's sketch moves
up with the top): the carried corner and the changed top face move with the block. `...UnderCap`
puts a valid Pad (`Cap`, 3 high on the block's top beside the slot) after the failing feature, and
its consumers name the Cap: the chain holds the failure, the target doesn't (the failing feature's
own elements are then expected `BROKEN`, since the harness reads no stop on a valid target).

Expected results are defined by the geometry above; no file is used. Measured verdicts and the
rule: `notes\\naming-ops549.md`.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Reopens, Scenario, edge, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
X, Y, Z = V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)


class FailedFeatureBase(Scenario):
    """A block, a feature on it that fails after the edit, and consumers on that feature."""

    abstract = True
    area = "failure pass-through"
    CLASSES = ("D",)
    ISSUE = "ops#549"
    FOUND_BY = "designer ops#549"
    TIER = "F"
    steps = ("edit", "fix")
    height = 10  # the block's
    tallerBy = 0  # the block's growth in the edit (BlockTaller variants)

    # The block

    def buildBlock(self, doc):
        self.body = m.body(doc)
        self.base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), self.body)
        self.block = m.pad(self.body, self.base, self.height, "Block")
        self.block.Refine = False
        doc.recompute()

    def growBlock(self):
        if self.tallerBy:
            self.height += self.tallerBy
            self.block.Length = self.height

    # Consumers

    def datumPoint(self, name, target, predicate):
        point = self.body.newObject("PartDesign::Point", name)
        point.AttachmentSupport = [(target, self.names(target, predicate))]
        point.MapMode = "Vertex"
        return point

    def datumPlane(self, name, target, predicate):
        plane = self.body.newObject("PartDesign::Plane", name)
        plane.AttachmentSupport = [(target, self.names(target, predicate))]
        plane.MapMode = "FlatFace"
        return plane

    def sketchOn(self, doc, name, target, predicate):
        sketch = doc.addObject("Sketcher::SketchObject", name)
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(target, self.names(target, predicate))]
        sketch.MapMode = "FlatFace"
        return sketch

    def fillet(self, name, target, predicate):
        fillet = self.body.newObject("PartDesign::Fillet", name)
        fillet.Base = (target, self.names(target, predicate))
        fillet.Radius = 0.5
        return fillet

    def addConsumers(self, doc, target, kinds):
        """Consumers of `target`, one per (reference, kind, predicate method)."""
        for name, kind, expect in kinds:
            if kind == "point":
                owner, prop = self.datumPoint(name, target, expect()), "AttachmentSupport"
            elif kind == "plane":
                owner, prop = self.datumPlane(name, target, expect()), "AttachmentSupport"
            elif kind == "sketch":
                owner, prop = self.sketchOn(doc, name, target, expect()), "AttachmentSupport"
            else:
                owner, prop = self.fillet(name, target, expect()), "Base"
            doc.recompute()
            self.ref(name, owner, prop, expect, Attached() if kind != "fillet" else None)

    # The block's elements, wherever it is

    def blockCorner(self):
        return vertex((0, 0, self.height))

    def blockTop(self):
        return face("plane", normal=Z, contains=(2, 5, self.height))

    def blockOuterEdge(self):
        return edge("line", direction=X, through=(0, 0, self.height), contains=(1, 0, self.height))


# A Pocket that fails


class SlotStops(FailedFeatureBase):
    """The Pocket `Slot` (4 deep, (5, 3)-(15, 7)) fails: length 0. Its floor, wall and rim corner
    are its own; the top face is the block's, changed; the outer corner and edge, carried."""

    REFS = ("floor_sketch", "wall_plane", "rim_point", "top_sketch", "corner_point", "outer_fillet")
    depth = 4

    def floor(self):
        return face("plane", normal=Z, contains=(10, 5, self.height - self.depth))

    def wall(self):
        return face("plane", normal=X, contains=(5, 5, self.height - 1))

    def rim(self):
        return vertex((5, 3, self.height))

    def buildSlot(self, doc):
        self.buildBlock(doc)
        self.slotSketch = m.sketch(doc, "SlotSketch", m.rectangle(5, 3, 15, 7), self.body, z=10)
        self.slot = m.pocket(self.body, self.slotSketch, self.depth, "Slot")
        self.slot.Refine = False
        doc.recompute()

    def build(self, doc):
        self.buildSlot(doc)
        self.addConsumers(
            doc,
            self.slot,
            [
                ("floor_sketch", "sketch", self.floor),
                ("wall_plane", "plane", self.wall),
                ("rim_point", "point", self.rim),
                ("top_sketch", "sketch", self.blockTop),
                ("corner_point", "point", self.blockCorner),
                ("outer_fillet", "fillet", self.blockOuterEdge),
            ],
        )

    def edit(self, doc):
        self.growBlock()
        self.slotSketch.Placement = App.Placement(V(0, 0, self.height), App.Rotation())
        self.slot.Length = 0

    def fix(self, doc):
        self.slot.Length = self.depth


class SlotStopsBlockTaller(SlotStops):
    """As SlotStops, and the block 12 high in the same recompute: the carried corner and edge and
    the changed top face move up 2 with it."""

    tallerBy = 2


# A Pad that fails, on a sketch


class BossStops(FailedFeatureBase):
    """The Pad `Boss` (5 high, (5, 3)-(15, 7)) fails: length 0. Its top, top edge and top corner
    are its own; the block's top face is changed; the outer corner and edge, carried."""

    REFS = ("boss_top_sketch", "boss_edge_fillet", "boss_point", "top_sketch", "corner_point",
            "outer_fillet")
    rise = 5

    def bossTop(self):
        return face("plane", normal=Z, contains=(10, 5, self.height + self.rise))

    def bossEdge(self):
        top = self.height + self.rise
        return edge("line", direction=X, through=(5, 3, top), contains=(10, 3, top))

    def bossCorner(self):
        return vertex((5, 3, self.height + self.rise))

    def build(self, doc):
        self.buildBlock(doc)
        self.bossSketch = m.sketch(doc, "BossSketch", m.rectangle(5, 3, 15, 7), self.body, z=10)
        self.boss = m.pad(self.body, self.bossSketch, self.rise, "Boss")
        self.boss.Refine = False
        doc.recompute()
        self.addConsumers(
            doc,
            self.boss,
            [
                ("boss_top_sketch", "sketch", self.bossTop),
                ("boss_edge_fillet", "fillet", self.bossEdge),
                ("boss_point", "point", self.bossCorner),
                ("top_sketch", "sketch", self.blockTop),
                ("corner_point", "point", self.blockCorner),
                ("outer_fillet", "fillet", self.blockOuterEdge),
            ],
        )

    def edit(self, doc):
        self.growBlock()
        self.bossSketch.Placement = App.Placement(V(0, 0, self.height), App.Rotation())
        self.boss.Length = 0

    def fix(self, doc):
        self.boss.Length = self.rise


class BossStopsBlockTaller(BossStops):
    """As BossStops, and the block 12 high in the same recompute."""

    tallerBy = 2


def relinkSpine(doc, case):
    """The Pipe's failure: its spine relinked to an empty sketch (`fix` links the spine back, whose
    geometry and IDs stay as they were)."""
    empty = doc.getObject("NoSpine") or m.sketch(doc, "NoSpine", [], case.body)
    case.feature.Spine = (empty, [])


class ThinBossStops(FailedFeatureBase):
    """A Pad `Boss` 0.1 high ((5, 3)-(15, 7) on the block's top) fails: length 0. Its top face is
    its own, 0.1 above the block's top: the nearest plane of the passed-through block, inside
    tier 3's reach."""

    REFS = ("boss_top_sketch", "boss_top_plane")
    rise = 0.1
    footprint = (5, 3, 15, 7)

    def bossTop(self):
        return face("plane", normal=Z, contains=(10, 5, self.height + self.rise))

    def buildBoss(self, doc):
        self.buildBlock(doc)
        self.bossSketch = m.sketch(doc, "BossSketch", m.rectangle(*self.footprint), self.body, z=10)
        self.boss = m.pad(self.body, self.bossSketch, self.rise, "Boss")
        self.boss.Refine = False
        doc.recompute()

    def build(self, doc):
        self.buildBoss(doc)
        self.addConsumers(
            doc,
            self.boss,
            [("boss_top_sketch", "sketch", self.bossTop), ("boss_top_plane", "plane", self.bossTop)],
        )

    def edit(self, doc):
        self.boss.Length = 0

    def fix(self, doc):
        self.boss.Length = self.rise


class ThinSlabStops(ThinBossStops):
    """As ThinBossStops with the boss on the whole top, (0, 0)-(20, 10): its top face has the
    block's top's size and outline, 0.1 above it."""

    footprint = (0, 0, 20, 10)


class ThinBossUnderCap(ThinBossStops):
    """As ThinBossStops, with a valid Pad `Cap` (3 high, (16, 2)-(19, 8)) after the Boss; the
    consumers name the Cap."""

    def bossTop(self):
        return BROKEN if self.stepName == "edit" else super().bossTop()

    def build(self, doc):
        self.buildBoss(doc)
        capSketch = m.sketch(doc, "CapSketch", m.rectangle(16, 2, 19, 8), self.body, z=10)
        self.cap = m.pad(self.body, capSketch, 3, "Cap")
        self.cap.Refine = False
        doc.recompute()
        self.addConsumers(
            doc,
            self.cap,
            [("boss_top_sketch", "sketch", self.bossTop), ("boss_top_plane", "plane", self.bossTop)],
        )


# A Pad and a Pipe whose profile is the block's right face: their end's names descend from the
# face's, which the block still has, at another place


class EndOnBlockFace(FailedFeatureBase):
    abstract = True
    REFS = ("end_point", "end_sketch", "end_fillet", "corner_point")
    length = 5

    def endCorner(self):
        return vertex((20 + self.length, 0, 0))

    def endFace(self):
        return face("plane", normal=X, contains=(20 + self.length, 5, 5))

    def endEdge(self):
        x = 20 + self.length
        return edge("line", direction=Y, through=(x, 0, self.height), contains=(x, 5, self.height))

    def farCorner(self):
        return vertex((0, 0, 0))

    def rightFace(self):
        return [
            f"Face{i}"
            for i, f in enumerate(self.block.Shape.Faces, 1)
            if abs(f.CenterOfMass.x - 20) < 1e-6
        ]

    def build(self, doc):
        self.buildBlock(doc)
        self.feature = self.makeFeature(doc)
        doc.recompute()
        if not self.feature.isValid():
            raise RuntimeError(f"{self.feature.Name} is invalid: {self.feature.getStatusString()}")
        self.addConsumers(
            doc,
            self.feature,
            [
                ("end_point", "point", self.endCorner),
                ("end_sketch", "sketch", self.endFace),
                ("end_fillet", "fillet", self.endEdge),
                ("corner_point", "point", self.farCorner),
            ],
        )


class StubStops(EndOnBlockFace):
    """The Pad `Stub`, 5 long from the block's right face, fails: length 0."""

    def makeFeature(self, doc):
        stub = self.body.newObject("PartDesign::Pad", "Stub")
        stub.Profile = (self.block, self.rightFace())
        stub.Length = self.length
        stub.Refine = False
        return stub

    def edit(self, doc):
        self.feature.Length = 0

    def fix(self, doc):
        self.feature.Length = self.length


class SweepStops(EndOnBlockFace):
    """The additive Pipe `Sweep`, the block's right face along (20, 5, 5)-(30, 5, 5), fails: its
    spine is relinked to an empty sketch."""

    length = 10

    def spineLine(self):
        return [Part.LineSegment(V(20, 5, 0), V(30, 5, 0))]

    def makeFeature(self, doc):
        self.spine = m.sketch(
            doc,
            "Spine",
            self.spineLine(),
            self.body,
            placement=App.Placement(V(0, 5, 0), App.Rotation(X, 90)),
        )
        sweep = self.body.newObject("PartDesign::AdditivePipe", "Sweep")
        sweep.Profile = (self.block, self.rightFace())
        sweep.Spine = (self.spine, [])
        sweep.Refine = False
        return sweep

    def edit(self, doc):
        relinkSpine(doc, self)

    def fix(self, doc):
        self.feature.Spine = (self.spine, [])


# A Pipe whose element carries a bare name the base has at another place


class RingSweepStops(FailedFeatureBase):
    """The issue's shape (ops#549, from pr383-r6hh) with a generic failure: a square 4 x 4 at the
    origin padded 1 down (`Plate`); an additive Pipe sweeps the Plate's top face round a closed
    rectangle 30 x 20 in the XZ plane, "Right corner". The Pipe's outer bottom left corner
    (-2, -2, -2) is named by the square sketch's vertex alone, a name the Plate's corner (2, 2, 0)
    carries too. The edit relinks the spine to an empty sketch: the Pipe fails and passes the
    Plate through.
    `top_plane` (the Pipe's top outer face) is the control: its name is the Pipe's own."""

    REFS = ("corner_point", "top_plane")
    half = 2

    def corner(self):
        return vertex((-self.half, -self.half, -self.half))

    def topOuter(self):
        return face("plane", normal=Z, contains=(15, 0, 20 + self.half))

    def ring(self):
        return m.polygon([(0, 0), (0, 20), (30, 20), (30, 0)])

    def buildRing(self, doc):
        self.body = m.body(doc)
        a = self.half
        self.spine = m.sketch(
            doc, "Spine", self.ring(), self.body, placement=App.Placement(V(), App.Rotation(X, 90))
        )
        square = m.sketch(doc, "Square", m.rectangle(-a, -a, a, a), self.body)
        plate = m.pad(self.body, square, 1, "Plate")
        plate.Reversed = True
        doc.recompute()
        top = [
            f"Face{i}"
            for i, f in enumerate(plate.Shape.Faces, 1)
            if abs(f.CenterOfMass.z) < 1e-6 and abs(f.normalAt(0, 0).z) > 0.99
        ]
        self.feature = self.body.newObject("PartDesign::AdditivePipe", "Sweep")
        self.feature.Profile = (plate, top)
        self.feature.Spine = (self.spine, [])
        self.feature.Transition = "Right corner"
        self.feature.Refine = False
        doc.recompute()
        if not self.feature.isValid():
            raise RuntimeError(f"the sweep is invalid: {self.feature.getStatusString()}")

    def build(self, doc):
        self.buildRing(doc)
        self.addConsumers(
            doc,
            self.feature,
            [("corner_point", "point", self.corner), ("top_plane", "plane", self.topOuter)],
        )

    def edit(self, doc):
        relinkSpine(doc, self)

    def fix(self, doc):
        self.feature.Spine = (self.spine, [])


# The failure in the chain: a valid Pad after the failing Pocket, its consumers on the Pad


class SlotUnderCap(SlotStops):
    """As SlotStops, with the Pad `Cap` (3 high, (16, 2)-(19, 8) on the block's top) after the
    Slot; every consumer names the Cap, as one picked on the Body's tip does."""

    REFS = SlotStops.REFS + ("cap_top_sketch",)

    # The Cap is valid after the edit, so the harness reads no stop (decision 186's branch): the
    # slot's own elements are expected to break while it fails
    def floor(self):
        return BROKEN if self.stepName == "edit" else super().floor()

    def wall(self):
        return BROKEN if self.stepName == "edit" else super().wall()

    def rim(self):
        return BROKEN if self.stepName == "edit" else super().rim()

    capHeight = 3

    def capTop(self):
        return face("plane", normal=Z, contains=(17.5, 5, self.height + self.capHeight))

    def build(self, doc):
        self.buildBlock(doc)
        self.slotSketch = m.sketch(doc, "SlotSketch", m.rectangle(5, 3, 15, 7), self.body, z=10)
        self.slot = m.pocket(self.body, self.slotSketch, self.depth, "Slot")
        self.slot.Refine = False
        self.capSketch = m.sketch(doc, "CapSketch", m.rectangle(16, 2, 19, 8), self.body, z=10)
        self.cap = m.pad(self.body, self.capSketch, self.capHeight, "Cap")
        self.cap.Refine = False
        doc.recompute()
        self.addConsumers(
            doc,
            self.cap,
            [
                ("floor_sketch", "sketch", self.floor),
                ("wall_plane", "plane", self.wall),
                ("rim_point", "point", self.rim),
                ("top_sketch", "sketch", self.blockTop),
                ("corner_point", "point", self.blockCorner),
                ("outer_fillet", "fillet", self.blockOuterEdge),
                ("cap_top_sketch", "sketch", self.capTop),
            ],
        )

    def edit(self, doc):
        super().edit(doc)
        self.capSketch.Placement = App.Placement(V(0, 0, self.height), App.Rotation())


class SlotUnderCapBlockTaller(SlotUnderCap):
    """As SlotUnderCap, and the block 12 high in the same recompute: the Cap moves up with it."""

    tallerBy = 2


class ThinSlabUnderCap(ThinBossUnderCap):
    """As ThinBossUnderCap with the slab of ThinSlabStops: the Cap's consumers of the slab's top
    see the block's top 0.1 below it, of the same size, and the Cap is valid (guesses stay on)."""

    footprint = (0, 0, 20, 10)

# The design review's cases (ops#549 r2): a split top, an expanded edge, a grown top, a groove, and
# suppression, which passes the base through as a failure does (Feature::recompute)


class ThroughSlotStops(FailedFeatureBase):
    REFS = ("left_sketch", "left_plane", "right_sketch")
    depth = 4

    def leftTop(self):
        return face("plane", normal=Z, contains=(2, 5, self.height))

    def rightTop(self):
        return face("plane", normal=Z, contains=(18, 5, self.height))

    def build(self, doc):
        self.buildBlock(doc)
        self.slotSketch = m.sketch(doc, "SlotSketch", m.rectangle(8, -1, 12, 11), self.body, z=10)
        self.slot = m.pocket(self.body, self.slotSketch, self.depth, "Slot")
        self.slot.Refine = False
        doc.recompute()
        self.addConsumers(
            doc,
            self.slot,
            [
                ("left_sketch", "sketch", self.leftTop),
                ("left_plane", "plane", self.leftTop),
                ("right_sketch", "sketch", self.rightTop),
            ],
        )

    def edit(self, doc):
        self.slot.Length = 0

    def fix(self, doc):
        self.slot.Length = self.depth


class SplitEdgeThenStops(FailedFeatureBase):
    """The Slot starts inside the top ((8, 3)-(12, 7)); a Fillet on the block's front top edge
    (y = 0, z = 10) after it. `split` widens the slot across the block ((8, -1)-(12, 11)): the edge
    is cut in two and the fillet's reference expands to both pieces (`from` = the whole edge).
    `edit` makes the Slot fail (length 0): the base's whole edge carries the `from` name (a collapse
    may remove a member and clear `from`). `fix` restores the length: the edge is cut in two again."""

    REFS = ("front_fillet",)
    steps = ("split", "edit", "fix")
    depth = 4

    def frontEdge(self):
        return edge(
            "line", direction=X, through=(0, 0, self.height), contains=(1, 0, self.height)
        )

    def build(self, doc):
        self.buildBlock(doc)
        self.slotSketch = m.sketch(doc, "SlotSketch", m.rectangle(8, 3, 12, 7), self.body, z=10)
        self.slot = m.pocket(self.body, self.slotSketch, self.depth, "Slot")
        self.slot.Refine = False
        doc.recompute()
        self.addConsumers(doc, self.slot, [("front_fillet", "fillet", self.frontEdge)])

    def split(self, doc):
        moves = {(0, 1): (8, -1), (0, 2): (12, -1), (1, 1): (12, -1), (1, 2): (12, 11),
                 (2, 1): (12, 11), (2, 2): (8, 11), (3, 1): (8, 11), (3, 2): (8, -1)}
        for (geo, pos), (x, y) in moves.items():
            self.slotSketch.moveGeometry(geo, pos, V(x, y, 0))

    def edit(self, doc):
        self.slot.Length = 0

    def fix(self, doc):
        self.slot.Length = self.depth


class ExtendStops(FailedFeatureBase):
    """A Pad `Ext` beside the block ((20, 0)-(26, 10), 10 high from z = 0, Refine on): the block's
    top grows to (0, 0)-(26, 10), its centre (13, 5) over the block's own top. A sketch on the grown
    top. `edit`: the Pad fails (length 0); the base's top is a part of the grown one."""

    REFS = ("top_sketch", "top_plane")
    far = 26

    def top(self):
        return face("plane", normal=Z, contains=(2, 5, self.height))

    def build(self, doc):
        self.buildBlock(doc)
        self.extSketch = m.sketch(doc, "ExtSketch", m.rectangle(20, 0, self.far, 10), self.body)
        self.ext = m.pad(self.body, self.extSketch, self.height, "Ext")
        self.ext.Refine = True
        doc.recompute()
        self.addConsumers(
            doc,
            self.ext,
            [("top_sketch", "sketch", self.top), ("top_plane", "plane", self.top)],
        )

    def edit(self, doc):
        self.ext.Length = 0

    def fix(self, doc):
        self.ext.Length = self.height


class ExtendFarStops(ExtendStops):
    """As ExtendStops, the Pad to x = 60: the grown top's centre (30, 5) lies outside the block's."""

    far = 60


class GrooveStops(FailedFeatureBase):
    """A Pocket `Groove`, 4 deep, from an annulus centred (10, 5) (radii 4 and 2) at the block's top:
    the top becomes the outer face round the groove and an island disc, both at z = 10. A sketch
    and a datum plane on the outer face. `edit`: the Groove fails (length 0): the base's whole top
    holds the outer face's inside point (kept today); its fingerprint may be measured anew there.
    `fix`: the Groove again, the island coplanar with the outer face."""

    REFS = ("outer_sketch", "outer_plane", "island_sketch")
    depth = 4

    def outer(self):
        return face("plane", normal=Z, contains=(1, 1, self.height))

    def island(self):
        return face("plane", normal=Z, contains=(10, 5, self.height))

    def buildGroove(self, doc):
        self.buildBlock(doc)
        self.grooveSketch = m.sketch(doc, "GrooveSketch", [m.circle(10, 5, 4), m.circle(10, 5, 2)],
                                     self.body, z=10)
        self.groove = m.pocket(self.body, self.grooveSketch, self.depth, "Groove")
        self.groove.Refine = False
        doc.recompute()

    def build(self, doc):
        self.buildGroove(doc)
        self.addConsumers(
            doc,
            self.groove,
            [
                ("outer_sketch", "sketch", self.outer),
                ("outer_plane", "plane", self.outer),
                ("island_sketch", "sketch", self.island),
            ],
        )

    def edit(self, doc):
        self.groove.Length = 0

    def fix(self, doc):
        self.groove.Length = self.depth


class RingSweepSuppressed(RingSweepStops):
    """As RingSweepStops, with the Pipe suppressed in `edit` (no failure: Feature::recompute passes
    the base through when Suppressed) and unsuppressed in `fix`."""

    def corner(self):
        return BROKEN if self.stepName == "edit" else super().corner()

    def topOuter(self):
        return BROKEN if self.stepName == "edit" else super().topOuter()

    def edit(self, doc):
        self.feature.Suppressed = True

    def fix(self, doc):
        self.feature.Suppressed = False


class ThinSlabSuppressed(ThinSlabStops):
    """As ThinSlabStops, the thin slab suppressed in `edit` and unsuppressed in `fix`."""

    def bossTop(self):
        return BROKEN if self.stepName == "edit" else super().bossTop()

    def edit(self, doc):
        self.boss.Suppressed = True

    def fix(self, doc):
        self.boss.Suppressed = False


# Suppression as an editing state (ops#549 rule PS, PLAN decision 213; notes/naming-ops549.md 8.4).
# Steps: `sup` suppresses the feature, an edit follows while it stays suppressed, `uns` brings it
# back. A suppressed feature is valid, so the harness reads no stop: its own elements are expected
# BROKEN while it is suppressed (`suppressedSteps`), as removal would leave them.


class Suppresses:
    """Mixin: `suppressible()` is the suppressed feature; `suppressedSteps` the steps it is suppressed
    after."""

    suppressedSteps = ("sup",)

    def suppressed(self):
        return self.stepName in self.suppressedSteps

    def gone(self, expectation):
        return BROKEN if self.suppressed() else expectation

    def sup(self, doc):
        self.suppressible().Suppressed = True

    def uns(self, doc):
        self.suppressible().Suppressed = False


class SlotSuppressed(Suppresses, SlotStops):
    """The Slot suppressed and back: its floor, wall and rim break and return; the top it cut, the
    corner and the edge it carried hold throughout."""

    steps = ("sup", "uns")

    def suppressible(self):
        return self.slot

    def floor(self):
        return self.gone(super().floor())

    def wall(self):
        return self.gone(super().wall())

    def rim(self):
        return self.gone(super().rim())

    def taller(self, doc):
        self.height = 12
        self.block.Length = self.height
        self.slotSketch.Placement = App.Placement(V(0, 0, self.height), App.Rotation())


class SlotSuppressedThenTaller(SlotSuppressed):
    """Edited while suppressed: the block 12 high (the slot's sketch with its top). The records
    retaken at `sup` are the world's without the Slot, so the edit is judged as ever."""

    steps = ("sup", "taller", "uns")
    suppressedSteps = ("sup", "taller")


class SlotSuppressedAndTaller(SlotSuppressed):
    """Suppressed and the block 12 high in one recompute: a switch with a move, nothing at the
    saved places (loud until the Slot is back)."""

    steps = ("supTaller", "uns")
    suppressedSteps = ("supTaller",)

    def supTaller(self, doc):
        self.sup(doc)
        self.taller(doc)


class SlotSuppressedUndo(SlotSuppressed):
    """The suppression undone, then the block 12 high: records retaken without the Slot stay after
    the undo (not in the transaction): loud while moved, never quiet."""

    steps = ("sup", "undo", "taller")

    def sup(self, doc):
        doc.UndoMode = 1
        doc.openTransaction("suppress")
        super().sup(doc)
        doc.recompute()
        doc.commitTransaction()

    def undo(self, doc):
        doc.undo()


class SlotSuppressedReload(Reopens, SlotSuppressed):
    """Suppressed, saved and reopened, then the block 12 high: the records' world is saved with
    them."""

    steps = ("sup", "reopen", "taller")
    suppressedSteps = ("sup", "reopen", "taller")

    def taller(self, doc):
        self.block = doc.getObject("Block")
        self.slotSketch = doc.getObject("SlotSketch")
        super().taller(doc)


class SlotSuppressedSavedBeforeRecompute(Reopens, SlotSuppressed):
    """Suppressed and saved before any recompute, reopened, then the block 12 high: the saved
    shapes still had the Slot (its pass-through state false in the file), so the open's batch is
    stable and the recompute the switch."""

    steps = ("supSaved", "taller")
    suppressedSteps = ("supSaved", "taller")

    def supSaved(self, doc):
        self.slot.Suppressed = True
        self.reopen(doc)

    def taller(self, doc):
        self.block = doc.getObject("Block")
        self.slotSketch = doc.getObject("SlotSketch")
        super().taller(doc)


class SlotUnderCapSuppressedCapTaller(Suppresses, SlotUnderCap):
    """The Slot suppressed under the Cap, the Cap 5 high meanwhile: a later feature edited while an
    earlier one is suppressed; the consumers name the Cap."""

    steps = ("sup", "capTaller", "uns")
    suppressedSteps = ("sup", "capTaller")

    def suppressible(self):
        return self.slot

    def floor(self):
        return self.gone(SlotStops.floor(self))

    def wall(self):
        return self.gone(SlotStops.wall(self))

    def rim(self):
        return self.gone(SlotStops.rim(self))

    def capTaller(self, doc):
        self.capHeight = 5
        self.cap.Length = self.capHeight


class TwoSuppressedOneBack(SlotUnderCapSuppressedCapTaller):
    """The Slot and the Cap suppressed, then the Cap back alone: only chains through the Cap
    switch."""

    steps = ("supBoth", "capBack")
    suppressedSteps = ("supBoth", "capBack")

    def capTop(self):
        return BROKEN if self.stepName == "supBoth" else super().capTop()

    def supBoth(self, doc):
        self.slot.Suppressed = True
        self.cap.Suppressed = True

    def capBack(self, doc):
        self.cap.Suppressed = False


class RingSweepSuppressedThenThicker(Suppresses, RingSweepStops):
    """C1 under suppression, edited meanwhile: the Plate 1.5 thick (inside the Pipe's corner, so
    the Pipe's shape is the same when it is back). The record taken with the Pipe stays (a switch
    each time) until it is back."""

    steps = ("sup", "thicker", "uns")
    suppressedSteps = ("sup", "thicker")

    def suppressible(self):
        return self.sweep

    def buildRing(self, doc):
        super().buildRing(doc)
        self.sweep = self.feature

    def corner(self):
        return self.gone(super().corner())

    def topOuter(self):
        return self.gone(super().topOuter())

    def thicker(self, doc):
        doc.getObject("Plate").Length = 1.5


class RingSweepSuppressedUnderPad(RingSweepSuppressedThenThicker):
    """C1 through a valid feature: a Pad `Lug` after the Pipe, (0, 0)-(1, 1) from z = 0 up 25 (in
    the Plate, through the Pipe's leg and out of its top, so it computes with the Pipe suppressed),
    and the datum on the Lug's corner that carries the bare name; the Pipe suppressed and back."""

    REFS = ("corner_point",)
    steps = ("sup", "uns")
    suppressedSteps = ("sup",)

    def build(self, doc):
        self.buildRing(doc)
        lugSketch = m.sketch(doc, "LugSketch", m.rectangle(0, 0, 1, 1), self.body)
        self.lug = m.pad(self.body, lugSketch, 25, "Lug")
        self.lug.Refine = False
        doc.recompute()
        self.addConsumers(doc, self.lug, [("corner_point", "point", self.corner)])


class RingSweepSuppressedAttachNew(Suppresses, RingSweepStops):
    """A datum taken while the Pipe is suppressed, on the vertex of the Plate's corner (2, 2, 0)
    whose bare name the Pipe's corner carries. Back, the Pipe absorbs the Plate and the vertex is
    gone: the datum breaks (C1 reversed: the name gives the Pipe's corner, elsewhere)."""

    REFS = ("new_point",)
    steps = ("uns",)
    suppressedSteps = ()

    def suppressible(self):
        return self.sweep

    def plateCorner(self):
        return BROKEN if self.stepName == "uns" else vertex((self.half, self.half, 0))

    def build(self, doc):
        self.buildRing(doc)
        self.sweep = self.feature
        self.sweep.Suppressed = True
        doc.recompute()
        self.addConsumers(doc, self.sweep, [("new_point", "point", self.plateCorner)])


class ThinSlabSuppressedThenTaller(Suppresses, ThinSlabStops):
    """C2 under suppression, edited meanwhile: the block 12 high (the slab's sketch with its top)."""

    steps = ("sup", "taller", "uns")
    suppressedSteps = ("sup", "taller")

    def suppressible(self):
        return self.boss

    def bossTop(self):
        return self.gone(super().bossTop())

    def taller(self, doc):
        self.height = 12
        self.block.Length = self.height
        self.bossSketch.Placement = App.Placement(V(0, 0, self.height), App.Rotation())


class ExtendSuppressed(Suppresses, ExtendStops):
    """The Pad that grew the top, suppressed and back: the block's own top lies within the grown
    one, and the grown one covers it again."""

    steps = ("sup", "uns")

    def suppressible(self):
        return self.ext


class ThroughSlotSuppressed(Suppresses, ThroughSlotStops):
    """The slot that split the top, suppressed and back: the pieces' names aren't on the whole top
    (PT only vetoes)."""

    steps = ("sup", "uns")

    def suppressible(self):
        return self.slot


class SlotSuppressedAttachNew(Suppresses, SlotStops):
    """A datum plane and a sketch taken on the block's top while the Slot is suppressed; the Slot
    back, its top lies within theirs."""

    REFS = ("new_plane", "new_sketch")
    steps = ("uns",)
    suppressedSteps = ()

    def suppressible(self):
        return self.slot

    def build(self, doc):
        self.buildSlot(doc)
        self.slot.Suppressed = True
        doc.recompute()
        self.addConsumers(
            doc,
            self.slot,
            [("new_plane", "plane", self.blockTop), ("new_sketch", "sketch", self.blockTop)],
        )


class GrooveSuppressedUnsuppressed(Suppresses, GrooveStops):
    """A datum plane taken on the whole top while the Groove is suppressed; the Groove back, the
    outer face lies within it, but so does the island on the same plane: no proof (loud)."""

    REFS = ("new_plane",)
    steps = ("uns",)
    suppressedSteps = ()

    def suppressible(self):
        return self.groove

    def build(self, doc):
        self.buildGroove(doc)
        self.groove.Suppressed = True
        doc.recompute()
        self.addConsumers(doc, self.groove, [("new_plane", "plane", self.outer)])


class PatternSuppressedOriginal(Suppresses, FailedFeatureBase):
    """A Pocket `Dimple` (r = 1 at (5, 5), 2 deep) and its LinearPattern along X (3, 5 apart); a
    sketch on the top, named on the pattern. The Pocket suppressed: the pattern's originals are in
    its chain (its links), a switch; the whole top covers the dimpled one."""

    REFS = ("top_sketch",)
    steps = ("sup", "uns")

    def suppressible(self):
        return self.dimple

    def build(self, doc):
        self.buildBlock(doc)
        sketch = m.sketch(doc, "DimpleSketch", [m.circle(5, 5, 1)], self.body, z=10)
        self.dimple = m.pocket(self.body, sketch, 2, "Dimple")
        self.dimple.Refine = False
        pattern = doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = [self.dimple]
        pattern.Direction = (m.originFeature(self.body, "X_Axis"), [""])
        pattern.Mode = "Spacing"
        pattern.Offset = 5
        pattern.Occurrences = 3
        self.body.addObject(pattern)
        doc.recompute()
        self.addConsumers(doc, pattern, [("top_sketch", "sketch", self.blockTop)])
