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

"""Sketch edits: the profile of a pad changes, and the references downstream follow it."""

import os
import re
import shutil
import tempfile
import zipfile

import FreeCAD as App
import Part

from .harness import (
    BROKEN,
    Attached,
    Broken,
    Filleted,
    Guessed,
    ReachesFace,
    Reopens,
    Scenario,
    ScenarioError,
    X,
    Y,
    Z,
    edge,
    face,
)
from . import models as m

V = App.Vector


class SketchEdit(Scenario):
    """A rectangle (0..20 x 0..10, lines: front, right, back, left) padded 10 high; a fillet on
    the right top edge; a tunnel (y, z 3..7) pocketed from the left face up to the right face;
    a sketch attached to the pad's top face."""

    abstract = True
    area = "sketch edits"
    MULTI = True
    REFS = ("top_face", "right_face", "right_top_edge")
    width, depth, height = 20, 10, 10

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.height))

    def rightFace(self):
        return face("plane", normal=X, through=(self.width, 0, 0))

    def rightTopEdge(self):
        return edge("line", direction=Y, through=(self.width, 0, self.height))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.rightTopEdge()))
        fillet.Radius = 1
        doc.recompute()
        # on the left face, facing -X, so the pocket runs +X; sketch x = global z, y = global y
        at = App.Placement(V(0, 0, 0), m.rotationFromAxes((0, 0, 1), (0, 1, 0)))
        tunnel = m.sketch(doc, "Tunnel", m.rectangle(3, 3, 7, 7), body, placement=at)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = tunnel
        pocket.Type = "UpToFace"
        pocket.UpToFace = (fillet, self.names(fillet, self.rightFace()))
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(pad, self.names(pad, self.topFace())[0])]
        onTop.MapMode = "FlatFace"
        self.ref("top_face", onTop, "AttachmentSupport", self.topFace, Attached())
        self.ref("right_face", pocket, "UpToFace", self.rightFace, ReachesFace())
        self.ref("right_top_edge", fillet, "Base", self.rightTopEdge, Filleted(1))


class SketchMoveSide(SketchEdit):
    """The right side moves from x = 20 to x = 24; its line keeps its geometry ID."""

    def edit(self, doc):
        lines = {0: ((0, 0), (24, 0)), 1: ((24, 0), (24, 10)), 2: ((24, 10), (0, 10))}
        m.setLines(doc.Profile, lines)
        self.width = 24


class SketchNotch(SketchEdit):
    """A notch (x 8..12, 2 deep) is cut into the front side: four new lines, and the front line
    ends at the notch."""

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)


class SketchRedraw(SketchEdit):
    """The rectangle is deleted and drawn again from the right back corner, the other way
    round: the same geometry, every geometry ID new."""

    def edit(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)


class SolverRedrawShifted(Scenario):
    """A rectangle (0..20 x 0..10) padded 10 high, a fillet, radius 1, on its front right
    vertical edge (x = 20). The rectangle is drawn again 0.5 mm over in x: every geometry ID new,
    so no name relates the old edges to the new ones, and the edge's analogue is 0.5 mm away,
    beyond tier 3's strict reach (1 % of the diagonal) and within the wide one (5 %). With no
    structural candidate, solver documents guess it loudly (N2 5.2 G2, kind `geometric`; the Fable
    review of fork PR 117, finding 3); without the solver the reference breaks."""

    area = "sketch edits"
    REFS = ("corner_edge",)

    def cornerEdge(self):
        if not getattr(self, "redrawn", False):
            return edge("line", direction=Z, through=(20, 0, 0))
        if self.solver:
            return Guessed(edge("line", direction=Z, through=(20.5, 0, 0)))
        return BROKEN

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.cornerEdge()))
        fillet.Radius = 1
        self.ref("corner_edge", fillet, "Base", self.cornerEdge, Filleted(1))

    def edit(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(20.5, 10), (20.5, 0), (0.5, 0), (0.5, 10)]), False)
        self.redrawn = True


class SolverRedrawShiftedReopened(Reopens, SolverRedrawShifted):
    """SolverRedrawShifted, then the document saved, closed and opened again: the guess comes
    back with its record and warning (ops#133). A regression guard: it passes on `integration`
    before ops#133's fix too (after a redraw with new IDs the original's name gives nothing, so
    no snap-back entry was built; the Fable review of fork PR 122, 3a)."""

    steps = ("edit", "reopen")


class SketchReaddLine(SketchEdit):
    """The right side's line is deleted and drawn again in the same place. The sketcher's
    geometry history gives it its old geometry ID back (SketchObject::generateId matches the end
    points of deleted geometry), so this checks a delete and re-add, not a new ID."""

    def edit(self, doc):
        doc.Profile.delGeometry(1)
        doc.Profile.addGeometry(Part.LineSegment(V(20, 0, 0), V(20, 10, 0)), False)


