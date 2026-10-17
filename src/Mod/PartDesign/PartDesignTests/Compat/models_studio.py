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

"""The corpus's models of B+ Stage 1's objects (FreeCAD-CH ops#325, notes/bplus-stage1-design.md;
ops#323 PR B2, notes/beta-compatibility.md 3.6, "feature PRs before the beta"): a studio with a
pick across its parts (MapOrigin) and a New part, sibling Remove/Intersect features, an accepted
Merge, a Split with its new half. Built with the module functions the panels call
(`PartDesign.newPartFrom`, `makeSiblings`, `makeMerge`, `split`). Same conventions as
`models.py`."""

import math

import FreeCAD as App
import PartDesign

from PartDesignTests.Compat.models import TOP, V, attachedSketch, faceWhere, plane, planeFacing
from PartDesignTests.Compat.models_partdesign import block, newBody
from PartDesignTests.Scenarios import models as m


def at(z):
    return App.Placement(V(0, 0, z), App.Rotation())


def StudioNewPart(make):
    """A studio (an App::Part holding Bodies at one origin), a pick across its parts, and a New
    part.

    Studio holds Enclosure and Upper. Enclosure: Base, a 40 x 40 x 10 block (0..40); Lid, a
    square 0..30 on Base's top face (MapOrigin "Body": the sketch's origin is the Body's,
    projected onto the face) padded 5, then made a New part (`newPartFrom`): a new Body holding
    LidSketch and Lid, Enclosure back to Base. Upper: a sketch on Base's top face (a feature of
    the other part, no binder) with a square 32..38, padded 3."""
    doc = make("StudioNewPart")
    studio = doc.addObject("App::Part", "Studio")
    enclosure = newBody(doc, "Enclosure")
    upper = newBody(doc, "Upper")
    studio.addObject(enclosure)
    studio.addObject(upper)
    base = block(enclosure, 0, 0, 40, 40, 10, "Base")
    doc.recompute()
    top = faceWhere(base.Shape, planeFacing(TOP, V(0, 0, 10)))
    lidSketch = attachedSketch(enclosure, "LidSketch", (base, top), m.rectangle(0, 0, 30, 30))
    if lidSketch.MapOrigin != "Body":
        raise AssertionError(f"LidSketch's MapOrigin is {lidSketch.MapOrigin}")
    lid = m.pad(enclosure, lidSketch, 5, "Lid")
    doc.recompute()
    part = PartDesign.newPartFrom(lid)
    doc.recompute()
    if list(part.Group) != [lidSketch, lid] or enclosure.Tip != base:
        raise AssertionError(f"New part: {[o.Name for o in part.Group]}, {enclosure.Tip.Name}")
    peg = attachedSketch(upper, "PegSketch", (base, top), m.rectangle(32, 32, 38, 38))
    m.pad(upper, peg, 3, "Peg")
    doc.recompute()
    return {"volumes": {"Base": 16000, "Lid": 4500, "Peg": 108}}


