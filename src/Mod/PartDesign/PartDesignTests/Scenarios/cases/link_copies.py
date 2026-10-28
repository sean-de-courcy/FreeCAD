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

"""Corpus cases (ops#523, class A; K8b's also class D, ops#503): copies of one object through
App::Links (and Part::Scale copies) in a Part MultiFuse or Compound.

The model is K8b's: a 40 x 20 x 10 box, a cylinder pin r = 2, 5 high, copies standing on the box
at (x, 10, 10); a PartDesign Body on the maker's result has datum points at the centres of the
copies' top rims (z = 15). Copy k's reference must follow copy k, or break where copy k is gone;
never land on another copy.

Before ops#523 a link added nothing to the names it handed over within one document, so two
copies' elements were told apart only by the maker's collision counter, in input order: removing
copy 0 gave copy 1 its names, silently. Now each link's copy carries a link copy section with the
link's ID (`CPY;L`, an array element `CPY;L<n>` with the array's ID), and copies by two copy makers
of one kind, and an element and its copy, are counter siblings to the solver (decision 157).

Ported from K8b's eight link cases (`corpus/inbox/D/k8b_copies.py`) and the real-link cases of the
design's prototype (`corpus/inbox/A/ops523/p523.py`, its `Today` column); the review's cases
(`PinAndLinkNeighbourMoved`, `ScaleAndLinkNeighbourMoved`, `ScaleBesideBaseMoved`) and the array
toggles are new.
"""

import os
import shutil
import tempfile

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    Attached,
    BROKEN,
    OwnOrBroken,
    Reopens,
    Scenario,
    edge,
    face,
)
from PartDesignTests.Scenarios import models as m


V = App.Vector


def datumPoint(body, target, sub, name):
    point = body.newObject("PartDesign::Point", name)
    point.AttachmentSupport = [(target, sub)]
    point.MapMode = "CenterOfCurvature"
    return point


def featureBase(body):
    return next(o for o in body.Group if o.TypeId == "PartDesign::FeatureBase")


class Copies(Scenario):
    """Copies k = 0.. of one pin at x = start[k]; references to each copy's top rim."""

    abstract = True
    area = "link-copies"
    CLASSES = ("A",)
    ISSUE = "ops#523"
    FOUND_BY = "ops#523 design prototype"
    TIER = "F"
    AXES = ("M5", "E1")
    maker = "Part::MultiFuse"
    mappedPin = False
    start = (10, 20)

    REFS = ("point_copy0", "point_copy1")

    def rim(self, k):
        x = self.at.get(k)
        return BROKEN if x is None else edge(center=(x, 10, 15), radius=2)

    def makePin(self, doc):
        if self.mappedPin:
            circle = doc.addObject("Part::Circle", "Circle")
            circle.Radius = 2
            pin = doc.addObject("Part::Extrusion", "Pin")
            pin.Base = circle
            pin.Dir = V(0, 0, 5)
            pin.Solid = True
            return pin
        pin = doc.addObject("Part::Cylinder", "Pin")
        pin.Radius, pin.Height = 2, 5
        return pin

    def makeCopy(self, doc, k, x):
        link = doc.addObject("App::Link", f"Copy{k}")
        link.LinkedObject = doc.Pin
        link.Placement.Base = V(x, 10, 10)
        return link

    def setInputs(self, doc, objs):
        if self.maker == "Part::MultiFuse":
            doc.Maker.Shapes = objs
        else:
            doc.Maker.Links = objs

    def inputs(self, doc):
        return [doc.Plate] + [doc.getObject(f"Copy{k}") for k in range(len(self.start))]

    def build(self, doc):
        self.at = dict(enumerate(self.start))
        m.box(doc, "Plate", (40, 20, 10))
        self.makePin(doc)
        for k, x in enumerate(self.start):
            self.makeCopy(doc, k, x)
        doc.addObject(self.maker, "Maker")
        self.setInputs(doc, self.inputs(doc))
        self.refer(doc)

    def refer(self, doc):
        body = m.body(doc)
        body.BaseFeature = doc.Maker
        doc.recompute()
        base = featureBase(body)
        for k in range(len(self.start)):
            point = datumPoint(body, base, self.names(base, self.rim(k))[0], f"Point{k}")
            self.ref(f"point_copy{k}", point, "AttachmentSupport", lambda k=k: self.rim(k), Attached())

    def removeCopy0(self, doc):
        self.setInputs(doc, [o for o in self.inputs(doc) if o.Name != "Copy0"])
        self.at[0] = None