class SolverOuterWireGains(Scenario):
    """The reference solver's tier 1 (ops#7): a rectangle (0..20 x 0..10) padded 10 high, a
    sketch attached to the pad's top face and a fillet on its front top edge. The profile's right
    back corner is cut off by a new line from (20, 7) to (17, 10): the outer wire gains an edge,
    so the top face's name changes, and its old name's edges are all in the new one's."""

    area = "sketch edits"
    MULTI = True
    REFS = ("top_face", "front_top_edge")

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def frontTopEdge(self):
        return edge("line", direction=X, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.frontTopEdge()))
        fillet.Radius = 1
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(pad, self.names(pad, self.topFace())[0])]
        onTop.MapMode = "FlatFace"
        self.ref("top_face", onTop, "AttachmentSupport", self.topFace, Attached())
        self.ref("front_top_edge", fillet, "Base", self.frontTopEdge, Filleted(1))

    def edit(self, doc):
        m.setLines(doc.Profile, {1: ((20, 0), (20, 7)), 2: ((17, 10), (0, 10))})
        doc.Profile.addGeometry(Part.LineSegment(V(20, 7, 0), V(17, 10, 0)), False)


# ---------------------------------------------------------------------------------------------
# The reference solver's tiers 2 and 3 (ops#7, Task 2 PR 4): sketches drawn again, so that no
# name relates the old elements to the new ones and only geometry can. SketchRedraw's
# right_top_edge is the case where it should (the edge is back in its place).
# ---------------------------------------------------------------------------------------------


class SolverSketchReplacedMoved(Scenario):
    """A rectangle (0..20 x 0..10) padded 10 high, a fillet on its right top edge. The rectangle
    is deleted and drawn again 5 mm over (x 5..25): every geometry ID is new, and the old edge's
    place is empty. The nearest edge along Y is 5 mm away, so the fillet's reference breaks
    rather than move to it."""

    area = "sketch edits"
    MULTI = True
    REFS = ("right_top_edge",)
    redrawn = False

    def rightTopEdge(self):
        if self.redrawn:
            return BROKEN
        return edge("line", direction=Y, through=(20, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.rightTopEdge()))
        fillet.Radius = 1
        self.ref("right_top_edge", fillet, "Base", self.rightTopEdge, Filleted(1))

    def edit(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(25, 10), (25, 0), (5, 0), (5, 10)]), False)
        self.redrawn = True


class SolverTwinRotate(Scenario):
    """A plate (0..30 x 0..30, 5 high) with two round bosses (radius 3, 5 high) at (10, 15) and
    (20, 15) from one sketch, and a fillet on each boss's top circle. The bosses' sketch is
    replaced by two circles at (15, 10) and (15, 20): every name is new, and each old circle has
    two circles of its radius and axis, neither in its place. Both references break; neither
    takes a rotated boss."""

    area = "sketch edits"
    MULTI = True
    REFS = ("edge_a", "edge_b")
    replaced = False

    def topCircle(self, x):
        if self.replaced:
            return BROKEN
        return edge("circle", center=(x, 15, 10), radius=3)

    def edgeA(self):
        return self.topCircle(10)

    def edgeB(self):
        return self.topCircle(20)

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(0, 0, 30, 30), body)
        m.pad(body, plate, 5, name="PlatePad")
        bosses = m.sketch(doc, "Bosses", [m.circle(10, 15, 3), m.circle(20, 15, 3)], body, z=5)
        bossPad = m.pad(body, bosses, 5, name="BossPad")
        doc.recompute()
        for ref, predicate in (("edge_a", self.edgeA), ("edge_b", self.edgeB)):
            fillet = body.newObject("PartDesign::Fillet", "Fillet_" + ref)
            fillet.Base = (bossPad, self.names(bossPad, predicate()))
            fillet.Radius = 0.5
            self.ref(ref, fillet, "Base", predicate, Filleted(0.5))
            doc.recompute()

    def edit(self, doc):
        doc.Bosses.deleteAllGeometry()
        doc.Bosses.addGeometry([m.circle(15, 10, 3), m.circle(15, 20, 3)], False)
        self.replaced = True


# Policy D (ops#127, design note N3 6.1): a guess needs a surviving source.


class PolicyDCorner(Scenario):
    """SolverRedrawShifted's model: a rectangle (0..20 x 0..10) padded 10 high, a fillet,
    radius 1, on its front right vertical edge (x = 20). Subclasses move that edge 0.5 mm in x,
    beyond tier 3's strict reach (1 % of the diagonal) and within G2's wide one (5 %)."""

    abstract = True
    area = "sketch edits"
    REFS = ("corner_edge",)
    moved = False

    def shiftedCorner(self):
        return edge("line", direction=Z, through=(20.5, 0, 0))

    def movedExpectation(self):
        raise NotImplementedError

    def cornerEdge(self):
        if not self.moved:
            return edge("line", direction=Z, through=(20, 0, 0))
        return self.movedExpectation()

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.cornerEdge()))
        fillet.Radius = 1
        self.ref("corner_edge", fillet, "Base", self.cornerEdge, Filleted(1))


