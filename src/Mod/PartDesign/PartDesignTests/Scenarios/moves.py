# SPDX-License-Identifier: LGPL-2.1-or-later

"""Moved elements (ops#105): a sketch edit moves a referenced element while its geometry ID, and
so its name, stays. A reference whose element moved while another element took its place is
ambiguous (its name says one, the geometry the other), and the reference solver breaks it,
naming both. An element that moved alone keeps its reference. Without the solver the name
decides: the reference follows the moved element (listed in ops105-moved-exact.txt)."""

import os
import shutil
import tempfile

import FreeCAD as App

from .harness import Broken, ExternalCoincides, Filleted, Scenario, X, Y, Z, edge, face, pieces
from . import models as m

V = App.Vector


def moveCircles(sketch, centres):
    """Moves circles {geometry index: (x, y)} in one assignment; they keep their geometry IDs."""
    geometry = sketch.Geometry
    for index, (x, y) in centres.items():
        geometry[index].Center = V(x, y, 0)
    sketch.Geometry = geometry


class BossEdit(Scenario):
    """A plate (0..30 x 0..30, 5 high) with two round bosses (radius 3, 5 high) from one sketch,
    a at (10, 15) and b at (20, 15), and a fillet on each boss's top circle, radius 0.5 on a and
    0.75 on b: with equal radii a swap gives the same solid. Subclasses move the circles in
    place (`moved`, {boss: (x, y)}) and say which references are ambiguous (`ambiguous`)."""

    abstract = True
    area = "moves"
    MULTI = True
    REFS = ("edge_a", "edge_b")
    radii = {"a": 0.5, "b": 0.75}
    start = {"a": (10, 15), "b": (20, 15)}
    moved = {}
    ambiguous = ()  # the references that should break, with the places they hold as candidates
    edited = False

    def centre(self, boss):
        return self.moved.get(boss, self.start[boss]) if self.edited else self.start[boss]

    def topCircle(self, boss):
        x, y = self.centre(boss)
        return edge("circle", center=(x, y, 10), radius=3)

    def topCircleAt(self, x, y):
        return edge("circle", center=(x, y, 10), radius=3)

    def expected(self, boss):
        if self.edited and boss in self.ambiguous:
            # the element at the old place, and the one the name holds
            return Broken(self.topCircleAt(*self.start[boss]), self.topCircle(boss))
        return self.topCircle(boss)

    def edgeA(self):
        return self.expected("a")

    def edgeB(self):
        return self.expected("b")

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(0, 0, 30, 30), body)
        m.pad(body, plate, 5, name="PlatePad")
        circles = [m.circle(*self.start["a"], 3), m.circle(*self.start["b"], 3)]
        bosses = m.sketch(doc, "Bosses", circles, body, z=5)
        bossPad = m.pad(body, bosses, 5, name="BossPad")
        doc.recompute()
        self.addConsumers(doc, body, bossPad)

    def addConsumers(self, doc, body, bossPad):
        for boss, ref, predicate in (("a", "edge_a", self.edgeA), ("b", "edge_b", self.edgeB)):
            fillet = body.newObject("PartDesign::Fillet", "Fillet_" + boss)
            fillet.Base = (bossPad, self.names(bossPad, predicate()))
            fillet.Radius = self.radii[boss]
            self.ref(ref, fillet, "Base", predicate, Filleted(self.radii[boss]))
            doc.recompute()

    def moveBosses(self, doc, centres):
        moveCircles(doc.Bosses, {0 if boss == "a" else 1: c for boss, c in centres.items()})

    def edit(self, doc):
        self.moveBosses(doc, self.moved)
        self.edited = True


class BossesTradePlaces(BossEdit):
    """The circles trade places in one edit: the shape is unchanged, each fillet's circle moved
    and the other's sits where it was. Both references are ambiguous: the solver breaks both
    (V2 swaps the fillets silently)."""

    moved = {"a": (20, 15), "b": (10, 15)}
    ambiguous = ("a", "b")


class SymmetricBossSwap(BossEdit):
    """The circles move to (15, 10) and (15, 20): both moved, neither has anything at its old
    place, so each fillet follows its own circle (ops#105 Q1)."""

    moved = {"a": (15, 10), "b": (15, 20)}


class SingleBossMoved(BossEdit):
    """Boss a moves to (10, 25), its old place left empty: its fillet follows it."""

    moved = {"a": (10, 25)}


