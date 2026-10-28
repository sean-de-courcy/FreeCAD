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

"""Corpus cases (ops#504, class E's E2, invariant I-S10): a rewrite keeps the records of the
references it doesn't change. A pad's profile is drawn again from another corner, so a reference
into the pad becomes a warned guess of its element in the same place; then code sets the
property again, as a dialog's OK, a list edit, a Python assignment or the Sketcher's added
external do. The reference must keep its element and its owner its warning: an exact-looking pick
of a guess is the wrong set (`notes/naming-class-E.md` 3.2, rows N2-N11; `corpus/predicted/E.json`)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    Predicate,
    Scenario,
    Settled,
    Warned,
    X,
    Z,
    edge,
    face,
    pieces,
    vertex,
)
from PartDesignTests.Scenarios import models as m


class RewriteCase(Scenario):
    """A rectangle 0..20 x 0..10 padded 10 high (`Profile`, `Pad`). Steps: `redraw`, the profile
    drawn again from its right back corner the other way round (the same geometry, new IDs: the
    references become tier 3 guesses at the same place), then `rewrite`, the case's own rewrite.
    Before the redraw a reference holds its element plainly; after each step it holds it with
    its owner warned."""

    abstract = True
    area = "rewrite"
    CLASSES = ("E",)
    AXES = ("M1", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "attacker E"
    TIER = "F"
    steps = ("redraw", "rewrite")

    def padded(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        return body, pad

    def redraw(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)

    def kept(self, before, after=None):
        """The expectation: `before` plainly at the build, then warned; after the rewrite
        `after` (default `before`), warned."""

        def expect():
            if self.stepName is None:
                return before
            return Warned(after if after is not None and self.stepName == "rewrite" else before)

        return expect

    @staticmethod
    def bottomEdges(xs):
        """The pad's vertical edges at (x, 0) for x in xs, as one expected set."""
        return pieces(
            edge(
                "line",
                direction=Z,
                where=lambda e: abs(e.Vertexes[0].Point.y) < 1e-6
                and any(abs(e.Vertexes[0].Point.x - x) < 1e-6 for x in xs),
            )
        )


class LinkSubListAddValue(RewriteCase):
    """A holder's list references the pad's vertical edge at (20, 0); the rewrite adds the edge
    at (0, 0) before it (setValues without shadows, a count change)."""

    REFS = ("guessed_entry",)

    def build(self, doc):
        _, pad = self.padded(doc)
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSubListGlobal", "Refs")
        holder.Refs = [(pad, tuple(self.names(pad, self.corner())))]
        self.ref(
            "guessed_entry", holder, "Refs", self.kept(self.corner(), self.bottomEdges((0, 20)))
        )

    @staticmethod
    def corner():
        return edge("line", direction=Z, through=(20, 0, 0))

    def rewrite(self, doc):
        pad = doc.Pad
        [held] = doc.Holder.Refs[0][1]
        other = self.names(pad, edge("line", direction=Z, through=(0, 0, 0)))[0]
        doc.Holder.Refs = [(pad, (other, held))]


class SketchAddExternalKeepsGuess(RewriteCase):
    """A sketch above the pad projects its top front edge; the rewrite adds the top back edge as
    a second external (Sketcher's setExternalLinks: the kept link passed with its shadow)."""

    REFS = ("guessed_entry",)

    @staticmethod
    def front():
        return edge("line", direction=X, through=(0, 0, 10))

    @staticmethod
    def both():
        return pieces(
            edge(
                "line",
                direction=X,
                where=lambda e: abs(e.Vertexes[0].Point.z - 10) < 1e-6,
            )
        )

    def build(self, doc):
        body, pad = self.padded(doc)
        sketch = m.sketch(doc, "Projection", [], body, z=20)
        sketch.addExternal(pad.Name, self.names(pad, self.front())[0])
        self.ref("guessed_entry", sketch, "ExternalGeometry", self.kept(self.front(), self.both()))

    def rewrite(self, doc):
        back = self.names(doc.Pad, edge("line", direction=X, through=(0, 10, 10)))[0]
        doc.Projection.addExternal(doc.Pad.Name, back)


class BinderDropKeepsGuess(RewriteCase):
    """A SubShapeBinder of the pad's vertical edge at (20, 0); the rewrite adds the edge at
    (0, 0) to its Support (PropertyXLinkSubList.setValues(), as a drop does)."""

    REFS = ("guessed_entry",)

    def build(self, doc):
        _, pad = self.padded(doc)
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(pad, tuple(self.names(pad, LinkSubListAddValue.corner())))]
        self.ref(
            "guessed_entry",
            binder,
            "Support",
            self.kept(LinkSubListAddValue.corner(), self.bottomEdges((0, 20))),
        )

    def rewrite(self, doc):
        pad = doc.Pad
        [held] = doc.Binder.Support[0][1]
        other = self.names(pad, edge("line", direction=Z, through=(0, 0, 0)))[0]
        doc.Binder.Support = [(pad, (held, other))]


