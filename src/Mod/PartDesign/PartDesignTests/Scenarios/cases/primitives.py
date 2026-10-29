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

"""Corpus cases (ops#502, class C): references to results without history when their topology
changes.

A Part or PartDesign primitive, or a script shape, has no history: its elements are named by a
verified match against the result it replaces (MLN). Each case attaches sketches to elements of
one primitive (FlatFace on a face, NormalToEdge on an edge), edits a parameter that changes the
primitive's faces, and expects each sketch on the same element where it now is, or a break where
the element is gone. Ported from `work/502/probe_prims.py` and `work/502-review/probe_rev.py`
(`corpus/predicted/C.json`'s `probe_prims` and `probe_rev` rows); the counter's cases (undo,
save and reopen) are the design's C2 tests (`notes/naming-class-C.md` 5.2)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Reopens, Scenario, X, Z, edge, face
from PartDesignTests.Scenarios import models as m

BOTTOM = face("plane", normal=(0, 0, -1), through=(0, 0, 0))


def top(z):
    return face("plane", normal=Z, through=(0, 0, z))


def circle(z, r):
    return edge("circle", center=(0, 0, z), radius=r)


class PrimitiveEdit(Scenario):
    """A primitive TYPE made with PARAMS (in a Body, on a 30 x 30 x 2 block below it when BASE),
    sketches attached to the elements `before()` names, then EDIT; `after()` gives each
    reference's expectation after the edit, BROKEN where the element is gone."""

    abstract = True
    area = "primitives"
    CLASSES = ("C",)
    AXES = ("M4", "E1")
    ISSUE = "ops#502"
    FOUND_BY = "port"
    TYPE = None
    PARAMS = {}
    EDIT = {}
    BASE = False

    def before(self):
        raise NotImplementedError

    def after(self):
        return self.before()

    def build(self, doc):
        if self.TYPE.startswith("PartDesign::"):
            body = m.body(doc)
            if self.BASE:
                block = body.newObject("PartDesign::AdditiveBox", "Base")
                block.Length, block.Width, block.Height = 30, 30, 2
                block.AttachmentOffset = App.Placement(App.Vector(-15, -15, -2), App.Rotation())
            prim = body.newObject(self.TYPE, "Prim")
        else:
            prim = doc.addObject(self.TYPE, "Prim")
        for name, value in self.PARAMS.items():
            setattr(prim, name, value)
        doc.recompute()
        afterwards = self.after()
        for key, (predicate, mode) in self.before().items():
            sketch = doc.addObject("Sketcher::SketchObject", "On_" + key)
            sketch.AttachmentSupport = [(prim, self.names(prim, predicate)[0])]
            sketch.MapMode = mode
            self.ref(
                key,
                sketch,
                "AttachmentSupport",
                (
                    lambda b=predicate, a=afterwards[key][0]: b
                    if self.stepName is None
                    else a
                ),
                Attached(),
            )

    def edit(self, doc):
        prim = doc.getObject("Prim")
        for name, value in self.EDIT.items():
            setattr(prim, name, value)


class PrimPrism6to8(PrimitiveEdit):
    """A Part::Prism given two more sides: the top and bottom faces stay (rung 4)."""

    TIER = "G"
    TYPE = "Part::Prism"
    PARAMS = {"Polygon": 6, "Circumradius": 5, "Height": 10}
    EDIT = {"Polygon": 8}
    REFS = ("top", "bottom")

    def before(self):
        return {"top": (top(10), "FlatFace"), "bottom": (BOTTOM, "FlatFace")}


class PrimPrism6to8Taller(PrimitiveEdit):
    """The same and taller: the bottom stays; the top moved and changed its outline, so no rung
    holds it (a break, `C.json`'s prediction)."""

    TYPE = "Part::Prism"
    PARAMS = {"Polygon": 6, "Circumradius": 5, "Height": 10}
    EDIT = {"Polygon": 8, "Height": 14}
    REFS = ("top", "bottom")

    def before(self):
        return {"top": (top(10), "FlatFace"), "bottom": (BOTTOM, "FlatFace")}

    def after(self):
        return {"top": (top(14), "FlatFace"), "bottom": (BOTTOM, "FlatFace")}


S30, C30 = math.sin(math.radians(30)), math.cos(math.radians(30))


class PrimPrism6to8Side(PrimitiveEdit):
    """The same edit and a side face: no side of the octagonal prism faces that way."""

    TYPE = "Part::Prism"
    PARAMS = {"Polygon": 6, "Circumradius": 5, "Height": 10}
    EDIT = {"Polygon": 8}
    REFS = ("side",)

    def before(self):
        return {"side": (face("plane", normal=(C30, S30, 0), through=(3.75, 1.25 * 3**0.5, 5)), "FlatFace")}

    def after(self):
        return {"side": (BROKEN, "FlatFace")}