class BossMovedOntoOther(BossEdit):
    """Boss a moves onto b's place, b to (20, 25): a moved alone (nothing at its old place) and
    keeps its fillet; b's place is a's now, so b's reference is ambiguous."""

    moved = {"a": (20, 15), "b": (20, 25)}
    ambiguous = ("b",)


class BossesTradePlacesOneFillet(BossEdit):
    """As BossesTradePlaces with one fillet (0.5) holding both top circles: both of its
    references break, each with both circles as candidates."""

    REFS = ("edges",)
    moved = {"a": (20, 15), "b": (10, 15)}

    def topCircles(self):
        return edge("circle", radius=3, where=lambda e: abs(e.Curve.Center.z - 10) < 1e-6)

    def bothCircles(self):
        return Broken(self.topCircles()) if self.edited else pieces(self.topCircles())

    def addConsumers(self, doc, body, bossPad):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (bossPad, pieces(self.topCircles()).select(bossPad.Shape))
        fillet.Radius = 0.5
        self.ref("edges", fillet, "Base", self.bothCircles, Filleted(0.5))
        doc.recompute()


class BossesTradePlacesBack(BossEdit):
    """The circles trade places, then trade back: broken after the first step, and found again
    after the second, where each sits where its reference's fingerprint was."""

    steps = ("trade", "tradeBack")
    ambiguous = ("a", "b")
    traded = ("trade",)

    def expected(self, boss):
        self.edited = self.stepName in self.traded
        self.moved = {"a": (20, 15), "b": (10, 15)} if self.edited else {}
        return super().expected(boss)

    def trade(self, doc):
        self.moveBosses(doc, {"a": (20, 15), "b": (10, 15)})

    def tradeBack(self, doc):
        self.moveBosses(doc, self.start)


class BossesTradePlacesReopened(BossesTradePlacesBack):
    """As BossesTradePlacesBack, with the document saved, closed and opened again between the
    steps: the broken references keep their fingerprints in the file and break again."""

    steps = ("trade", "reopen", "tradeBack")
    traded = ("trade", "reopen")

    def reopen(self, doc):
        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        path = os.path.join(self.folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        self.doc = self.openDocument(path)

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class ExternalBossTradePlaces(BossEdit):
    """A sketch at z = 10 with boss a's top circle as external geometry; the circles trade
    places. The external edge is ambiguous: the solver breaks it and the sketch fails."""

    REFS = ("external_a",)
    moved = {"a": (20, 15), "b": (10, 15)}
    ambiguous = ("a",)

    def addConsumers(self, doc, body, bossPad):
        sketch = m.sketch(doc, "OnBoss", [], body, z=10)
        sketch.addExternal(bossPad.Name, self.names(bossPad, self.edgeA())[0])
        self.ref("external_a", sketch, "ExternalGeometry", self.edgeA, ExternalCoincides())
        doc.recompute()


class SquareBossEdit(BossEdit):
    """As BossEdit with square bosses (6 x 6, lines: front, right, back, left) centred at
    (10, 15) and (20, 15), and a sketch attached (FlatFace) to a face of boss a."""

    abstract = True
    REFS = ("face_a",)

    def square(self, x, y):
        return m.rectangle(x - 3, y - 3, x + 3, y + 3)

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(0, 0, 30, 30), body)
        m.pad(body, plate, 5, name="PlatePad")
        squares = self.square(*self.start["a"]) + self.square(*self.start["b"])
        m.sketch(doc, "Bosses", squares, body, z=5)
        bossPad = m.pad(body, doc.Bosses, 5, name="BossPad")
        doc.recompute()
        onBoss = body.newObject("Sketcher::SketchObject", "OnBoss")
        onBoss.AttachmentSupport = [(bossPad, self.names(bossPad, self.faceA())[0])]
        onBoss.MapMode = "FlatFace"
        # No outcome: a sketch on a coplanar face has the same placement, so the stored
        # sub-element decides (ops#55).
        self.ref("face_a", onBoss, "AttachmentSupport", self.faceA)
        doc.recompute()

    def moveBosses(self, doc, centres):
        lines = {}
        for boss, (x, y) in centres.items():
            first = 0 if boss == "a" else 4
            corners = [(x - 3, y - 3), (x + 3, y - 3), (x + 3, y + 3), (x - 3, y + 3)]
            for i in range(4):
                lines[first + i] = (corners[i], corners[(i + 1) % 4])
        m.setLines(doc.Bosses, lines)


