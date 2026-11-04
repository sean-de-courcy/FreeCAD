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


"""Corpus cases (ops#502, class C): a script compound whose members change shape while they move
(P1b, decision 260; the class C ruling `work/s3339/c2-platebthin-ruling.md`, from review
pr399-r3g's `PlateBThinToCPlace`).

The model: `Plate`, a script's compound of three 40 x 30 x 5 slabs A, B and C at x = 0, 60 and
120, as a fresh shape (no element map, so this build names it by match); `Cut`, the plate less a
box notching A's corner; a sketch on each slab's top in the plate (`pA`, `pB`, `pC`) and in the cut
(`cA`, `cB`, `cC`). The script sets the plate again with the slabs listed in `slabs` (x, height).

"B thinned and moved onto C's place, C moved on" and "C thinned in place, B deleted, a slab
appended" make the same compound in the same order, so no rule over the shapes can be right for
both: P1b retires the changed slab matched at another member's place when the old member has a
whole twin standing free, and the references to both slabs break (loud). Without the free twin
the place reading stands, as for every changed piece (the uncorroborated order/place ambiguity,
listed in the ruling's 5: right under the place reading, which these cases expect)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


class _Plate(Scenario):
    abstract = True
    area = "history-less results"
    CLASSES = ("C",)
    ISSUE = "ops#502"
    FOUND_BY = "review pr399-r3g"
    TIER = "F"
    AXES = ("M2", "X4")
    REFS = ("pA", "pB", "pC", "cA", "cB", "cC")
    slabs = ((0, 5), (60, 5), (120, 5))  # the edit's compound: (x, height) per slab, in order
    where = {"A": (0, 5), "B": (60, 5), "C": (120, 5)}  # after the edit: the slab's (x, height); None: broken

    def plate(self, slabs):
        shape = Part.Shape()
        compound = Part.makeCompound([Part.makeBox(40, 30, h, V(x, 0, 0)) for x, h in slabs])
        shape.importBrepFromString(compound.exportBrepToString())
        return shape

    def top(self, tag):
        if self.stepName is None:
            x, h = {"A": (0, 5), "B": (60, 5), "C": (120, 5)}[tag]
        elif self.where[tag] is None:
            return BROKEN
        else:
            x, h = self.where[tag]
        return face("plane", normal=Z, contains=V(x + 20, 15, h))

    def build(self, doc):
        self.target = m.feature(doc, "Plate", self.plate(((0, 5), (60, 5), (120, 5))))
        notch = m.box(doc, "Notch", (6, 6, 10), at=(-1, -1, -2))
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = self.target, notch
        doc.recompute()
        for tag in "ABC":
            for prefix, owner in (("p", self.target), ("c", cut)):
                expect = lambda tag=tag: self.top(tag)
                sketch = doc.addObject("Sketcher::SketchObject", "On_" + prefix + tag)
                sketch.AttachmentSupport = [(owner, self.names(owner, expect())[0])]
                sketch.MapMode = "FlatFace"
                self.ref(prefix + tag, sketch, "AttachmentSupport", expect, Attached())

    def edit(self, doc):
        self.target.Shape = self.plate(self.slabs)


class PlateBThinToCPlace(_Plate):
    """The find (review pr399-r3g): B 3 high moves onto C's place (120), C moves to 300. The thin
    slab is matched to C by place, while C's whole twin stands free at 300 and B is unmatched: P1b
    retires it. Right by the order: B's top on the thin slab, C's at 300; a break offering them
    is loud+. A keeps its top."""

    FOUND_BY = "review pr399-r3g"
    slabs = ((0, 5), (120, 3), (300, 5))
    where = {"A": (0, 5), "B": (120, 3), "C": (300, 5)}


class PlateInsertFrontBThickerDropC(_Plate):
    """A slab inserted in front (x = -100), B 8 high in place, C dropped. B+ is matched to B at its
    own place but at another order position, A's whole twin (the new slab in front) stands free
    and C is unmatched: P1b retires B+, and B's references break (right -> loud: the class's
    price, decision 260)."""

    FOUND_BY = "design s3339"
    ACCEPTED = {f"{r}|{c}": "decision 260" for r in ("pB", "cB") for c in ("V2", "V2s")}
    slabs = ((-100, 5), (0, 5), (60, 8))
    where = {"A": (0, 5), "B": (60, 8), "C": None}


class PlateBThinToCPlaceCDropped(_Plate):
    """B 3 high onto C's place, C deleted. No whole twin of C stands free, so the place reading
    stands (the uncorroborated order/place ambiguity, the ruling's 5, listed): the thin slab keeps
    C's ids and C's references follow it. Under the order reading C's references would break and
    B's take the thin slab; integration answers by index, the mirror image."""

    FOUND_BY = "design s3339"
    slabs = ((0, 5), (120, 3))
    where = {"A": (0, 5), "B": None, "C": (120, 3)}


class PlateBThinCThickTraded(_Plate):
    """B 3 high moves to C's place (120) and C 8 high to B's (60): nothing is left unmatched, so the
    place reading stands (the uncorroborated order/place ambiguity, listed): the slab at 60 keeps
    B's ids, the one at 120 C's. Under the order reading they trade; integration answers by index,
    the mirror image."""

    FOUND_BY = "design s3339"
    slabs = ((0, 5), (120, 3), (60, 8))
    where = {"A": (0, 5), "B": (60, 8), "C": (120, 3)}


class PlateCThinInPlaceBAway(_Plate):
    """B moves to 300 and C is 3 high in place. The thin slab is C's at C's own position: the order
    agrees, P1b doesn't fire, and C's references stay on it. B moved whole: R2' retires it, and a
    break offering the slab at 300 is loud+."""

    FOUND_BY = "design s3339"
    slabs = ((0, 5), (300, 5), (120, 3))
    where = {"A": (0, 5), "B": (300, 5), "C": (120, 3)}


class PlateBThicker(_Plate):
    """The control: B 8 high in place. Every reference stays on its slab."""

    FOUND_BY = "design s3339"
    slabs = ((0, 5), (60, 8), (120, 5))
    where = {"A": (0, 5), "B": (60, 8), "C": (120, 5)}