class SketchLineRedrawnShifted(PolicyDCorner):
    """The rectangle's right line deleted and drawn again at x = 20.5 in the same sketch, the
    front and back lines stretched to meet it (they keep their IDs). The corner edge is made
    from the front line's end and the new line's start, so its name keeps the front line's
    vertex: V2 follows it by name, and the solver's tier 1 resolves it plainly (its only
    structural candidate), with no guess and no warning. N3 6.1 expected a guess (G2); the run
    showed structure decides (ops#127 P8a). V1 breaks it."""

    def movedExpectation(self):
        return BROKEN if self.mode == "V1" else self.shiftedCorner()

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (20.5, 0)), 2: ((20.5, 10), (0, 10))})
        doc.Profile.delGeometry(1)
        doc.Profile.addGeometry(m.polyline([(20.5, 0), (20.5, 10)]), False)
        self.moved = True


class NewSketchShifted(PolicyDCorner):
    """The rectangle drawn 0.5 mm over in x in a new sketch object, which the pad then takes as
    its profile: no name relates the new edges to the old ones, and the new sketch isn't the
    original's source. Policy D: no guess; the reference breaks with the moved corner edge
    listed first (N3 4.4). Without the solver it breaks too."""

    def movedExpectation(self):
        return Broken(self.shiftedCorner())

    def edit(self, doc):
        redrawn = m.sketch(
            doc,
            "Redrawn",
            m.polygon([(20.5, 10), (20.5, 0), (0.5, 0), (0.5, 10)]),
            self.bodyObject,
        )
        doc.Pad.Profile = redrawn
        self.moved = True


class IndexOnlyMoved(PolicyDCorner):
    """The fillet's reference saved as an index-only missing reference (`?EdgeN`, its
    fingerprint kept, no name: N2 5.4, the P6 review's 4b), the file opened again, and the
    rectangle's right side moved to x = 20.5 (its lines keep their IDs) before the first
    recompute. With no name it has no source: policy D breaks it with the moved edge listed
    first (N3 Q3). Without the solver it breaks."""

    steps = ("staleAndMoved",)

    def movedExpectation(self):
        return Broken(self.shiftedCorner())

    def staleAndMoved(self, doc):
        index = doc.Fillet.Base[1][0]
        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        path = os.path.join(self.folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        xml = files["Document.xml"].decode("utf-8")
        xml, count = re.subn(
            r'<Sub value="%s" shadow="[^"]*"' % index, '<Sub value="?%s"' % index, xml
        )
        if count != 1:
            raise ScenarioError(f"the fillet's sub {index} isn't saved once: {count}")
        # Opened with the solver off: on, the open itself would find the edge in its place
        # (strict tier 3), before the edit. openDocument() puts the configuration's back.
        xml = re.sub(
            r'(<Property name="ReferenceSolver"[^>]*>\s*<Bool value=")true(")', r"\1false\2", xml
        )
        files["Document.xml"] = xml.encode("utf-8")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        self.doc = doc = self.openDocument(path)
        lines = {0: ((0, 0), (20.5, 0)), 1: ((20.5, 0), (20.5, 10)), 2: ((20.5, 10), (0, 10))}
        m.setLines(doc.Profile, lines)
        self.moved = True

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class SlotRedrawnShifted(Scenario):
    """G1 as a scenario (TestNamingSolver's testStructuralCandidatesAreGuessedByTheNearest): a
    pad (0..20 x 0..10, 10 high) with a slot (x 6..14, y 3..7) pocketed through it, a fillet,
    radius 0.5, on the slot's bottom edge at y = 3. The slot is drawn again 0.5 mm over in y (new
    IDs): structure keeps the slot's two bottom edges along x (the pocket's), neither within
    tier 3's strict reach; the wide one holds the nearer, y = 3.5. In solver documents it is
    guessed (G1, kind `nearest`); without the solver it breaks with both as candidates."""

    area = "sketch edits"
    REFS = ("slot_edge",)
    redrawn = False

    def slotEdge(self):
        if not self.redrawn:
            return edge("line", direction=X, through=(0, 3, 0))
        nearer = edge("line", direction=X, through=(0, 3.5, 0))
        if self.solver:
            return Guessed(nearer)
        return Broken(nearer, edge("line", direction=X, through=(0, 7.5, 0)))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        slot = m.sketch(doc, "SlotSketch", m.rectangle(6, 3, 14, 7), body, z=10)
        pocket = m.pocketThroughAll(body, slot)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, self.slotEdge()))
        fillet.Radius = 0.5
        self.ref("slot_edge", fillet, "Base", self.slotEdge, Filleted(0.5))

    def edit(self, doc):
        doc.SlotSketch.deleteAllGeometry()
        doc.SlotSketch.addGeometry(m.polygon([(14, 7.5), (14, 3.5), (6, 3.5), (6, 7.5)]), False)
        self.redrawn = True


class SlotRedrawnShiftedReopened(Reopens, SlotRedrawnShifted):
    """SlotRedrawnShifted, then the document saved, closed and opened again: the guess comes
    back with its record and warning (ops#133). A regression guard: it passes on `integration`
    before ops#133's fix too (after a redraw with new IDs the original's name gives nothing, so
    no snap-back entry was built; the Fable review of fork PR 122, 3a)."""

    steps = ("edit", "reopen")