class BossSideFaceTradePlaces(SquareBossEdit):
    """A sketch on boss a's right side face (x = 13); the bosses trade places, so b's right
    face is at x = 13 now. The attachment's placement differs between the two faces, so the
    reference is ambiguous."""

    moved = {"a": (20, 15), "b": (10, 15)}

    def rightFace(self, x):
        return face("plane", normal=X, contains=(x + 3, 15, 7.5))

    def faceA(self):
        if self.edited:
            return Broken(self.rightFace(10), self.rightFace(20))
        return self.rightFace(10)


class BossTopFaceTradePlacesFlatFace(SquareBossEdit):
    """A sketch on boss a's top face; the bosses trade places. b's top face sits where a's was,
    but a sketch on either gets the same placement (coplanar faces): the reference keeps a's
    top face (ops#105 Q4)."""

    moved = {"a": (20, 15), "b": (10, 15)}

    def faceA(self):
        x, y = self.centre("a")
        return face("plane", normal=Z, contains=(x, y, 10))


class RectangleEdit(Scenario):
    """A rectangle (0..20 x 0..10, lines: front, right, back, left) padded 10 high, a fillet on
    its right top edge. The rectangle's lines move in place (they keep their geometry IDs)."""

    abstract = True
    area = "moves"
    MULTI = True
    REFS = ("right_top_edge",)
    edited = False

    def topEdgeAlongY(self, x):
        return edge("line", direction=Y, through=(x, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.rightTopEdge()))
        fillet.Radius = 1
        self.ref("right_top_edge", fillet, "Base", self.rightTopEdge, Filleted(1))


class RectangleShiftedByWidth(RectangleEdit):
    """The rectangle moves right by its own width (x 20..40): its left line now lies where the
    right line was, so the left top edge sits where the filleted edge was. Ambiguous: the
    solver breaks the reference (V2 keeps the fillet on the moved right edge)."""

    def rightTopEdge(self):
        if self.edited:
            return Broken(self.topEdgeAlongY(20), self.topEdgeAlongY(40))
        return self.topEdgeAlongY(20)

    def edit(self, doc):
        m.moveRectangle(doc.Profile, 20, 0, 40, 10)
        self.edited = True


class RectangleResizedWider(RectangleEdit):
    """The right side moves from x = 20 to x = 30: the edge moved alone and keeps its fillet."""

    def rightTopEdge(self):
        return self.topEdgeAlongY(30 if self.edited else 20)

    def edit(self, doc):
        m.moveRectangle(doc.Profile, 0, 0, 30, 10)
        self.edited = True


class LinearPitchDoubled(Scenario):
    """A plate (0..60 x 0..10, 5 high) with a round boss (radius 2, 5 high) at (5, 5), patterned
    along X, 3 occurrences 10 apart ("Spacing" mode); a fillet (0.5) on instance 3's top edge.
    The spacing doubles: instance 3 moves to x = 45 and instance 2 lands on its old place
    (x = 25). Under the uniform rule (ops#105 Q3) the reference is ambiguous."""

    area = "moves"
    MULTI = True
    REFS = ("instance3_edge",)
    edited = False

    def topEdge(self, x):
        return edge("circle", center=(x, 5, 10), radius=2)

    def instance3Edge(self):
        if self.edited:
            return Broken(self.topEdge(25), self.topEdge(45))
        return self.topEdge(25)

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "PlateSketch", m.rectangle(0, 0, 60, 10), body)
        m.pad(body, plate, 5, "Plate")
        bossSketch = m.sketch(doc, "BossSketch", [m.circle(5, 5, 2)], body, z=5)
        boss = m.pad(body, bossSketch, 5, "Boss")
        pattern = doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = [boss]
        pattern.Direction = (m.originFeature(body, "X_Axis"), [""])
        pattern.Mode = "Spacing"
        pattern.Offset = 10
        pattern.Occurrences = 3
        body.addObject(pattern)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pattern, self.names(pattern, self.instance3Edge()))
        fillet.Radius = 0.5
        self.ref("instance3_edge", fillet, "Base", self.instance3Edge, Filleted(0.5))

    def edit(self, doc):
        doc.LinearPattern.Offset = 20
        self.edited = True
