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

"""Corpus cases (class E, E1; ops#264 e2): a sketch's link to a whole face gives one projected
line per edge of the face. After an edit of the profile, a constraint on one of those lines must
stay on the line from the same edge, or the sketch must fail naming the line that lost its edge.
Before E1 the k-th new line took the k-th old line's Id, so an edge added before the
constrained one moved the constraint to the next edge, the sketch valid and silent.

The model: a 20 x 20 square (lines front y = 0, right x = 20, back y = 20, left x = 0, kept by
their geometry IDs) padded 10 high; a sketch at z = 0 projects the pad's top face and has a
circle r 1 whose centre is on one projected line (PointOnObject, nothing else holding it). The
reference judged is the sketch's face link; its outcome is where the circle is.

The review's redraw cases f and g (the square redrawn 24 x 24 from another corner: the face is
found by a tier 3 guess and the sketch breaks) are `sketch_face_redraw.py`'s (fork PR 387)."""

import os
import re
import shutil
import tempfile
import zipfile

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Reopens, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

TOL = 1e-6


def reopenWithoutSources(scenario, doc):
    """The document saved, closed and opened again (scenario.openDocument()) with every external
    geometry's source name removed from its Document.xml: geometry as a build before ops#264 e2
    saved it (no `Source` attribute). Setting the facade's Source from Python doesn't reach the
    geometry a sketch holds, so a file is the only way to get it (the class E ruling, R9). The
    folder is scenario.folder (the scenario removes it). Returns the opened document."""
    scenario.folder = tempfile.mkdtemp(prefix="NamingScenario")
    path = os.path.join(scenario.folder, doc.Name + ".FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    with zipfile.ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    xml = files["Document.xml"].decode("utf-8")
    count = 0

    def strip(match):
        nonlocal count
        tag, n = re.subn(r' Source="[^"]*"', "", match.group(0))
        count += n
        return tag

    xml = re.sub(r'<GeoExtension [^>]*Sketcher::ExternalGeometryExtension[^>]*>', strip, xml)
    # a build before E1 saves no source names: its file is already one
    if count == 0 and hasattr(Sketcher.ExternalGeometryFacade, "Source"):
        raise RuntimeError("no external geometry with a source name in the saved file")
    files["Document.xml"] = xml.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return scenario.openDocument(path)


def lineOn(sketch, axis, value):
    """The GeoId of the sketch's one projected line on axis = value."""
    found = [
        -i - 1
        for i, g in enumerate(sketch.ExternalGeo)
        if i >= 2
        and hasattr(g, "StartPoint")
        and abs(getattr(g.StartPoint, axis) - value) < TOL
        and abs(getattr(g.EndPoint, axis) - value) < TOL
    ]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} projected lines on {axis} = {value}")
    return found[0]


class CircleStaysOnItsLine(Outcome):
    """The sketch computes, its PointOnObject constraint names the projected line on axis =
    value (`on` before the edit, `after` after it), and the circle's centre lies on it. With
    `defining`, that line is also still the one made defining (its flags went with it, row
    N1)."""

    def __init__(self, on, after, defining=False):
        self.on, self.after, self.defining = on, after, defining

    def compare(self, scenario, consumer, target, expectation):
        axis, value = self.on if scenario.stepName is None else self.after
        constraint = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        line = consumer.ExternalGeo[-constraint.Second - 1]
        ends = (line.StartPoint, line.EndPoint)
        if not all(abs(getattr(p, axis) - value) < TOL for p in ends):
            return False, f"the constraint is on the projected line {ends[0]} - {ends[1]}"
        centre = consumer.Geometry[constraint.First].Center
        if abs(getattr(centre, axis) - value) > TOL:
            return False, f"the circle's centre is at {centre}"
        if self.defining:
            facades = [
                (i, Sketcher.ExternalGeometryFacade(g))
                for i, g in enumerate(consumer.ExternalGeo)
                if i >= 2
            ]
            defining = [i for i, f in facades if f.testFlag("Defining")]
            if defining != [-constraint.Second - 1]:
                return False, f"defining lines {defining}, not the constraint's"
        return True, ""