# K8b's eight link cases (ops#503): their verdicts on integration 95538c7728 in a comment above


class K8bCase(Copies):
    abstract = True
    CLASSES = ("A", "D")
    ISSUE = "ops#503"
    FOUND_BY = "K8b attacker pass 2"


# point_copy0 wrong (tier 0, silent: copy 1 carries copy 0's index name), point_copy1 broken
class K8bLinkPinRemovedNeighbourMoved(K8bCase):
    """Link 0 is taken out of the fuse and link 1 moves to (10, 10): copy 0's point must break,
    copy 1's follows copy 1."""

    AXES = ("M5", "E1", "E4")

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


# point_copy0 wrong (tier 0, silent), point_copy1 broken ("pattern sibling")
class K8bLinkCopyRemoved(K8bCase):
    """Only link 0 is taken out of the fuse. Copy 0's point must break; copy 1's stays."""

    def edit(self, doc):
        self.removeCopy0(doc)


# point_copy0 broken (a null edit: the index names trade, both refused), point_copy1 broken
class K8bLinkCopiesReordered(K8bCase):
    """The fuse's inputs are only reordered: [plate, link 1, link 0]. Both points must stay."""

    AXES = ("M5", "E2")

    def edit(self, doc):
        self.setInputs(doc, [doc.Plate, doc.Copy1, doc.Copy0])


# point_copy0 wrong (tier 0, silent), point_copy1 broken ("pattern sibling")
class K8bLinkCopyRemovedCompound(K8bLinkCopyRemoved):
    """As K8bLinkCopyRemoved with a Part Compound in place of the MultiFuse."""

    maker = "Part::Compound"


# reopen: point_copy0 correct, point_copy1 correct; edit: point_copy0 wrong, point_copy1 broken
class K8bLinkCopyRemovedAfterReopen(Reopens, K8bLinkCopyRemoved):
    """K8bLinkCopyRemoved in a document saved and opened again first."""

    AXES = ("M5", "E1", "E9")
    steps = ("reopen", "edit")


# edit: point_copy0 wrong, point_copy1 broken; reopen: point_copy0 wrong, point_copy1 broken
class K8bLinkCopyRemovedThenReopened(Reopens, K8bLinkCopyRemoved):
    """K8bLinkCopyRemoved, then the document saved and opened again."""

    AXES = ("M5", "E1", "E9")
    steps = ("edit", "reopen")


# edit: point_copy0 wrong, point_copy1 broken; restore: point_copy0 broken, point_copy1 correct
class K8bLinkCopyRemovedRestored(K8bLinkCopyRemoved):
    """K8bLinkCopyRemoved, then link 0 put back into the fuse (an undo by hand): both points on
    their own copies again."""

    AXES = ("M5", "E1", "E9")
    steps = ("edit", "restore")

    def restore(self, doc):
        self.setInputs(doc, [doc.Plate, doc.Copy0, doc.Copy1])
        self.at[0] = 10


# change: point_copy0 wrong, point_copy1 broken; undo: point_copy0 correct, point_copy1 correct
class K8bLinkCopyRemovedUndone(K8bCase):
    """Link 0 taken out in one transaction with its recompute, then Document.undo()."""

    AXES = ("M5", "E1", "E9")
    steps = ("change", "undo")

    def build(self, doc):
        doc.UndoMode = 1
        super().build(doc)

    def change(self, doc):
        doc.openTransaction("change")
        self.removeCopy0(doc)
        doc.recompute()
        doc.commitTransaction()

    def undo(self, doc):
        doc.undo()
        self.at[0] = 10


# The prototype's designed variants (its verdicts on integration 95538c7728, Today column)


# point_copy0 correct, point_copy1 broken
class LinkCopyInsertedMiddle(Copies):
    """A third copy at x = 30 goes between copy 0 and copy 1 in the inputs."""

    AXES = ("M5", "E1", "E2")

    def edit(self, doc):
        self.makeCopy(doc, 2, 30)
        self.setInputs(doc, [doc.Plate, doc.Copy0, doc.Copy2, doc.Copy1])


