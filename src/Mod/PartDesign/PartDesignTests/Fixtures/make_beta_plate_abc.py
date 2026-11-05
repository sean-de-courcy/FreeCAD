# SPDX-License-Identifier: LGPL-2.1-or-later
"""Makes Fixtures/BetaPlateABC.FCStd (FreeCAD-CH ops#502, decision 260): a script compound of three
slabs as the beta saved it, from review pr399-r3g's `mkfx.py` (Sonnet's G1).

Run once with a build of the beta's naming (ForkNamingRevision 15, before C2), never with a later one:
BETA_PLATE_OUT=<output.FCStd> FreeCADCmd make_beta_plate_abc.py. Such a build gives a script's compound
one-section IDX names, and a Cut of it names its faces from them.

Designed geometry, all in mm:
- Plate: a Part::Feature set by script to a compound of three 40 x 30 x 5 slabs, A at x = 0, B at
  x = 60 and C at x = 120.
- Notch: a Part::Box 6 x 6 x 10 at (-1, -1, -2), notching A's corner; Cut: Plate less Notch.
- DatumPlateA, DatumPlateB, DatumPlateC (PartDesign::Plane) on the plate's slab tops (z = 5, centres at
  x = 20, 80, 140); DatumCutA, DatumCutB, DatumCutC on the cut's (A's is the notched one).
"""

import os

import FreeCAD as App
import Part

V = App.Vector


def topFace(shape, cx):
    """The name of the planar top face (z = 5, normal +Z) of `shape` over x = `cx`."""
    for i, face in enumerate(shape.Faces, 1):
        if face.Surface.TypeId != "Part::GeomPlane":
            continue
        n = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
        box = face.BoundBox
        if abs(face.CenterOfMass.z - 5) < 1e-6 and n.getAngle(V(0, 0, 1)) < 1e-6 and box.XMin <= cx <= box.XMax:
            return "Face%d" % i
    raise RuntimeError("no top over x = %s" % cx)


def datum(doc, name, support, element):
    plane = doc.addObject("PartDesign::Plane", name)
    plane.AttachmentSupport = [(support, element)]
    plane.MapMode = "FlatFace"
    return plane


def make(path):
    doc = App.newDocument("BetaPlateABC")
    plate = doc.addObject("Part::Feature", "Plate")
    plate.Shape = Part.makeCompound([Part.makeBox(40, 30, 5, V(x, 0, 0)) for x in (0, 60, 120)])
    notch = doc.addObject("Part::Box", "Notch")
    notch.Length = notch.Width = 6
    notch.Height = 10
    notch.Placement.Base = V(-1, -1, -2)
    cut = doc.addObject("Part::Cut", "Cut")
    cut.Base = plate
    cut.Tool = notch
    doc.recompute()
    for tag, cx in (("A", 20), ("B", 80), ("C", 140)):
        datum(doc, "DatumPlate" + tag, plate, topFace(plate.Shape, cx))
        datum(doc, "DatumCut" + tag, cut, topFace(cut.Shape, cx))
    doc.recompute()
    for obj in doc.Objects:
        if not obj.isValid():
            raise RuntimeError("%s is invalid" % obj.Name)
    if not any("IDX" in name for name in plate.Shape.ElementMap):
        raise RuntimeError("the plate has no IDX names: not a build of the beta's naming")
    doc.saveAs(path)
    for obj in (plate, cut):
        print("BETA", obj.Name, "map", obj.Shape.ElementMapSize)
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Plane":
            print("BETA", obj.Name, obj.AttachmentSupport, obj.Placement.Base)
    App.closeDocument(doc.Name)


make(os.environ["BETA_PLATE_OUT"])