class FaceLinkEdit(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "attacker E"
    TIER = "F"
    AXES = ("M8", "E5")
    REFS = ("circle_on_x0",)
    # the line the circle is on, (axis, value) before and after the edit
    on = ("x", 0)
    after = ("x", 0)
    defining = False

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 20), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        axis, value = self.on
        line = lineOn(sketch, axis, value)
        centre = (value, 5) if axis == "x" else (5, value)
        circle = sketch.addGeometry(m.circle(*centre, 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        if self.defining:
            sketch.toggleConstruction(line)
        self.ref(
            self.REFS[0],
            sketch,
            "ExternalGeometry",
            self.topFace,
            CircleStaysOnItsLine(self.on, self.after, defining=self.defining),
        )


class ExternalFaceCornerCut(FaceLinkEdit):
    """Row 149, the prototype's case: a 5 x 5 corner cut at (20, 20), the lines keeping their
    IDs: the top face gains an edge before the left one in its order. The circle moved to the
    back edge (y = 20). E1 pairs the left line by its source edge's name."""

    AXES = ("M8", "E1")
    TIER = "G"

    def edit(self, doc):
        m.setLines(doc.Profile, {1: ((20, 0), (20, 15)), 2: ((15, 20), (0, 20))})
        doc.Profile.addGeometry(m.polyline([(20, 15), (15, 20)]), False)


class ExternalFaceCornerCutReopened(Reopens, ExternalFaceCornerCut):
    """ExternalFaceCornerCut, then saved, closed and opened again: the lines' sources are saved
    with them, and the circle stays on x = 0."""

    AXES = ("M8", "E1", "E9")
    TIER = "F"
    steps = ("edit", "reopen")


class ExternalFaceConstructionFlag(ExternalFaceCornerCut):
    """Row N1: the same corner cut, the left line alone made defining. A geometry's flags go
    with its Id, so they followed the wrong pairing to the back line."""

    REFS = ("flag_on_x0",)
    TIER = "F"
    defining = True


class ExternalFaceDimension(FaceLinkEdit):
    """Row 149'', review case a: the right side moves to x = 25, the lines keeping their IDs.
    The face resolves by history (tier 1), so the right line, whose name and place both change,
    still pairs by position."""

    def edit(self, doc):
        m.setLines(
            doc.Profile, {0: ((0, 0), (25, 0)), 1: ((25, 0), (25, 20)), 2: ((25, 20), (0, 20))}
        )


class ExternalFaceDimensionMovedEdge(ExternalFaceDimension):
    """The same, the circle on the right edge, which moves: only its position pairs it."""

    REFS = ("circle_on_x20",)
    on = ("x", 20)
    after = ("x", 25)


class ExternalFaceDimension4m(FaceLinkEdit):
    """Review case e: ExternalFaceDimension at 200 times the size, a 4 m square."""

    AXES = ("M8", "E5", "X4:4000")
    k = 200

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10 * self.k))

    def build(self, doc):
        k = self.k
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20 * k, 20 * k), body)
        pad = m.pad(body, profile, 10 * k)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        circle = sketch.addGeometry(m.circle(0, 5 * k, k), False)
        sketch.addConstraint(
            Sketcher.Constraint("PointOnObject", circle, 3, lineOn(sketch, "x", 0))
        )
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, k))
        self.ref(
            "circle_on_x0",
            sketch,
            "ExternalGeometry",
            self.topFace,
            CircleStaysOnItsLine(("x", 0), ("x", 0)),
        )

    def edit(self, doc):
        k = self.k
        m.setLines(
            doc.Profile,
            {
                0: ((0, 0), (25 * k, 0)),
                1: ((25 * k, 0), (25 * k, 20 * k)),
                2: ((25 * k, 20 * k), (0, 20 * k)),
            },
        )


class ExternalFaceNotch(FaceLinkEdit):
    """Row 149v, review case d: a notch 4 wide and 3 deep in the back edge, the old lines
    keeping their IDs: four more edges before the left one, which keeps its name. The circle
    moved to the notch's side (x = 12)."""

    AXES = ("M8", "E1")

    def edit(self, doc):
        m.setLines(doc.Profile, {2: ((20, 20), (12, 20))})
        doc.Profile.addGeometry(
            m.polyline([(12, 20), (12, 17), (8, 17), (8, 20), (0, 20)]), False
        )