# point_copy0 broken, point_copy1 broken
class LinkCopyInsertedFirst(Copies):
    """A third copy at x = 30 goes first in the inputs."""

    AXES = ("M5", "E1", "E2")

    def edit(self, doc):
        self.makeCopy(doc, 2, 30)
        self.setInputs(doc, [doc.Plate, doc.Copy2, doc.Copy0, doc.Copy1])


# point_copy0 wrong, point_copy1 broken, point_copy2 broken
class LinkCopyRemovedFirstOfThree(Copies):
    """Three copies at x = 8, 20, 32; copy 0 leaves the inputs."""

    start = (8, 20, 32)
    REFS = ("point_copy0", "point_copy1", "point_copy2")

    def edit(self, doc):
        self.removeCopy0(doc)


# point_copy0 correct, point_copy1 wrong, point_copy2 broken
class LinkCopyRemovedMiddleOfThree(Copies):
    """Three copies at x = 8, 20, 32; copy 1 leaves the inputs."""

    start = (8, 20, 32)
    REFS = ("point_copy0", "point_copy1", "point_copy2")

    def edit(self, doc):
        self.setInputs(doc, [doc.Plate, doc.Copy0, doc.Copy2])
        self.at[1] = None


# point_copy0 correct, point_copy1 correct, point_copy2 broken
class LinkCopyRemovedLastOfThree(Copies):
    """Three copies at x = 8, 20, 32; copy 2 leaves the inputs (a link array's count down)."""

    start = (8, 20, 32)
    REFS = ("point_copy0", "point_copy1", "point_copy2")

    def edit(self, doc):
        self.setInputs(doc, [doc.Plate, doc.Copy0, doc.Copy1])
        self.at[2] = None


# point_copy0 wrong, point_copy1 broken
class LinkCopyRemovedMappedPin(Copies):
    """As K8bLinkCopyRemoved, the pin an extrusion of a circle (a source with an element map)."""

    mappedPin = True

    def edit(self, doc):
        self.removeCopy0(doc)


# point_copy0 wrong, point_copy1 broken
class LinkCopyRemovedSwappedPlaces(Copies):
    """Copy 0 leaves the inputs and copy 1 moves onto copy 0's place, in a compound."""

    maker = "Part::Compound"
    AXES = ("M5", "E1", "E4")

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


# point_copy0 correct, point_copy1 broken, point_copy2 broken
class LinkCopyShiftedDown(Copies):
    """Three copies at x = 8, 20, 32; copy 2 leaves, copy 0 moves to 20 and copy 1 to 32 (a link
    array's first placement dropped). By key, copy 0's reference follows copy 0 to 20."""

    AXES = ("M5", "E1", "E4")
    start = (8, 20, 32)
    REFS = ("point_copy0", "point_copy1", "point_copy2")

    def edit(self, doc):
        self.setInputs(doc, [doc.Plate, doc.Copy0, doc.Copy1])
        doc.Copy0.Placement.Base = V(20, 10, 10)
        doc.Copy1.Placement.Base = V(32, 10, 10)
        self.at = {0: 20, 1: 32, 2: None}


# point_copy0 broken, point_copy1 broken
class LinkCopySwappedPlacements(Copies):
    """Copies 0 and 1 trade places (their placements swapped); both stay in the inputs. By key,
    each reference follows its copy (or breaks: a trade with names kept is refused)."""

    AXES = ("M5", "E4")

    def edit(self, doc):
        doc.Copy0.Placement.Base = V(20, 10, 10)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at = {0: 20, 1: 10}


class PinAndLinkCase(Copies):
    """The pin itself at (10, 10, 10) is copy 0, a link to it at (20, 10, 10) copy 1."""

    abstract = True

    def makeCopy(self, doc, k, x):
        if k == 0:
            doc.Pin.Placement.Base = V(x, 10, 10)
            return doc.Pin
        return super().makeCopy(doc, k, x)

    def inputs(self, doc):
        return [doc.Plate, doc.Pin, doc.Copy1]

    def removeCopy0(self, doc):
        self.setInputs(doc, [doc.Plate, doc.Copy1])
        self.at[0] = None


