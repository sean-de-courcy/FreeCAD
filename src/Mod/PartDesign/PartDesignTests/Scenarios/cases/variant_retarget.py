# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Corpus cases (ops#504, class E): a reference through an App::Link whose target changes with a
variant switch (the link's `LinkCopyOnChange` = Tracking, then `Config = "Large"`).

Designed geometry only. A primitive that a switch unsuppresses keeps its Placement expressions
unevaluated in the copy until it is touched (found porting these cases), so a feature that is
absent in the small configuration sits out of reach there instead of being suppressed. One document holds a spreadsheet configuration table (rows "Small" and
"Large", set up as Spreadsheet's "Configuration table" dialog does), a PartDesign::Body whose
`Config` is a CopyOnChange enumeration, and an App::Link to the Body. The Body's features are
primitives (AdditiveBox, SubtractiveBox, SubtractiveCylinder, Fillet) whose sizes, places and
`Suppressed` flags are expressions on the table's columns, so the switch makes a copy of the Body
in the other configuration and retargets the link. Each reference is a PropertyLinkSub (`Sub`)
of its own consumer, an App::FeaturePython that fails without it (as a joint does), on an element
of the link. A retarget keeps the reference's index only (ops#42, option A), so the expectation
is the counterpart element on the new target, found by geometry (the same corner, the same hole,
the same pocket's floor), or a loud break where the design says no counterpart exists (more than
one look-alike, or the feature is gone).

Rows of corpus/predicted/E.json ported here, by class and reference (V2s; the rows marked V2s+V2
also run in V2 with FREECAD_SCENARIO_CONFIGS=V2s,V2: a case can't name a report column):
- VariantBoltHolesFillet: hole_top_vertex, hole_wall. A 100 x 60 x 10 plate with four holes
  (radius 4) becomes a 140 x 80 plate with four holes and a fillet (radius 2) on the vertical
  edge at the origin: the topology changes, and the holes' faces and vertices keep their count
  but not their numbers. Counterpart: the same corner's hole. The plain names are the se hole's
  (of the walls, the first of the three that land on another hole's wall on integration); the
  other three holes are extra references (`hole_wall_<corner>`, `hole_top_vertex_<corner>`).
- VariantBoltHolesSameTopology: hole_wall. The same plates without the fillet (same topology).
- VariantPocketMoved: pocket_floor. A 10 x 10 x 5 block with a 3 x 3 x 1.5 pocket at (2, 2)
  becomes a 30 x 20 x 8 block with a 4 x 4 x 2 pocket at (13, 8): the floor follows its pocket.
- VariantOnePocketToTwo: pocket_floor. The block's one pocket becomes two look-alike pockets in
  the large block: no counterpart a person could name, so a loud break is the answer. (In this
  numbering the small floor's index, Face11, is a wall of the second pocket and never a floor:
  no arrangement of two interior pockets puts a floor there, so the kind guard breaks it.)
- VariantPocketToLStep: pocket_top_corner. The pocket's top corner (the vertex at (2, 2, 5)) when
  the large block has an L step (from x = 15, 4 above the bottom cut away) and no pocket: the
  pocket is gone, so a loud break. Extras: the pocket's other three top corners.
- VariantTopologyChanged: top_face_on_pocket_floor, vertex_corner. The small block (with its
  pocket at (2, 2)) becomes a large block with a corner notch (4 x 4 x 2 at (0, 0)) whose floor
  has the top face's index (checked: the case errors if the numbering ever stops doing that).
  The top face must follow to the large top face; the block's corners (vertex_corner is the far
  top one, the other seven are extras `vertex_corner_<x><y><z>`, 1 for the far side) to the
  large block's corners; the notch removes the (0, 0, top) corner, which must break.
- VariantNotch4m: top_face. The same kind of swap on a 300 x 300 x 4000 post whose notch
  (100 x 100 x 60) floor sits 60 mm under the top, 0.985 of the height.
- VariantCopyGroupDirect: reference1. A reference straight into the variant copy (not through
  the link); the source part is edited, which remakes the copy, and the old one is removed: the
  reference is emptied, which its consumer reports (loud).
- VariantExpressionArea: link_face6_area. An expression `LinkA.<<Face6>>._shape.Area` on the
  small block's top face (area 100) across the switch to the filleted large block: the top
  face's area (599.14) or an error. Judged by the expression's value, not a stored reference
  (judge()).
- VariantRetargetUndo: pending_check. The switch to the filleted block inside a transaction,
  undone and redone before the first recompute; then the top face is kept or the reference
  breaks, never another face.
"""

import math
import sys

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    OwnOrBroken,
    Predicate,
    Result,
    Scenario,
    ScenarioError,
    Z,
    expectedNames,
    face,
    vertex,
)

V = App.Vector
TOL = 1e-5
LETTERS = "BCDEFGHIJKLMNOPQRSTUVWXYZ"


def S(alias):
    return "Sheet." + alias


class Consumer:
    """What a joint or a binder does with a reference: it fails when the link is empty or a
    sub-name is marked missing (`?`)."""

    def __init__(self, obj, prop="Sub"):
        self.prop = prop
        obj.Proxy = self

    def execute(self, obj):
        value = getattr(obj, self.prop)
        if not value or value[0] is None or not value[1]:
            raise ValueError(f"{obj.Name}.{self.prop} is empty")
        for sub in value[1]:
            if sub.startswith("?"):
                raise ValueError(f"{obj.Name}.{self.prop}: {sub} is missing")


class Variants(Scenario):
    """The document, the Body with its configuration table, and the link; a subclass gives the
    table's COLUMNS ((alias, Small value, Large value), column B on), builds the features
    (`makeFeatures`) and tracks the references (`makeReferences`). The edit switches the link to
    "Large". `value(alias)` gives a column's value in the configuration the link shows now, for
    the expectations."""

    abstract = True
    area = "variant_retarget"
    CLASSES = ("E",)
    AXES = ("M5", "E5")
    ISSUE = "ops#504"
    FOUND_BY = "port"
    TIER = "F"
    COLUMNS = ()
    edited = False

    def value(self, alias):
        for name, small, large in self.COLUMNS:
            if name == alias:
                return large if self.edited else small
        raise ScenarioError(f"no column {alias!r}")

    # Building

    def build(self, doc):
        self.edited = False
        self.makeTable(doc)
        self.makeFeatures(doc)
        doc.recompute()
        self.link = doc.addObject("App::Link", "LinkA")
        self.link.LinkedObject = self.body
        doc.recompute()
        self.link.LinkCopyOnChange = "Tracking"
        doc.recompute()
        self.makeReferences(doc)
        doc.recompute()

    def makeTable(self, doc):
        sheet = doc.addObject("Spreadsheet::Sheet", "Sheet")
        self.body = body = doc.addObject("PartDesign::Body", "Body")
        sheet.set("A2", "Small")
        sheet.set("A3", "Large")
        for letter, (_, small, large) in zip(LETTERS, self.COLUMNS):
            sheet.set(f"{letter}2", str(small))
            sheet.set(f"{letter}3", str(large))
        body.addProperty("App::PropertyEnumeration", "Config", "Configuration")
        body.setPropertyStatus("Config", "CopyOnChange")
        body.setExpression("Config.Enum", "Sheet.cells[<<A2:|>>]")
        doc.recompute()
        sheet.set("A1", "=hiddenref(Body.Config.String)")
        last = LETTERS[len(self.COLUMNS) - 1]
        sheet.setExpression(
            f".cells.Bind.B1.{last}1",
            "tuple(.cells; <<B>> + str(hiddenref(Body.Config) + 2); "
            f"<<{last}>> + str(hiddenref(Body.Config) + 2))",
        )
        doc.recompute()
        for letter, (alias, _, _) in zip(LETTERS, self.COLUMNS):
            sheet.setAlias(f"{letter}1", alias)
        doc.recompute()
        self.sheet = sheet

    @staticmethod
    def setValue(obj, prop, value):
        """A number or an expression (a string), always set as an expression: the copy a variant
        switch makes keeps only what an expression binds (a numeric part of a Placement, or of a
        suppressed feature, comes back as the default)."""
        obj.setExpression(prop, value if isinstance(value, str) else repr(value))

    @staticmethod
    def place(obj, at):
        for axis, c in zip("xyz", at):
            obj.setExpression(f".Placement.Base.{axis}", c if isinstance(c, str) else repr(c))

    def addBox(self, size, name="Box"):
        box = self.body.newObject("PartDesign::AdditiveBox", name)
        for prop, c in zip(("Length", "Width", "Height"), size):
            self.setValue(box, prop, c)
        return box

    def addCut(self, name, at, size, off=None):
        """A SubtractiveBox at `at` (numbers or expressions); `off` is an expression for its
        Suppressed."""
        cut = self.body.newObject("PartDesign::SubtractiveBox", name)
        for prop, c in zip(("Length", "Width", "Height"), size):
            self.setValue(cut, prop, c)
        self.place(cut, at)
        if off:
            cut.setExpression("Suppressed", off)
        return cut

    def addHole(self, name, at, radius, height):
        hole = self.body.newObject("PartDesign::SubtractiveCylinder", name)
        self.setValue(hole, "Radius", radius)
        self.setValue(hole, "Height", height)
        self.place(hole, at)
        return hole

    def addFillet(self, doc, base, radius=2):
        """A fillet on the vertical edge at x = y = 0 of `base`, suppressed by the column
        "Plain"."""
        doc.recompute()
        edge = next(
            f"Edge{i}"
            for i, e in enumerate(base.Shape.Edges, 1)
            if e.BoundBox.XMax < TOL and e.BoundBox.YMax < TOL
        )
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (base, [edge])
        fillet.Radius = radius
        fillet.setExpression("Suppressed", S("Plain"))
        return fillet

    def makeFeatures(self, doc):
        raise NotImplementedError

    def makeReferences(self, doc):
        raise NotImplementedError

    def track(self, name, locate, expect, target=None):
        """A reference to the element `locate()` finds on the link (or `target`) now: its own
        consumer, its `Sub`, expected as `expect()` says."""
        target = target or self.link
        holder = self.doc.addObject("App::FeaturePython", "Ref_" + name)
        holder.addProperty("App::PropertyLinkSub", "Sub")
        Consumer(holder)
        holder.Sub = (target, list(self.names(target, locate())))
        self.ref(name, holder, "Sub", expect)
        return holder

    # Editing

    def edit(self, doc):
        self.edited = True
        self.link.Config = "Large"
        doc.recompute()
        doc.recompute()
        self.precondition()

    def precondition(self):
        """Raises ScenarioError where the model doesn't show what the case is about."""

    def planeUp(self, z):
        return face("plane", normal=Z, through=(0, 0, z))


# ---------------------------------------------------------------------------------------------
# Bolt holes
# ---------------------------------------------------------------------------------------------

CORNERS = ("sw", "se", "ne", "nw")
HOLE_COLUMNS = {"sw": ("HoleX1", "HoleY1"), "se": ("HoleX2", "HoleY1"),
                "ne": ("HoleX2", "HoleY2"), "nw": ("HoleX1", "HoleY2")}


def refNames(base, primary):
    """`base` for the corner `primary`, `base_<corner>` for the others, in CORNERS' order."""
    return tuple(base if c == primary else f"{base}_{c}" for c in CORNERS)


class BoltHoles(Variants):
    """A 100 x 60 x 10 plate with four holes (radius 4, 15 from the sides: corners sw, se, ne, nw)
    in the small configuration; 140 x 80 x 10 with the holes 20 from the sides in the large one,
    with a fillet (radius 2) on the vertical edge at the origin if FILLET. The reference is a
    hole's wall (its cylinder face) or its top vertex (the seam of its top circle); the
    counterpart is the same corner's hole in the large plate."""

    abstract = True
    FILLET = True
    RADIUS, THICKNESS = 4, 10
    PRIMARY = "se"  # the corner whose references take the plain names

    @property
    def COLUMNS(self):
        columns = (
            ("BoxL", 100, 140),
            ("BoxW", 60, 80),
            ("HoleX1", 15, 20),
            ("HoleX2", 85, 120),
            ("HoleY1", 15, 20),
            ("HoleY2", 45, 60),
        )
        return columns + (("Plain", 1, 0),) if self.FILLET else columns

    def makeFeatures(self, doc):
        self.addBox((S("BoxL"), S("BoxW"), self.THICKNESS))
        last = None
        for corner in CORNERS:
            hx, hy = HOLE_COLUMNS[corner]
            last = self.addHole(
                "Hole_" + corner, (S(hx), S(hy), -1), self.RADIUS, self.THICKNESS + 2
            )
        if self.FILLET:
            self.addFillet(doc, last)

    def centre(self, corner):
        hx, hy = HOLE_COLUMNS[corner]
        return self.value(hx), self.value(hy)

    def wall(self, corner):
        cx, cy = self.centre(corner)
        return face(
            "cylinder",
            where=lambda f: abs(f.Surface.Center.x - cx) < TOL
            and abs(f.Surface.Center.y - cy) < TOL,
        )

    def topVertex(self, corner):
        cx, cy = self.centre(corner)
        top, r = self.THICKNESS, self.RADIUS
        return Predicate(
            "Vertex",
            f"hole top seam at ({cx}, {cy})",
            [
                lambda v, tol: abs(v.Point.z - top) < TOL
                and abs(math.hypot(v.Point.x - cx, v.Point.y - cy) - r) < TOL
            ],
        )

    def makeReferences(self, doc):
        for i, corner in enumerate(CORNERS):
            self.track(
                refNames("hole_wall", self.PRIMARY)[i],
                lambda c=corner: self.wall(c),
                lambda c=corner: self.wall(c),
            )
            if self.FILLET:
                self.track(
                    refNames("hole_top_vertex", self.PRIMARY)[i],
                    lambda c=corner: self.topVertex(c),
                    lambda c=corner: self.topVertex(c),
                )


class VariantBoltHolesFillet(BoltHoles):
    """The plate with four holes becomes the larger plate with four holes and a rounded corner
    (a fillet on the vertical edge at the origin). The holes keep their count but not their
    face numbers. Each reference must follow its own hole, or break loudly."""

    AXES = ("M5", "E1")
    FILLET = True
    REFS = refNames("hole_wall", "se") + refNames("hole_top_vertex", "se")


class VariantBoltHolesSameTopology(BoltHoles):
    """The same plates without the rounded corner: the same topology, each reference must stay
    on its own hole."""

    FILLET = False
    REFS = refNames("hole_wall", "se")


# ---------------------------------------------------------------------------------------------
# Pockets in blocks
# ---------------------------------------------------------------------------------------------

BOX = (("BoxL", 10, 30), ("BoxW", 10, 20), ("BoxH", 5, 8))


class PocketBlock(Variants):
    """A 10 x 10 x 5 block with a pocket becomes a 30 x 20 x 8 block (BOX); the subclass adds its
    pockets or steps."""

    abstract = True

    def top(self):
        return self.value("BoxH")

    def makeBox(self):
        self.addBox((S("BoxL"), S("BoxW"), S("BoxH")))


class VariantPocketMoved(PocketBlock):
    """A pocket (3 x 3 x 1.5 at (2, 2)) in the small block, a pocket (4 x 4 x 2 at (13, 8)) in the
    large one: same topology, the pocket's floor follows its pocket. Reference: the floor."""

    COLUMNS = BOX + (
        ("PockX", 2, 13),
        ("PockY", 2, 8),
        ("PockL", 3, 4),
        ("PockW", 3, 4),
        ("PockH", 1.5, 2),
    )
    REFS = ("pocket_floor",)

    def makeFeatures(self, doc):
        self.makeBox()
        self.addCut(
            "Pocket",
            (S("PockX"), S("PockY"), S("BoxH") + " - " + S("PockH")),
            (S("PockL"), S("PockW"), S("PockH")),
        )

    def floor(self):
        return self.planeUp(self.top() - self.value("PockH"))

    def makeReferences(self, doc):
        self.track("pocket_floor", self.floor, self.floor)


class VariantOnePocketToTwo(PocketBlock):
    """The small block's pocket (3 x 3 x 1.5 at (2, 2)) becomes two pockets (4 x 4 x 2 at (3, 3)
    and (20, 12)) in the large block: two look-alike floors, no counterpart a person could name
    without looking. The reference must break loudly."""

    AXES = ("M5", "E1")
    COLUMNS = BOX + (
        ("PockX", 2, 3),
        ("PockY", 2, 3),
        ("PockL", 3, 4),
        ("PockW", 3, 4),
        ("PockH", 1.5, 2),
        ("Pock2X", 40, 20),
    )
    REFS = ("pocket_floor",)

    def makeFeatures(self, doc):
        self.makeBox()
        z = S("BoxH") + " - " + S("PockH")
        size = (S("PockL"), S("PockW"), S("PockH"))
        self.addCut("Pocket", (S("PockX"), S("PockY"), z), size)
        # Away from the small block (x = 40): no pocket there. Not suppressed: the copy of a
        # variant switch leaves a primitive's Placement expressions unevaluated where the
        # switch unsuppresses it (found porting this case).
        self.addCut("Pocket2", (S("Pock2X"), 12, z), size)

    def floor(self):
        return self.planeUp(self.top() - self.value("PockH"))

    def makeReferences(self, doc):
        self.track("pocket_floor", self.floor, lambda: BROKEN if self.edited else self.floor())


class VariantPocketToLStep(PocketBlock):
    """The small block's pocket (3 x 3 x 1.5 at (2, 2)) is gone in the large block, which has an
    L step instead (the part from x = 15 and 4 above the bottom cut away): the topology changes
    and the pocket's top corners have no counterpart. The references must break loudly, never
    land on the step's corners."""

    COLUMNS = BOX + (
        ("PockOff", 0, 1),
        ("StepX", 15, 15),
        ("StepL", 5, 15),
        ("StepZ", 4, 4),
        ("StepH", 1, 4),
    )
    CORNER_NAMES = (
        "pocket_top_corner",
        "pocket_top_corner_se",
        "pocket_top_corner_ne",
        "pocket_top_corner_nw",
    )
    POCKET_CORNERS = ((2, 2), (5, 2), (5, 5), (2, 5))  # in the small block, 5 high
    REFS = CORNER_NAMES

    def makeFeatures(self, doc):
        self.makeBox()
        self.addCut("Pocket", (2, 2, S("BoxH") + " - 1.5"), (3, 3, 1.5), off=S("PockOff"))
        # In the small block the step is out of reach (x = 15 on a block 10 long), not
        # suppressed: see VariantOnePocketToTwo.
        self.addCut(
            "Step",
            (S("StepX"), 0, S("StepZ")),
            (S("StepL"), S("BoxW"), S("StepH")),
        )

    def makeReferences(self, doc):
        for name, (x, y) in zip(self.CORNER_NAMES, self.POCKET_CORNERS):
            self.track(
                name,
                lambda x=x, y=y: vertex((x, y, 5)),
                lambda x=x, y=y: BROKEN if self.edited else vertex((x, y, 5)),
            )


class FloorOnTop(PocketBlock):
    """The small block has a pocket in its interior, which makes its top face the third face; the
    large block has a corner notch whose floor is the third face. The top face's index names the
    notch floor on the large block (a plane with the same normal), not the top face. The
    precondition is checked after the switch."""

    abstract = True
    topSub = None

    def precondition(self):
        floor = self.names(self.link, self.floorPredicate())
        if floor != [self.topSub]:
            raise ScenarioError(
                f"the notch floor is {floor}, not the small block's top face {self.topSub}: "
                "the case's numbering precondition no longer holds"
            )


class VariantTopologyChanged(FloorOnTop):
    """The small block (10 x 10 x 5, a 3 x 3 x 1.5 pocket at (2, 2)) becomes the large block
    (30 x 20 x 8, a 4 x 4 x 2 notch at the origin corner). `top_face_on_pocket_floor`: the small
    top face must follow to the large top face (z = 8), not the notch floor that has its index.
    `vertex_corner` (and `vertex_corner_<x><y><z>`, 1 for the far side): the block's corners must
    follow to the large block's corners; the notch takes the (0, 0, top) corner, which must
    break."""

    COLUMNS = BOX + (
        ("PockX", 2, 0),
        ("PockY", 2, 0),
        ("PockL", 3, 4),
        ("PockW", 3, 4),
        ("PockH", 1.5, 2),
    )
    BITS = tuple((x, y, z) for x in (1, 0) for y in (1, 0) for z in (1, 0))
    CORNER_NAMES = tuple(
        "vertex_corner" if bits == (1, 1, 1) else "vertex_corner_%d%d%d" % bits for bits in BITS
    )
    REFS = ("top_face_on_pocket_floor",) + CORNER_NAMES

    def makeFeatures(self, doc):
        self.makeBox()
        self.addCut(
            "Pocket",
            (S("PockX"), S("PockY"), S("BoxH") + " - " + S("PockH")),
            (S("PockL"), S("PockW"), S("PockH")),
        )

    def topPredicate(self):
        return self.planeUp(self.top())

    def floorPredicate(self):
        return self.planeUp(self.top() - self.value("PockH"))

    def corner(self, bits):
        x, y, z = bits
        return vertex((self.value("BoxL") * x, self.value("BoxW") * y, self.top() * z))

    def cornerExpected(self, bits):
        if self.edited and bits == (0, 0, 1):
            return BROKEN
        return self.corner(bits)

    def makeReferences(self, doc):
        holder = self.track("top_face_on_pocket_floor", self.topPredicate, self.topPredicate)
        self.topSub = holder.Sub[1][0]
        for name, bits in zip(self.CORNER_NAMES, self.BITS):
            self.track(name, lambda b=bits: self.corner(b), lambda b=bits: self.cornerExpected(b))


class VariantNotch4m(FloorOnTop):
    """A 300 x 300 x 4000 post with a 100 x 100 x 60 notch in its interior at (100, 100) becomes
    the post with the notch at the corner (0, 0): the notch floor, 60 mm under the top (0.985 of
    the height), has the index of the post's top face. The reference to the top face must follow
    to the top face (z = 4000), not the floor."""

    AXES = ("M5", "E5", "X4:4000")
    COLUMNS = (("NotchX", 100, 0), ("NotchY", 100, 0))
    HEIGHT = 4000
    REFS = ("top_face",)

    def makeFeatures(self, doc):
        self.addBox((300, 300, self.HEIGHT))
        self.addCut("Notch", (S("NotchX"), S("NotchY"), self.HEIGHT - 60), (100, 100, 60))

    def topPredicate(self):
        return self.planeUp(self.HEIGHT)

    def floorPredicate(self):
        return self.planeUp(self.HEIGHT - 60)

    def makeReferences(self, doc):
        holder = self.track("top_face", self.topPredicate, self.topPredicate)
        self.topSub = holder.Sub[1][0]


# ---------------------------------------------------------------------------------------------
# The link's copy, an expression, an undo
# ---------------------------------------------------------------------------------------------


class FilletBlock(Variants):
    """A 10 x 10 x 5 block becomes a 30 x 20 x 8 block with a fillet (radius 2) on the vertical
    edge at the origin: the top face keeps its height and loses a corner, and the numbering of
    the faces changes."""

    abstract = True
    COLUMNS = BOX + (("Plain", 1, 0),)

    def top(self):
        return self.value("BoxH")

    def topPredicate(self):
        return self.planeUp(self.top())

    def makeFeatures(self, doc):
        box = self.addBox((S("BoxL"), S("BoxW"), S("BoxH")))
        self.addFillet(doc, box)


class VariantCopyGroupDirect(Variants):
    """A reference straight into the variant copy (a joint's `Reference1` to the copy's top face,
    not through the link). The link is switched to Large first (the copy is made), then a cell of
    the part's sheet that no box uses is edited: the link remakes its copy and the old one is
    removed. Nothing can follow; the reference is emptied, which its consumer reports."""

    COLUMNS = BOX
    REFS = ("reference1",)

    def makeFeatures(self, doc):
        self.addBox((S("BoxL"), S("BoxW"), S("BoxH")))

    def makeReferences(self, doc):
        self.link.Config = "Large"
        doc.recompute()
        copy = self.link.LinkedObject
        if copy is self.body:
            raise ScenarioError("no copy was made")
        self.track(
            "reference1",
            lambda: self.planeUp(8),
            lambda: BROKEN if self.edited else self.planeUp(8),
            target=copy,
        )

    def edit(self, doc):
        self.edited = True
        old = self.link.LinkedObject
        self.sheet.set("A10", "note")
        doc.recompute()
        doc.recompute()
        if self.link.LinkedObject is old:
            raise ScenarioError("the link's copy wasn't remade")


class VariantExpressionArea(FilletBlock):
    """An expression `LinkA.<<Face6>>._shape.Area` (the small block's top face, area 100) across
    the switch to the filleted large block, where the numbering of the faces has changed. The
    value must be the large top face's area (599.14), or the expression must fail (loud). The
    expression holds no stored reference the harness could read, so `judge` compares the value."""

    REFS = ("link_face6_area",)

    def makeReferences(self, doc):
        face6 = self.link.Shape.getElement("Face6")
        if abs(face6.BoundBox.ZMin - 5) > TOL or abs(face6.BoundBox.ZMax - 5) > TOL:
            raise ScenarioError("Face6 isn't the small block's top face")
        holder = doc.addObject("App::FeaturePython", "Ref_link_face6_area")
        holder.addProperty("App::PropertyFloat", "Area")
        holder.setExpression("Area", "LinkA.<<Face6>>._shape.Area")
        self.ref(
            "link_face6_area", holder, "Area", lambda: OwnOrBroken(self.topPredicate())
        )

    def judge(self, ref, step):
        owner = self.doc.getObject(ref.owner)
        expectation = ref.expect()
        shape = self.link.Shape
        expected = shape.getElement(expectedNames(expectation.expected, shape)[0]).Area
        result = Result(type(self).__name__, ref.name, self.config, step)
        got = None
        if not owner.isValid():
            verdict, detail = "broken", owner.getStatusString()
        else:
            got = owner.Area
            if abs(got - expected) < 1e-6:
                verdict, detail = "correct", ""
            else:
                verdict, detail = "wrong", f"{owner.Name}.Area is {got}, not {expected}"
        result.verdict = verdict
        result.record.update(
            scenario=type(self).__name__,
            area=self.area,
            ref=ref.name,
            config=self.config,
            platform=sys.platform,
            step=step,
            consumer=f"{owner.Name}.Area",
            target=self.link.Name,
            subs=[],
            names=[] if got is None else [f"Area {got:.6f}"],
            expect=repr(expectation),
            expected_names=[f"Area {expected:.6f}"],
            stored=None,
            outcome=verdict,
            detail=detail,
            verdict=verdict,
            classes=list(self.CLASSES),
            axes=list(self.AXES),
            issue=self.ISSUE,
            found_by=self.FOUND_BY,
            tier=self.TIER,
            warning="Warning" in owner.State,
        )
        return result


class VariantRetargetUndo(FilletBlock):
    """The switch to the filleted large block inside a transaction, undone and redone, all before
    the first recompute of the new copy. The link's pending retarget check on the reference must
    survive the undo and the redo: after the recompute the reference holds the top face (z = 8)
    or is marked missing, never the side face that has its index."""

    AXES = ("M5", "E9")
    REFS = ("pending_check",)

    def makeReferences(self, doc):
        self.track(
            "pending_check", self.topPredicate, lambda: OwnOrBroken(self.topPredicate())
        )

    def edit(self, doc):
        self.edited = True
        doc.UndoMode = 1
        doc.openTransaction("Switch the variant")
        self.link.Config = "Large"
        doc.commitTransaction()
        doc.undo()
        doc.redo()
        doc.recompute()
        doc.recompute()