class ExternalFaceRedrawSame(FaceLinkEdit):
    """Row 149'''', review case c: the square's lines deleted and the same square drawn again
    from (20, 20), the other way round: every edge gets a new name and the face's order turns.
    The face is found by its place; geometry pairs all four lines."""

    AXES = ("M8", "E5", "E2")

    def edit(self, doc):
        doc.Profile.delGeometries(list(range(len(doc.Profile.Geometry))))
        doc.Profile.addGeometry(m.polygon([(20, 20), (20, 0), (0, 0), (0, 20)]), False)


class ExternalFaceRedrawResize(FaceLinkEdit):
    """Review case b: a 25 x 20 rectangle drawn from (25, 20), the other way round, instead of
    the square. The solver finds no top face for the reference (a candidate 2.5 mm off), so the
    sketch fails on the face, as before E1: loud. (The class note predicted `correct`: its
    probe paired the old lines with themselves, the face being gone.)"""

    def edit(self, doc):
        doc.Profile.delGeometries(list(range(len(doc.Profile.Geometry))))
        doc.Profile.addGeometry(m.polygon([(25, 20), (25, 0), (0, 0), (0, 20)]), False)


class ExternalFaceEdgeRemoved(FaceLinkEdit):
    """Row 149': the circle on the right line; the right side replaced by a V, (20, 0)-(25,
    10)-(20, 20). The projected line at x = 20 has no counterpart: the sketch fails naming it,
    and its constraint stays on it (before E1 it went to the V's first line)."""

    REFS = ("constrained_edge",)
    on = ("x", 20)
    after = ("x", 20)

    def edit(self, doc):
        doc.Profile.delGeometry(1)
        doc.Profile.addGeometry(m.polyline([(20, 0), (25, 10), (20, 20)]), False)

class ExternalFaceRedrawSidesNeighboursReversedFront(FaceLinkEdit):
    """Round 1's review case (`sketch_face_links_r1.py`), the circle on the front line: the left
    and right lines redrawn at x = -5 and 25 with the front and back lines left the other way
    round. The face's edges come in another order (back, right, front, left): by position the
    front line's circle went to the back line; place pairs it."""

    AXES = ("M8", "E2")
    FOUND_BY = "review pr384-r1"
    REFS = ("circle_on_y0",)
    on = ("y", 0)
    after = ("y", 0)

    def edit(self, doc):
        doc.Profile.delGeometries([1, 3])  # 0: front, 1: back
        geometry = doc.Profile.Geometry
        for index, start, end in ((0, (25, 0), (-5, 0)), (1, (-5, 20), (25, 20))):
            line = geometry[index]
            line.StartPoint = App.Vector(-777, -777, 0)  # away from both ends first
            line.EndPoint = App.Vector(*end, 0)
            line.StartPoint = App.Vector(*start, 0)
        doc.Profile.Geometry = geometry
        doc.Profile.addGeometry(m.polyline([(25, 0), (25, 20)]), False)
        doc.Profile.addGeometry(m.polyline([(-5, 20), (-5, 0)]), False)


class PointOnHoleCentre(Outcome):
    """The sketch computes, the point's Coincident constraint names a projected circle whose
    centre is at `on` before the edit and `after` after it, and the point is there."""

    def __init__(self, on, after):
        self.on, self.after = on, after

    def compare(self, scenario, consumer, target, expectation):
        x, y = self.on if scenario.stepName is None else self.after
        constraint = [c for c in consumer.Constraints if c.Type == "Coincident"][0]
        circle = consumer.ExternalGeo[-constraint.Second - 1]
        if abs(circle.Center.x - x) > TOL or abs(circle.Center.y - y) > TOL:
            return False, f"the constraint is on the projected circle at {circle.Center}"
        point = consumer.Geometry[constraint.First]
        if abs(point.X - x) > TOL or abs(point.Y - y) > TOL:
            return False, f"the point is at ({point.X}, {point.Y})"
        return True, ""