# point_copy0 wrong, point_copy1 broken
class LinkCopyPinAndLink(PinAndLinkCase):
    """The pin leaves the inputs; its link copy stays."""

    def edit(self, doc):
        self.removeCopy0(doc)


# Not run before: silent on integration by the review's trace (the names were identical)
class LinkCopyPinAndLinkNeighbourMoved(PinAndLinkCase):
    """The pin leaves the inputs and its link copy moves onto its place (Fable review finding 1):
    the original's point must break, never land on its copy."""

    AXES = ("M5", "E1", "E4")
    FOUND_BY = "ops#523 design review"

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


# point_copy0 correct, point_copy1 correct
class LinkCopyReplacedSamePlace(Copies):
    """Copy 0 leaves the inputs and a new copy (copy 2) takes its place at x = 10. The point may
    follow the place (the new copy, correct) or break (loud: decision 157's accepted cost);
    never another copy."""

    AXES = ("M5", "E1", "E5")

    def rim(self, k):
        if k == 0 and getattr(self, "replaced", False):
            return edge(center=(10, 10, 15), radius=2)
        return super().rim(k)

    def edit(self, doc):
        self.makeCopy(doc, 2, 10)
        self.setInputs(doc, [doc.Plate, doc.Copy2, doc.Copy1])
        self.replaced = True


# point_copy0 wrong, point_copy1 broken
class LinkCopyNested(Copies):
    """The copies sit in an inner Part Compound, the maker's input beside the box (a compound of
    a compound); copy 0 leaves the inner compound."""

    def inputs(self, doc):
        inner = doc.getObject("Inner") or doc.addObject("Part::Compound", "Inner")
        inner.Links = [doc.getObject(f"Copy{k}") for k in range(len(self.start))]
        return [doc.Plate, inner]

    def edit(self, doc):
        doc.Inner.Links = [doc.Copy1]
        self.at[0] = None


# point_copy0 wrong, point_copy1 broken
class LinkCopyLinkToLink(Copies):
    """Copy 1 is a link to copy 0 (a link to the pin); copy 0 leaves the inputs."""

    def makeCopy(self, doc, k, x):
        link = super().makeCopy(doc, k, x)
        if k == 1:
            link.LinkedObject = doc.Copy0
        return link

    def edit(self, doc):
        self.removeCopy0(doc)


# point_copy0 wrong, point_copy1 broken
class LinkCopiesToPart(Copies):
    """Two links to an App::Part holding the pin (a link to a group); link 0 leaves the
    compound."""

    maker = "Part::Compound"

    def makeCopy(self, doc, k, x):
        if not doc.getObject("Group"):
            group = doc.addObject("App::Part", "Group")
            group.addObject(doc.Pin)
        link = doc.addObject("App::Link", f"Copy{k}")
        link.LinkedObject = doc.Group
        link.Placement.Base = V(x, 10, 10)
        return link

    def edit(self, doc):
        self.removeCopy0(doc)


# point_copy0 correct, point_copy1 correct
class LinkCopySameLinkTwice(Copies):
    """The same link given twice (coincident copies) beside copy 1; one occurrence leaves. The
    key can't tell the occurrences apart (decision 150 (1)): they sit at one place."""

    maker = "Part::Compound"

    def inputs(self, doc):
        return [doc.Plate, doc.Copy0, doc.Copy0, doc.Copy1]

    def edit(self, doc):
        self.setInputs(doc, [doc.Plate, doc.Copy0, doc.Copy1])


class ScaleCase(Copies):
    """Copy 0 is a Part::Scale of the pin (factor 1, its names `X|CPY;1`) at x = 10, placed by its
    own Placement (a Scale takes the pin's shape without the pin's placement); copy 1 is a link to
    the pin at x = 20 (`X|CPY;L`)."""

    abstract = True
    AXES = ("M5", "E1", "E4")
    FOUND_BY = "ops#523 design review"

    def makeCopy(self, doc, k, x):
        if k == 0:
            scale = doc.addObject("Part::Scale", "Copy0")
            scale.Base = doc.Pin
            scale.Uniform = True
            scale.UniformScale = 1
            scale.Placement.Base = V(x, 10, 10)
            return scale
        return super().makeCopy(doc, k, x)


