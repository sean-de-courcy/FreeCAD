# SPDX-License-Identifier: LGPL-2.1-or-later
"""Makes Fixtures/BetaMapless.FCStd (FreeCAD-CH ops#502): history-less results as the beta saved them.

Run once with a build of the beta's naming (ForkNamingRevision 15, before C2), never with a later one:
BETA_MAPLESS_OUT=<output.FCStd> FreeCADCmd make_beta_mapless.py. Such a build names a history-less result by index:
a Part::Box and a boolean of map-less shapes have no element map (their consumers hold bare indices,
`Face6`), a script's compound has one-section IDX names, and no shape has an `ElementIdNext` counter.
TestBetaMapless opens the file on a later build and checks its port (the C2 implementation note,
"The port for beta files").

Designed geometry, all in mm:
- Box: Part::Box 10 x 20 x 30. DatumTop (PartDesign::Plane) on its top face Face6 (z = 30);
  BoxFillet (Part::Fillet, radius 2) on its vertical edge at x = 10, y = 20.
- Plate: a Part::Feature set by script to a compound of two 40 x 30 x 5 slabs, A at x = 0 and B at
  x = 60. DatumPlateB on B's top face (z = 5, centre x = 80).
- Cutout: a Part::Feature set by script to a 30 x 30 x 10 block less a radius-5 hole at (15, 15).
  DatumCutTop on its top face (z = 10).
"""

import os

import FreeCAD as App
import Part


def faceAt(shape, centre, normal):
    """The name of the planar face of `shape` whose centre of mass is `centre` and whose normal is `normal`."""
    for i, face in enumerate(shape.Faces, 1):
        if face.Surface.TypeId != "Part::GeomPlane":
            continue
        n = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
        if face.CenterOfMass.distanceToPoint(centre) < 1e-6 and n.getAngle(normal) < 1e-6:
            return "Face%d" % i
    raise RuntimeError("no face at %s" % centre)


def edgeAt(shape, a, b):
    for i, edge in enumerate(shape.Edges, 1):
        ends = {tuple(round(c, 6) for c in v.Point) for v in edge.Vertexes}
        if ends == {tuple(a), tuple(b)}:
            return "Edge%d" % i
    raise RuntimeError("no edge %s-%s" % (a, b))


def datum(doc, name, support, element):
    plane = doc.addObject("PartDesign::Plane", name)
    plane.AttachmentSupport = [(support, element)]
    plane.MapMode = "FlatFace"
    return plane


def slabs(xb):
    return Part.makeCompound([Part.makeBox(40, 30, 5), Part.makeBox(40, 30, 5, App.Vector(xb, 0, 0))])


def make(path):
    doc = App.newDocument("BetaMapless")
    up = App.Vector(0, 0, 1)
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 10, 20, 30
    doc.recompute()
    datum(doc, "DatumTop", box, faceAt(box.Shape, App.Vector(5, 10, 30), up))
    fillet = doc.addObject("Part::Fillet", "BoxFillet")
    fillet.Base = box
    fillet.Edges = [(int(edgeAt(box.Shape, (10, 20, 0), (10, 20, 30))[4:]), 2.0, 2.0)]

    plate = doc.addObject("Part::Feature", "Plate")
    plate.Shape = slabs(60)
    datum(doc, "DatumPlateB", plate, faceAt(plate.Shape, App.Vector(80, 15, 5), up))

    cut = doc.addObject("Part::Feature", "Cutout")
    cut.Shape = Part.makeBox(30, 30, 10).cut(Part.makeCylinder(5, 10, App.Vector(15, 15, 0)))
    faces = cut.Shape.Faces
    top = [i for i, f in enumerate(faces, 1) if abs(f.CenterOfMass.z - 10) < 1e-6 and f.Surface.TypeId == "Part::GeomPlane"]
    datum(doc, "DatumCutTop", cut, "Face%d" % top[0])
    doc.recompute()
    for obj in doc.Objects:
        if not obj.isValid():
            raise RuntimeError("%s is invalid" % obj.Name)
    doc.saveAs(path)
    for obj in (box, plate, cut):
        print("BETA", obj.Name, "map", obj.Shape.ElementMapSize)
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Plane":
            print("BETA", obj.Name, obj.AttachmentSupport, obj.Placement.Base)
    print("BETA fillet", fillet.Edges, fillet.Shape.isValid(), fillet.Shape.Volume)
    App.closeDocument(doc.Name)


make(os.environ["BETA_MAPLESS_OUT"])