class ExternalFaceHoleRowMovedByPitch(Scenario):
    """The cloud review of fork PR 384 (model A): a 40 x 20 plate with two holes r 3 at (10, 10)
    and (20, 10), a row at pitch 10, padded 10 high; a sketch at z = 0 projects the top face
    (four lines and two circles) and has a point Coincident with the right hole's centre. The
    row moves +10 (holes at (20, 10) and (30, 10)), the circles keeping their IDs: the left hole
    lands on the right hole's old place. The point must follow its hole to (30, 10), or break;
    paired by place it stayed on the look-alike at (20, 10)."""

    area = "external geometry"
    CLASSES = ("E",)
    AXES = ("M8", "E5")
    ISSUE = "ops#264"
    FOUND_BY = "review pr384 cloud"
    TIER = "F"
    REFS = ("point_on_right_hole",)

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(
            doc, "Profile", m.rectangle(0, 0, 40, 20) + [m.circle(10, 10, 3), m.circle(20, 10, 3)],
            body,
        )
        pad = m.pad(body, profile, 10)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        right = [
            -i - 1
            for i, g in enumerate(sketch.ExternalGeo)
            if i >= 2 and hasattr(g, "Radius") and abs(g.Center.x - 20) < TOL
        ][0]
        point = sketch.addGeometry(Part.Point(App.Vector(20, 10, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("Coincident", point, 1, right, 3))
        self.ref(
            "point_on_right_hole",
            sketch,
            "ExternalGeometry",
            self.topFace,
            PointOnHoleCentre((20, 10), (30, 10)),
        )

    def edit(self, doc):
        geometry = doc.Profile.Geometry
        geometry[4].Center = App.Vector(20, 10, 0)
        geometry[5].Center = App.Vector(30, 10, 0)
        doc.Profile.Geometry = geometry


class ExternalFaceHoleRowMovedByPitchNoSource(ExternalFaceHoleRowMovedByPitch):
    """The same on geometry saved before E1: the file saved, its projected geometry's source names
    removed, and opened again before the edit (`models.reopenWithoutSources`). Setting Source from
    Python doesn't reach the sketch's geometry, so before round 4 this case scored the named
    geometry (the class E ruling, R9). Position and place disagree and nothing settles them: the
    point's hole breaks, loud (a listed cost, R7; decision 58)."""

    AXES = ("M8", "E5", "E9")

    def edit(self, doc):
        self.doc = doc = reopenWithoutSources(self, doc)
        super().edit(doc)

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class ExternalFaceNotchMovedByWidth(FaceLinkEdit):
    """The cloud review of fork PR 384 (model B): a 30 x 20 plate with a notch 8 wide and 5 deep
    in its back edge (walls at x = 6 and 14), padded 10 high; the circle on the notch's right
    wall (x = 14). The notch moves 8 to the right (walls at 14 and 22), its lines keeping their
    IDs: the left wall lands on the right wall's old place. The circle must follow to x = 22."""

    FOUND_BY = "review pr384 cloud"
    REFS = ("circle_on_notch_wall",)
    on = ("x", 14)
    after = ("x", 22)

    def build(self, doc):
        body = m.body(doc)
        outline = [(0, 0), (30, 0), (30, 20), (14, 20), (14, 15), (6, 15), (6, 20), (0, 20)]
        profile = m.sketch(doc, "Profile", m.polygon(outline), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        wall = lineOn(sketch, "x", 14)
        circle = sketch.addGeometry(m.circle(14, 17.5, 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, wall))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        self.ref(
            "circle_on_notch_wall",
            sketch,
            "ExternalGeometry",
            self.topFace,
            CircleStaysOnItsLine(self.on, self.after),
        )

    def edit(self, doc):
        m.setLines(
            doc.Profile,
            {
                2: ((30, 20), (22, 20)),
                3: ((22, 20), (22, 15)),
                4: ((22, 15), (14, 15)),
                5: ((14, 15), (14, 20)),
                6: ((14, 20), (0, 20)),
            },
        )