# Not run before: silent on integration by the review's trace
class LinkCopyScaleAndLinkNeighbourMoved(ScaleCase):
    """The Scale copy leaves the inputs and the link copy moves onto its place: the Scale's
    point must break, never land on the link's copy."""

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


# Not run before: silent on integration by the review's trace
class LinkCopyScaleBesideBaseMoved(ScaleCase):
    """The pin itself at x = 20 is copy 1, beside its Scale copy (copy 0) at x = 10. The Scale
    leaves the inputs and the pin moves onto its place: the Scale's point must break, never land
    on the pin."""

    def makeCopy(self, doc, k, x):
        if k == 0:
            return super().makeCopy(doc, k, x)
        doc.Pin.Placement.Base = V(x, 10, 10)
        return doc.Pin

    def inputs(self, doc):
        return [doc.Plate, doc.Copy0, doc.Pin]

    def edit(self, doc):
        self.setInputs(doc, [doc.Plate, doc.Pin])
        self.at[0] = None
        doc.Pin.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


# Link arrays: 3 elements at x = 8, 20, 32 in a Part Compound with the box


class ArrayCase(Copies):
    """A link array of the pin, 3 elements at x = 8, 20, 32, in a Part Compound with the box."""

    abstract = True
    maker = "Part::Compound"
    start = (8, 20, 32)
    REFS = ("point_copy0", "point_copy1", "point_copy2")
    showElement = False

    def build(self, doc):
        self.at = dict(enumerate(self.start))
        m.box(doc, "Plate", (40, 20, 10))
        self.makePin(doc)
        array = doc.addObject("App::Link", "Array")
        array.LinkedObject = doc.Pin
        array.ElementCount = len(self.start)
        array.ShowElement = self.showElement
        doc.recompute()  # the first recompute resets PlacementList
        self.place(array, self.start)
        doc.addObject(self.maker, "Maker")
        self.setInputs(doc, [doc.Plate, array])
        self.refer(doc)

    def place(self, array, xs):
        """The elements at x = xs: through PlacementList, or each element's own Placement when the
        array shows them as objects (PlacementList set later doesn't reach them)."""
        placements = [App.Placement(V(x, 10, 10), App.Rotation()) for x in xs]
        if array.ShowElement:
            for element, placement in zip(array.ElementList, placements):
                element.Placement = placement
        else:
            array.PlacementList = placements


# point_copy0 correct, point_copy1 correct, point_copy2 broken
class LinkArrayCountDown(ArrayCase):
    """ElementCount 3 -> 2: element 2 goes."""

    def edit(self, doc):
        doc.Array.ElementCount = 2
        self.at[2] = None


# point_copy0 wrong, point_copy1 broken, point_copy2 broken
class LinkArrayFirstHidden(ArrayCase):
    """Element 0 hidden (its visibility off): it leaves the array's shape."""

    def edit(self, doc):
        doc.Array.setElementVisible("0", False)
        self.at[0] = None


# point_copy0 correct, point_copy1 broken, point_copy2 broken
class LinkArrayFirstPlacementDropped(ArrayCase):
    """ElementCount 3 -> 2 with the first placement dropped from the list: elements 0 and 1 now
    at x = 20 and 32. By element number, element 0's reference goes to x = 20 (its new place)
    and element 2's breaks."""

    AXES = ("M5", "E1", "E4")

    def edit(self, doc):
        doc.Array.ElementCount = 2
        doc.recompute()
        self.place(doc.Array, self.start[1:])
        self.at = {0: 20, 1: 32, 2: None}


class LinkArrayShownFirstHidden(LinkArrayFirstHidden):
    """LinkArrayFirstHidden with the elements shown as objects (ShowElement)."""

    FOUND_BY = "ops#523 design review"
    showElement = True


class LinkArrayShowElementToggled(ArrayCase):
    """The array's ShowElement turned on, then off again (Fable review finding 2): nothing moves,
    every point stays."""

    AXES = ("M5", "E9")
    FOUND_BY = "ops#523 design review"
    steps = ("shown", "hidden")

    def shown(self, doc):
        doc.Array.ShowElement = True

    def hidden(self, doc):
        doc.Array.ShowElement = False


