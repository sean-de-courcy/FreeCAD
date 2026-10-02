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

"""Cross-document links: SubShapeBinders in one document bind faces of a pad in another, and
follow them when the pad changes, with the binders' document open or closed (ops#18, ops#40).
Both documents are saved in a temporary folder."""

import os
import shutil
import tempfile

import FreeCAD as App

from .harness import Bound, Scenario, X, Z, face
from . import models as m


class CrossDocEdit(Scenario):
    """Document B: a rectangle (0..20 x 0..10, lines: front, right, back, left) padded 10 high.
    Document A (the scenario's): a SubShapeBinder of the pad's right face and one of its top
    face."""

    abstract = True
    area = "cross-document"
    REFS = ("binder_right", "binder_top")
    width, height = 20, 10
    closed = False  # edit B with A closed
    mixed = False  # B's InternNames is the opposite of A's (ops#6)

    def rightFace(self):
        return face("plane", normal=X, through=(self.width, 0, 0))

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.height))

    def path(self, doc):
        return os.path.join(self.folder, doc.Name + ".FCStd")

    def build(self, doc):
        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        target = self.newDocument("B", interned=(not self.interned) if self.mixed else None)
        target.saveAs(self.path(target))
        body = m.body(target)
        profile = m.sketch(target, "Profile", m.rectangle(0, 0, self.width, 10), body)
        pad = m.pad(body, profile, self.height)
        target.recompute()
        target.save()
        doc.saveAs(self.path(doc))
        for name, predicate in (("binder_right", self.rightFace), ("binder_top", self.topFace)):
            binder = doc.addObject("PartDesign::SubShapeBinder", name)
            binder.Support = [(pad, tuple(self.names(pad, predicate())))]
            self.ref(name, binder, "Support", predicate, Bound())
        doc.recompute()
        doc.save()

    def change(self, target):
        raise NotImplementedError

    def edit(self, doc):
        target = App.getDocument(self.documents[1])
        if not self.closed:
            self.change(target)
            target.recompute()
            return
        pathA, nameA = self.path(doc), doc.Name
        doc.save()
        App.closeDocument(nameA)
        self.change(target)
        target.recompute()
        target.save()
        App.closeDocument(target.Name)
        self.doc = App.openDocument(pathA)  # opens B too
        for obj in self.doc.Objects:
            obj.touch()

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class CrossDocNotch(CrossDocEdit):
    """A notch (x 8..12, 2 deep) is cut into the front side of B's profile: four new lines, and
    the pad's faces renumber. A is open."""

    def change(self, target):
        m.setLines(target.Profile, {0: ((0, 0), (8, 0))})
        target.Profile.addGeometry(m.polyline([(8, 0), (8, 2), (12, 2), (12, 0), (20, 0)]), False)


class CrossDocNotchClosed(CrossDocNotch):
    """As CrossDocNotch, with A saved and closed while B changes, then opened again."""

    closed = True


class CrossDocNotchMixed(CrossDocNotch):
    """As CrossDocNotch, with B's InternNames the opposite of A's (ops#6): A plain and B interned,
    or the reverse in V2i. A's binders hold names in B's form; their shapes are stored in A's."""

    mixed = True


class CrossDocNotchMixedClosed(CrossDocNotchMixed):
    """As CrossDocNotchMixed, with A saved and closed while B changes, then opened again."""

    closed = True


class CrossDocWidthClosed(CrossDocEdit):
    """B's right side moves from x = 20 to x = 26 (its line keeps its geometry ID) while A is
    closed."""

    closed = True

    def change(self, target):
        lines = {0: ((0, 0), (26, 0)), 1: ((26, 0), (26, 10)), 2: ((26, 10), (0, 10))}
        m.setLines(target.Profile, lines)
        self.width = 26