class PrimPrism6to5(PrimitiveEdit):
    """A Part::Prism given one side less: the top and bottom stay."""

    TYPE = "Part::Prism"
    PARAMS = {"Polygon": 6, "Circumradius": 5, "Height": 10}
    EDIT = {"Polygon": 5}
    REFS = ("top", "bottom")

    def before(self):
        return {"top": (top(10), "FlatFace"), "bottom": (BOTTOM, "FlatFace")}


class PrimCylinder360to270(PrimitiveEdit):
    """A Part::Cylinder made partial: its ends stay (rung 4) and its top rim, now an arc of the
    old circle (rung 5)."""

    TIER = "G"
    TYPE = "Part::Cylinder"
    PARAMS = {"Radius": 5, "Height": 10, "Angle": 360}
    EDIT = {"Angle": 270}
    REFS = ("top", "bottom", "rim")

    def before(self):
        return {
            "top": (top(10), "FlatFace"),
            "bottom": (BOTTOM, "FlatFace"),
            "rim": (circle(10, 5), "NormalToEdge"),
        }


class PrimCylinder270to360(PrimitiveEdit):
    """A partial Part::Cylinder made whole: its ends and rim stay; its cut face is gone."""

    TYPE = "Part::Cylinder"
    PARAMS = {"Radius": 5, "Height": 10, "Angle": 270}
    EDIT = {"Angle": 360}
    REFS = ("top", "bottom", "rim", "cut0")

    def before(self):
        return {
            "top": (top(10), "FlatFace"),
            "bottom": (BOTTOM, "FlatFace"),
            "rim": (circle(10, 5), "NormalToEdge"),
            "cut0": (face("plane", normal=(0, -1, 0), through=(0, 0, 0)), "FlatFace"),
        }

    def after(self):
        found = dict(self.before())
        found["cut0"] = (BROKEN, "FlatFace")
        return found


class PrimConeTopToApex(PrimitiveEdit):
    """A Part::Cone's top radius made 0: the bottom and its circle stay; the top face is gone."""

    TYPE = "Part::Cone"
    PARAMS = {"Radius1": 5, "Radius2": 3, "Height": 10}
    EDIT = {"Radius2": 0}
    REFS = ("bottom", "base", "top")

    def before(self):
        return {
            "bottom": (BOTTOM, "FlatFace"),
            "base": (circle(0, 5), "NormalToEdge"),
            "top": (top(10), "FlatFace"),
        }

    def after(self):
        found = dict(self.before())
        found["top"] = (BROKEN, "FlatFace")
        return found


class PrimConeApexToTop(PrimitiveEdit):
    """A pointed Part::Cone given a top radius: the bottom and its circle stay."""

    TYPE = "Part::Cone"
    PARAMS = {"Radius1": 5, "Radius2": 0, "Height": 10}
    EDIT = {"Radius2": 3}
    REFS = ("bottom", "base")

    def before(self):
        return {"bottom": (BOTTOM, "FlatFace"), "base": (circle(0, 5), "NormalToEdge")}


class PrimConeFlip(PrimitiveEdit):
    """A pointed Part::Cone whose apex changes end (radii 5 / 0 to 0 / 5): the bottom face and
    its circle are gone (the base is at the top now)."""

    TYPE = "Part::Cone"
    PARAMS = {"Radius1": 5, "Radius2": 0, "Height": 10}
    EDIT = {"Radius1": 0, "Radius2": 5}
    REFS = ("bottom", "base")

    def before(self):
        return {"bottom": (BOTTOM, "FlatFace"), "base": (circle(0, 5), "NormalToEdge")}

    def after(self):
        return {"bottom": (BROKEN, "FlatFace"), "base": (BROKEN, "NormalToEdge")}


class PrimSphereCapFlip(PrimitiveEdit):
    """A Part::Sphere cut at the top (angles -90..45) cut at the bottom instead (-45..90): the
    top cap is gone."""

    TYPE = "Part::Sphere"
    PARAMS = {"Radius": 5, "Angle1": -90, "Angle2": 45}
    EDIT = {"Angle1": -45, "Angle2": 90}
    REFS = ("cap",)

    def before(self):
        return {"cap": (top(5 * math.sin(math.radians(45))), "FlatFace")}

    def after(self):
        return {"cap": (BROKEN, "FlatFace")}


class PrimBoxTaller(PrimitiveEdit):
    """A Part::Box made taller (the control): every face stays (rung 6)."""

    TYPE = "Part::Box"
    PARAMS = {"Length": 10, "Width": 8, "Height": 6}
    EDIT = {"Height": 10}
    REFS = ("top", "bottom", "xplus")

    def before(self):
        return {
            "top": (top(6), "FlatFace"),
            "bottom": (BOTTOM, "FlatFace"),
            "xplus": (face("plane", normal=X, through=(10, 0, 0)), "FlatFace"),
        }

    def after(self):
        found = dict(self.before())
        found["top"] = (top(10), "FlatFace")
        return found