class AttacherRepickKeepsOthers(RewriteCase):
    """A datum line through the pad's top corners at (20, 0) and (20, 10); the rewrite re-picks
    the second to (0, 10), the list TaskAttacher writes (setValues of the whole list, no
    shadows)."""

    REFS = ("guessed_entry",)

    @staticmethod
    def corners(points):
        """The pad's vertices at the points, as one expected set."""
        return pieces(
            Predicate(
                "Vertex",
                f"at={points}",
                [lambda v, tol: any((v.Point - App.Vector(*p)).Length < tol for p in points)],
            )
        )

    def build(self, doc):
        body, pad = self.padded(doc)
        datum = body.newObject("PartDesign::Line", "Datum")
        first = self.names(pad, vertex((20, 0, 10)))[0]
        second = self.names(pad, vertex((20, 10, 10)))[0]
        datum.AttachmentSupport = [(pad, first), (pad, second)]
        datum.MapMode = "TwoPointLine"
        self.ref(
            "guessed_entry",
            datum,
            "AttachmentSupport",
            self.kept(
                self.corners([(20, 0, 10), (20, 10, 10)]), self.corners([(20, 0, 10), (0, 10, 10)])
            ),
        )

    def rewrite(self, doc):
        pad = doc.Pad
        held = doc.Datum.AttachmentSupport[0][1][0]
        other = self.names(pad, vertex((0, 10, 10)))[0]
        doc.Datum.AttachmentSupport = [(pad, held), (pad, other)]


class AttachmentEditorOk(RewriteCase):
    """A datum plane on the pad's top face; the rewrite assigns its support again unchanged, as
    the attachment editors' OK does."""

    REFS = ("guessed_entry",)

    @staticmethod
    def top():
        return face("plane", normal=Z, through=(0, 0, 10))

    def build(self, doc):
        body, pad = self.padded(doc)
        plane = body.newObject("PartDesign::Plane", "Datum")
        plane.AttachmentSupport = [(pad, self.names(pad, self.top())[0])]
        plane.MapMode = "FlatFace"
        self.ref("guessed_entry", plane, "AttachmentSupport", self.kept(self.top()))

    def rewrite(self, doc):
        doc.Datum.AttachmentSupport = doc.Datum.AttachmentSupport


class ThicknessOkUnchanged(RewriteCase):
    """A Part Thickness of the pad without its top face; the rewrite assigns Faces again
    unchanged, as its panel's OK does after Faces is pressed and released."""

    REFS = ("guessed_entry",)

    def build(self, doc):
        _, pad = self.padded(doc)
        thickness = doc.addObject("Part::Thickness", "Thickness")
        thickness.Faces = (pad, self.names(pad, AttachmentEditorOk.top()))
        thickness.Value = 1
        self.ref("guessed_entry", thickness, "Faces", self.kept(AttachmentEditorOk.top()))

    def rewrite(self, doc):
        doc.Thickness.Faces = doc.Thickness.Faces


class IndexRepickAfterEdit(RewriteCase):
    """The holder's guessed edge at (20, 0); then a notch on the profile's left side renumbers
    the pad's edges (the reference follows its edge, still warned); then the reference is set to
    the edge's old index name, which now names another edge. That is a new pick: it holds the
    edge at that index, plainly, with no record (E2's key: an index-only sub pairs only with an
    entry whose mapped name gives that index now)."""

    REFS = ("repicked_by_index",)
    steps = ("redraw", "notch", "repick")
    picked = None  # the predicate of the edge at the old index after the notch

    def build(self, doc):
        _, pad = self.padded(doc)
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSubListGlobal", "Refs")
        holder.Refs = [(pad, tuple(self.names(pad, LinkSubListAddValue.corner())))]
        self.oldIndex = None

        def expect():
            corner = LinkSubListAddValue.corner()
            if self.stepName is None:
                return corner
            if self.stepName == "repick":
                return Settled(self.picked)
            return Warned(corner)

        self.ref("repicked_by_index", holder, "Refs", expect)

    def notch(self, doc):
        [self.oldIndex] = doc.Holder.Refs[0][1]
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(
            m.polygon([(0, 0), (0, 3), (-2, 3), (-2, 7), (0, 7), (0, 10), (20, 10), (20, 0)]), False
        )
        doc.recompute()
        centre = doc.Pad.Shape.getElement(self.oldIndex).CenterOfMass
        self.picked = edge("line", where=lambda e: (e.CenterOfMass - centre).Length < 1e-6)

    def repick(self, doc):
        doc.Holder.Refs = [(doc.Pad, (self.oldIndex,))]