def SiblingCuts(make):
    """Sibling Remove and Intersect features (one feature per part, the siblings following the
    first by expression).

    Enclosure: a 40 x 40 x 10 block (0..40). Lid: a 40 x 40 plate, 5 thick, on top (z 10..15).
    Holes: four circles, radius 2, at (5, 5), (35, 5), (5, 35), (35, 35), from a sketch at
    z 15 in Lid, pocketed through all in Lid, with a sibling in Enclosure ("Remove from" both).
    Trim: a square 10..30 from a sketch at z 15 in Lid, pocketed through all as Common
    ("Intersect with") in Lid, with a sibling in Enclosure: Lid keeps 20 x 20 x 5, Enclosure
    20 x 20 x 10 (the holes fall outside)."""
    doc = make("SiblingCuts")
    enclosure = newBody(doc, "Enclosure")
    block(enclosure, 0, 0, 40, 40, 10, "Base")
    lid = newBody(doc, "Lid")
    plate = block(lid, 0, 0, 40, 40, 5, "Plate")
    plate.Profile[0].AttachmentOffset = at(10)
    doc.recompute()
    holeSketch = attachedSketch(
        lid,
        "HoleSketch",
        plane(lid, "XY_Plane"),
        [m.circle(x, y, 2) for x, y in ((5, 5), (35, 5), (5, 35), (35, 35))],
    )
    holeSketch.AttachmentOffset = at(15)
    holes = m.pocketThroughAll(lid, holeSketch, "Holes")
    doc.recompute()
    (holesSibling,) = PartDesign.makeSiblings(holes, [enclosure])
    doc.recompute()
    trimSketch = attachedSketch(
        lid, "TrimSketch", plane(lid, "XY_Plane"), m.rectangle(10, 10, 30, 30)
    )
    trimSketch.AttachmentOffset = at(15)
    trim = m.pocketThroughAll(lid, trimSketch, "Trim")
    trim.Operation = "Common"
    doc.recompute()
    (trimSibling,) = PartDesign.makeSiblings(trim, [enclosure])
    doc.recompute()
    for sibling, primary in ((holesSibling, holes), (trimSibling, trim)):
        if sibling.SiblingOf != primary or "Warning" in sibling.State:
            raise AssertionError(f"{sibling.Name}: {sibling.State} {sibling.getStatusString()}")
    holeArea = 4 * math.pi * 4
    return {
        "volumes": {
            "Holes": 8000 - holeArea * 5,
            holesSibling.Name: 16000 - holeArea * 10,
            "Trim": 2000,
            trimSibling.Name: 4000,
        }
    }


def MergeAccepted(make):
    """An accepted Merge (decision 59): Panel merged into Bracket, the warning accepted.

    Bracket: a 40 x 40 x 10 block (0..40). Panel: a 40 x 30 x 10 block (x 20..60, y 0..30).
    `makeMerge(Bracket, [Panel])`: a PartDesign Boolean Fuse in Bracket whose tool is Panel's
    last feature; Panel hidden and merged into it; `MergeAccepted` set, so no warning: Bracket
    16000 + 12000 - 6000."""
    doc = make("MergeAccepted")
    bracket = newBody(doc, "Bracket")
    block(bracket, 0, 0, 40, 40, 10, "BracketPad")
    panel = newBody(doc, "Panel")
    panelPad = block(panel, 20, 0, 60, 30, 10, "PanelPad")
    doc.recompute()
    merge = PartDesign.makeMerge(bracket, [panel])
    doc.recompute()
    merge.MergeAccepted = True
    doc.recompute()
    if list(merge.Group) != [panelPad] or panel.MergedInto != merge or "Warning" in merge.State:
        raise AssertionError(f"Merge: {merge.State} {merge.getStatusString()}")
    return {"volumes": {merge.Name: 22000}}


def SplitHalves(make):
    """A Split with its new half (2.7).

    Shroud: an additive box 20 x 10 x 8 less a subtractive box 18 x 8 x 7 at (1, 1, 1) (an open
    tray, 592); a datum plane at y 3, normal +Y; `split(Shroud, plane, "Front")`: Shroud keeps
    y 3..10 (a Split at its end, 364), a new Body keeps y 0..3 (its first feature a Split whose
    partner is Shroud's, 228)."""
    doc = make("SplitHalves")
    body = newBody(doc, "Shroud")
    outer = body.newObject("PartDesign::AdditiveBox", "Outer")
    outer.Length, outer.Width, outer.Height = 20, 10, 8
    inner = body.newObject("PartDesign::SubtractiveBox", "Inner")
    inner.Length, inner.Width, inner.Height = 18, 8, 7
    inner.Placement = App.Placement(V(1, 1, 1), App.Rotation())
    cut = body.newObject("PartDesign::Plane", "SplitPlane")
    cut.MapMode = "Deactivated"
    cut.Placement = App.Placement(V(0, 3, 0), App.Rotation(V(0, 0, 1), V(0, 1, 0)))
    doc.recompute()
    part = PartDesign.split(body, cut, "Front")
    doc.recompute()
    original, half = body.Tip, part.Tip
    if half.Partner != original or not half.NewHalf or original.NewHalf:
        raise AssertionError(f"Split: {original.Name}, {half.Name}")
    return {"volumes": {"Inner": 592, original.Name: 364, half.Name: 228}}


MODELS = [StudioNewPart, SiblingCuts, MergeAccepted, SplitHalves]