class LinkArrayCountDownUp(ArrayCase):
    """ElementCount 3 -> 1 -> 3 with the elements shown as objects (new LinkElements): every
    point is back on its element."""

    AXES = ("M5", "E1", "E9")
    FOUND_BY = "ops#523 design review"
    showElement = True
    steps = ("down", "up")

    def down(self, doc):
        doc.Array.ElementCount = 1
        self.at = {0: 8, 1: None, 2: None}

    def up(self, doc):
        doc.Array.ElementCount = 3
        doc.recompute()
        self.place(doc.Array, self.start)
        self.at = dict(enumerate(self.start))


# Cross-document links (the EXT section carries the link's ID)


class CrossDoc(Copies):
    abstract = True

    def makePin(self, doc):
        self.folder = os.path.realpath(tempfile.mkdtemp(prefix="NamingScenario"))
        source = App.newDocument("PinSource")
        self.source = source
        source.saveAs(os.path.join(self.folder, "PinSource.FCStd"))
        pin = source.addObject("Part::Cylinder", "Pin")
        pin.Radius, pin.Height = 2, 5
        source.recompute()
        source.save()
        doc.saveAs(os.path.join(self.folder, doc.Name + ".FCStd"))
        self.pin = pin
        return pin

    def makeCopy(self, doc, k, x):
        link = doc.addObject("App::Link", f"Copy{k}")
        link.LinkedObject = self.pin
        link.Placement.Base = V(x, 10, 10)
        return link

    def cleanup(self):
        super().cleanup()
        try:
            App.closeDocument(self.source.Name)
        except Exception:
            pass
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


# Twins inside copies (the A3 pre-push review's T1): a Pad of a disc r = 2.3 about (3.3, 3) up to
# a plate at z = 10 with a hole of four lobes about (3, 3) (PR 340 round 6's N9 model): the disc's
# far cap is four ordered twins on the plate, between the lobes. Two copies of the pad sit 100
# apart. Turning the hole 45 degrees (its symmetry) trades the twins' names; each copy's twins
# must stay a set of their own, so that the tie between the +45 and -45 readings breaks the
# reference, never picks one quietly.


def lobedHoleShell(z, turn=0):
    import math

    import Part

    points = []
    for k in range(60):
        t = 2 * math.pi * k / 60
        r = 2 + 0.8 * math.cos(4 * t)
        points.append(V(3 + r * math.cos(t), 3 + r * math.sin(t), z))
    curve = Part.BSplineCurve()
    curve.interpolate(points, PeriodicFlag=True)
    edge = curve.toShape()
    if turn:
        edge.rotate(V(3, 3, z), V(0, 0, 1), turn)
    outer = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
    plane = Part.Plane(V(0, 0, z), V(0, 0, 1))
    plate = Part.Face(plane, [Part.makePolygon(outer + outer[:1]), Part.Wire([edge])])
    fill = Part.Face(Part.Wire([edge]))
    return Part.Shell([plate.toNurbs().Faces[0], fill.toNurbs().Faces[0]])


