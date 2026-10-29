# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prA1b-r1 (ops#522): a far piece whose fingerprint has no saved up-to faces when its
profile moves by placement. `_updateElementFingerprints()` keeps the saved up-to faces only when
the old fingerprint has some; a Pad's Placement is set before its shape is made again
(positionByPrevious()), and the refresh in between measures the gone piece's point, carried by
the new placement, over the next plate. A fingerprint without up-to faces then takes those.

Two ways to a far piece's fingerprint without up-to faces:
- `Stacked*`: the line along the sweep through the strip's point meets three up-to faces (the
  plate under it and two more over that plate, which the Pad doesn't reach): toString() writes
  version 5 (more than MaxUpToFaces). Once moved, the point lies over one plate only.
- `Unsaved*`: the file holds version 5 fingerprints (a file saved before version 6, emulated by
  rewriting the saved `fp=`), opened and edited with no recompute in between.

Two plates at z = 10 meeting at a seam x = 0 (x -10..0 and 0..10, y -12..12, B-spline faces); the
rib x -0.1..0.3, y -10..10 in an unattached sketch; a strip on the first plate (centre
(-0.05, 0)) and a piece on the second. The sketch's Placement moves it by 0.12 along x, wholly
onto the second plate: the strip is gone and its datum must break."""

import os
import re
import shutil
import tempfile
import zipfile

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


def flatPlate(outline, z=10):
    corners = [V(x, y, z) for x, y in outline]
    return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]


def downgrade(text):
    """A version 6 fingerprint as a build before it wrote it: version 5, without the up-to faces
    (and without the `_` for no inside point)."""
    fields = text.split("|")
    if fields[0] != "6" or len(fields) != 13:
        return text
    fields = fields[:12]
    if fields[11] == "_":
        fields = fields[:11]
    return "5|" + "|".join(fields[1:])


class SeamRibPlaced(Scenario):
    abstract = True
    area = "uptoface"
    CLASSES = ("A",)
    AXES = ("M2", "E5")
    ISSUE = "ops#522"
    FOUND_BY = "review prA1b-r1"
    TIER = "F"
    REFS = ("strip", "piece")
    move = 0.12
    moved = False
    stacked = False
    stackHeights = (14, 18)
    mover = "placement"

    def plates(self):
        faces = [
            flatPlate(((-10, -12), (0, -12), (0, 12), (-10, 12))),
            flatPlate(((0, -12), (10, -12), (10, 12), (0, 12))),
        ]
        if self.stacked:
            # two more over the first plate, beyond it: the Pad stops at the first plate
            for z in self.stackHeights:
                faces.append(flatPlate(((-10, -12), (-0.01, -12), (-0.01, 12), (-10, 12)), z))
        return faces

    def build(self, doc):
        body = m.body(doc)
        faces = self.plates()
        plate = m.feature(doc, "Plate", Part.Shell(faces) if not self.stacked else Part.Compound(faces))
        profile = m.sketch(doc, "Profile", m.rectangle(-0.1, -10, 0.3, 10), body)
        if self.mover == "offset":
            profile.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), "")]
            profile.MapMode = "FlatFace"
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Type = "UpToShape"
        pad.UpToShape = (plate, ["Face%d" % i for i in range(1, len(faces) + 1)])
        pad.Refine = False
        doc.recompute()
        for name in self.REFS:
            expect = getattr(self, name)
            point = body.newObject("PartDesign::Point", name.capitalize())
            point.AttachmentSupport = [(pad, self.names(pad, expect())[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect, Attached())
        body.Tip = pad

    def shift(self):
        return self.move if self.moved else 0.0

    def strip(self):
        x0 = -0.1 + self.shift()
        return BROKEN if x0 >= 0 else face(contains=(x0 / 2, 0, 10))

    def piece(self):
        x0 = max(0, -0.1 + self.shift())
        x1 = 0.3 + self.shift()
        return face(contains=((x0 + x1) / 2, 0, 10))

    def moveProfile(self, doc):
        self.moved = True
        shift = App.Placement(V(self.move, 0, 0), App.Rotation())
        if self.mover == "offset":
            doc.Profile.AttachmentOffset = shift
        else:
            doc.Profile.Placement = shift

    def edit(self, doc):
        self.moveProfile(doc)


class SeamRibPlacementStripGone(SeamRibPlaced):
    """The control: two plates, the sketch's Placement moved by 0.12."""


class StackedSeamRibPlacementStripGone(SeamRibPlaced):
    """Two more plates over the first (z = 14, 18): the strip's point meets three up-to faces."""

    stacked = True


class StackedSeamRibOffsetStripGone(SeamRibPlaced):
    """As StackedSeamRibPlacementStripGone, the sketch on XY_Plane moved by its AttachmentOffset."""

    stacked = True
    mover = "offset"


class StackedBelowSeamRibPlacementStripGone(SeamRibPlaced):
    """The two more plates under the sketch (z = -4, -8), behind the Pad."""

    stacked = True
    stackHeights = (-4, -8)


class UnsavedSeamRibPlacementStripGone(SeamRibPlaced):
    """Saved, its fingerprints rewritten as version 5, reopened, and the sketch's Placement moved
    before any recompute."""

    def edit(self, doc):
        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        path = os.path.join(self.folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        old = path + ".v6"
        shutil.move(path, old)
        with zipfile.ZipFile(old) as src, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "Document.xml":
                    text = data.decode("utf-8")
                    text = re.sub(r'fp="([^"]*)"', lambda mt: 'fp="%s"' % downgrade(mt.group(1)), text)
                    self.downgraded = text.count('fp="5|')
                    data = text.encode("utf-8")
                dst.writestr(item, data)
        self.doc = self.openDocument(path)
        self.moveProfile(self.doc)

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)