class PDCylinder360to270(PrimitiveEdit):
    """A PartDesign AdditiveCylinder made partial: its top and rim stay (the tool's ids)."""

    TYPE = "PartDesign::AdditiveCylinder"
    PARAMS = {"Radius": 5, "Height": 10, "Angle": 360}
    EDIT = {"Angle": 270}
    REFS = ("top", "rim")

    def before(self):
        return {"top": (top(10), "FlatFace"), "rim": (circle(10, 5), "NormalToEdge")}


class PDCylinder360to270OnBase(PDCylinder360to270):
    """The same on a block (the tool fused with a base)."""

    TIER = "G"
    BASE = True


class PDPrism6to8(PrimitiveEdit):
    """A PartDesign AdditivePrism given two more sides: its top stays."""

    TYPE = "PartDesign::AdditivePrism"
    PARAMS = {"Polygon": 6, "Circumradius": 5, "Height": 10}
    EDIT = {"Polygon": 8}
    REFS = ("top",)

    def before(self):
        return {"top": (top(10), "FlatFace")}


class PDPrism6to8OnBase(PDPrism6to8):
    """The same on a block."""

    BASE = True


class PDConeFlip(PrimitiveEdit):
    """A pointed PartDesign AdditiveCone whose apex changes end: its bottom face is gone."""

    TYPE = "PartDesign::AdditiveCone"
    PARAMS = {"Radius1": 5, "Radius2": 0, "Height": 10}
    EDIT = {"Radius1": 0, "Radius2": 5}
    REFS = ("bottom",)

    def before(self):
        return {"bottom": (BOTTOM, "FlatFace")}

    def after(self):
        return {"bottom": (BROKEN, "FlatFace")}


class PrimPrismUndone(PrimitiveEdit):
    """A Part::Prism given two more sides, the edit undone, then made taller: its top stays
    through each step (the ids of the undone step are not given again)."""

    TYPE = "Part::Prism"
    PARAMS = {"Polygon": 6, "Circumradius": 5, "Height": 10}
    REFS = ("top", "bottom")
    steps = ("more", "back", "taller")
    height = 10

    def before(self):
        return {"top": (top(10), "FlatFace"), "bottom": (BOTTOM, "FlatFace")}

    def build(self, doc):
        doc.UndoMode = 1
        super().build(doc)
        self.ref("top", doc.getObject("On_top"), "AttachmentSupport", lambda: top(self.height), Attached())

    def edited(self, doc, **values):
        doc.openTransaction(self.stepName)
        prim = doc.getObject("Prim")
        for name, value in values.items():
            setattr(prim, name, value)
        doc.recompute()
        doc.commitTransaction()

    def more(self, doc):
        self.edited(doc, Polygon=8)

    def back(self, doc):
        doc.undo()

    def taller(self, doc):
        self.height = 14
        self.edited(doc, Height=14)


class PrimPrismReopened(Reopens, PrimitiveEdit):
    """A Part::Prism saved and opened again, then given two more sides: its top and bottom stay
    (the ids and the counter are saved with the shape)."""

    TYPE = "Part::Prism"
    PARAMS = {"Polygon": 6, "Circumradius": 5, "Height": 10}
    REFS = ("top", "bottom")
    steps = ("reopen", "more")

    def before(self):
        return {"top": (top(10), "FlatFace"), "bottom": (BOTTOM, "FlatFace")}

    def more(self, doc):
        self.doc.getObject("Prim").Polygon = 8


def row(spacing, count=3):
    """A script compound: `count` 10 mm cubes along x, `spacing` apart."""
    return Part.makeCompound(
        [Part.makeBox(10, 10, 10, App.Vector(i * spacing, 0, 0)) for i in range(count)]
    )


class ScriptRowSlid(Scenario):
    """A script compound of three cubes, 20 apart, set as a Part::Feature's shape; sketches on
    each cube's top and on the third's +x side; the spacing becomes 25. The first cube stays; the
    third moved by its own width, onto the place of its own far side, and the design's direction
    and side terms refuse that hand-over (`C.json`: loud, a cost the design accepts)."""

    area = "primitives"
    CLASSES = ("C",)
    AXES = ("M4", "E4")
    ISSUE = "ops#502"
    FOUND_BY = "port"
    REFS = ("top1", "top2", "top3", "side3")
    spacing = 20

    def build(self, doc):
        row_ = m.feature(doc, "Row", row(20))
        doc.recompute()

        def tops(k):
            return lambda: face("plane", normal=Z, contains=(k * self.spacing + 5, 5, 10))

        def side():
            return face("plane", normal=X, through=(2 * self.spacing + 10, 0, 0))

        for key, predicate, mode in (
            ("top1", tops(0), "FlatFace"),
            ("top2", tops(1), "FlatFace"),
            ("top3", tops(2), "FlatFace"),
            ("side3", side, "FlatFace"),
        ):
            sketch = doc.addObject("Sketcher::SketchObject", "On_" + key)
            sketch.AttachmentSupport = [(row_, self.names(row_, predicate())[0])]
            sketch.MapMode = mode
            self.ref(key, sketch, "AttachmentSupport", predicate, Attached())

    def edit(self, doc):
        self.spacing = 25
        doc.getObject("Row").Shape = row(25)
