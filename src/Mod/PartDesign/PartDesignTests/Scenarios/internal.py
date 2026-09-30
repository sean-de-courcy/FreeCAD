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

"""Internal faces: a sketch with MakeInternals gives a face per region, and pads of single
regions keep their region when the sketch changes."""

import FreeCAD as App

from .harness import Attached, Extruded, Scenario, Z, face, internal
from . import models as m

V = App.Vector


class InternalEdit(Scenario):
    """A square 0..20 x 0..20 with a circle (10, 10), radius 4, inside, MakeInternals on: two
    regions, the ring and the disk (the sketch's InternalFaces). The ring is padded 10 high (Ring), the disk 5 high on top of
    that (Plug, filling the lower half of the hole); a sketch is attached to the ring's top."""

    abstract = True
    area = "internal faces"
    MULTI = True
    REFS = ("ring_profile", "disk_profile", "ring_top")
    centre = (10, 10)

    def ring(self):
        return internal(face("plane", contains=(1, 1, 0)))

    def disk(self):
        return internal(face("plane", contains=(*self.centre, 0)))

    def ringTop(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 20) + [m.circle(10, 10, 4)], body)
        profile.MakeInternals = True
        doc.recompute()
        ring = body.newObject("PartDesign::Pad", "Ring")
        ring.Profile = (profile, self.names(profile, self.ring()))
        ring.Length = 10
        plug = body.newObject("PartDesign::Pad", "Plug")
        plug.Profile = (profile, self.names(profile, self.disk()))
        plug.Length = 5
        doc.recompute()
        onTop = body.newObject("Sketcher::SketchObject", "OnRing")
        onTop.AttachmentSupport = [(ring, self.names(ring, self.ringTop())[0])]
        onTop.MapMode = "FlatFace"
        self.ref("ring_profile", ring, "Profile", self.ring, Extruded(10, Z))
        self.ref("disk_profile", plug, "Profile", self.disk, Extruded(5, Z))
        self.ref("ring_top", onTop, "AttachmentSupport", self.ringTop, Attached())


class InternalMoveCircle(InternalEdit):
    """The circle moves to (12, 9); it keeps its geometry ID."""

    def edit(self, doc):
        geometry = doc.Profile.Geometry
        geometry[4].Center = V(12, 9, 0)
        doc.Profile.Geometry = geometry
        self.centre = (12, 9)


class InternalAddCircle(InternalEdit):
    """A second circle, (4, 15) radius 2, is added: a third region, and the ring gets a second
    hole."""

    def edit(self, doc):
        doc.Profile.addGeometry(m.circle(4, 15, 2), False)