class LobedCopies(Scenario):
    """Copy 0 at the origin and copy 1 at x = 100; datum points at the centres of copy 0's four
    twins (between the lobes at 45, 135, 225, 315 degrees); the hole turned 45 degrees."""

    abstract = True
    area = "link-copies"
    CLASSES = ("A", "D")
    ISSUE = "ops#523"
    FOUND_BY = "review pr523-r1"
    TIER = "F"
    AXES = ("M5", "E4")
    REFS = ("twin45", "twin135", "twin225", "twin315")
    maker = "Part::MultiFuse"
    turn = 0

    def twin(self, angle):
        import math

        a = math.radians(angle + self.turn)
        point = (3 + 1.7 * math.cos(a), 3 + 1.7 * math.sin(a), 10)
        found = face(contains=point)
        return OwnOrBroken(found) if self.turn else found

    def makePad(self, doc):
        body = m.body(doc)
        plate = doc.addObject("Part::Feature", "Plate")
        plate.Shape = lobedHoleShell(10)
        sketch = m.sketch(doc, "Profile", [m.circle(3.3, 3, 2.3)], body)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Type = "UpToShape"
        pad.UpToShape = (plate, ["Face1", "Face2"])
        pad.Refine = False
        doc.recompute()
        return body

    def copies(self, doc, body):
        raise NotImplementedError

    def build(self, doc):
        source = self.sourceDocument(doc)
        body = self.makePad(source)
        maker = doc.addObject(self.maker, "Maker")
        inputs = self.copies(doc, body)
        if self.maker == "Part::MultiFuse":
            maker.Shapes = inputs
        else:
            maker.Links = inputs
        target = m.body(doc)
        target.BaseFeature = doc.Maker
        doc.recompute()
        base = featureBase(target)
        for angle in (45, 135, 225, 315):
            point = target.newObject("PartDesign::Point", f"Twin{angle}")
            point.AttachmentSupport = [(base, self.names(base, self.twin(angle))[0])]
            point.MapMode = "CenterOfMass"
            self.ref(f"twin{angle}", point, "AttachmentSupport", lambda a=angle: self.twin(a), Attached())

    def sourceDocument(self, doc):
        return doc

    def edit(self, doc):
        source = self.sourceDocument(doc)
        source.Plate.Shape = lobedHoleShell(10, turn=45)
        source.recompute()
        self.turn = 45


class LinkCopyCrossDocLobesTurned45(LobedCopies):
    """Two links to the pad's body in another document (EXT copies)."""

    def sourceDocument(self, doc):
        if not hasattr(self, "source"):
            self.folder = os.path.realpath(tempfile.mkdtemp(prefix="NamingScenario"))
            self.source = App.newDocument("LobesSource")
            self.source.saveAs(os.path.join(self.folder, "LobesSource.FCStd"))
            doc.saveAs(os.path.join(self.folder, doc.Name + ".FCStd"))
        return self.source

    def copies(self, doc, body):
        body.Document.save()
        links = []
        for k, x in enumerate((0, 100)):
            link = doc.addObject("App::Link", f"Copy{k}")
            link.LinkedObject = body
            link.Placement.Base = V(x, 0, 0)
            links.append(link)
        return links

    def cleanup(self):
        super().cleanup()
        try:
            App.closeDocument(self.source.Name)
        except Exception:
            pass
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class LinkCopyLobesRemovedNeighbourMoved(LobedCopies):
    """Two links to the pad's body in one document; link 0 leaves the fuse and link 1 moves onto
    its place (the A3 pre-push review's T2): copy 0's twins are gone, so every point must break,
    never land on copy 1's twin there (an ordered name's renumbering is within one copy)."""

    AXES = ("M5", "E1", "E4")
    maker = "Part::Compound"  # a MultiFuse needs two inputs
    gone = False

    def twin(self, angle):
        return BROKEN if self.gone else super().twin(angle)

    def copies(self, doc, body):
        links = []
        for k, x in enumerate((0, 100)):
            link = doc.addObject("App::Link", f"Copy{k}")
            link.LinkedObject = body
            link.Placement.Base = V(x, 0, 0)
            links.append(link)
        return links

    def edit(self, doc):
        doc.Maker.Links = [doc.Copy1]
        doc.Copy1.Placement.Base = V(0, 0, 0)
        self.gone = True


class ScaleCopiesLobesTurned45(LobedCopies):
    """Two Part::Scale copies of the pad's body in one document (`CPY;1` copies)."""

    def copies(self, doc, body):
        scales = []
        for k, x in enumerate((0, 100)):
            scale = doc.addObject("Part::Scale", f"Copy{k}")
            scale.Base = body
            scale.Uniform = True
            scale.UniformScale = 1
            scale.Placement.Base = V(x, 0, 0)
            scales.append(scale)
        return scales


# point_copy0 broken, point_copy1 correct
class LinkCopyCrossDocRemoved(CrossDoc):
    """Two links to a pin in another document; link 0 leaves the fuse."""

    def edit(self, doc):
        self.removeCopy0(doc)


# point_copy0 wrong (tier 3 at 0), point_copy1 correct
class LinkCopyCrossDocRemovedNeighbourMoved(CrossDoc):
    """Two links to a pin in another document; link 0 leaves the fuse, link 1 moves onto its
    place."""

    AXES = ("M5", "E1", "E4")

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10
