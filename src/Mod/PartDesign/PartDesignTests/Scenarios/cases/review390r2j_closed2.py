"""Review pr390-r2j, T2 (ops#468): the closed-edge twin loop for a gone name (decision 206)
decides its entry before the owner's solve and holds nothing, so the element the reference kept
on integration (by its name, held exactly against the owner's other references) is free for
another reference's tier 3 nearest.

The model (scale s): a Pad of a circle r 10, 20 high; a groove: a YZ-plane circle r 3 at (y 0,
z 20) pocketed 24 long, symmetric (a channel along x, x -12..12). On the PR the top rim's crossings with
the channel's wall at y 3, (+-9.539, 3, 20), are closed-edge twins (`0of2`/`1of2`, GEN,ORD,CLS;
probed); those at y -3 carry roles. c_p is the one at (-9.539, 3, 20). A second Pocket, 1 deep,
from a sketch at z 20 with two rectangles: N, x -9.40..-8.80, y 3.10..3.30 (its corner y_ref at
(-9.40, 3.10, 20), 0.171 from c_p), and F, x -1..1, y -8..-7 (keeps the pocket valid).

One edit: the groove's sketch moved 5 toward -x (the channel spans x -17..7): its crossings at
x > 0 go, so c_p is alone in its group (renamed on the PR) and stays where it was; and N is deleted.
c_p follows or breaks (decision 206); y_ref's pocket is gone: it breaks, the crossing 0.171 away
being the groove's.
"""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
YZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 1, 1), 120))
CX = math.sqrt(100 - 9)


class R2jClosedTwinGoneFreesElement(Scenario):
    """c_p and y_ref in one owner (a sketch attached at c_p, y_ref its external vertex)."""

    AXES = ("M3", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2j"
    TIER = "F"
    SIZE = 20
    SCALE = 1.0
    REFS = ("c_p", "y_ref")
    BEFORE = {"c_p": (-CX, 3), "y_ref": (-9.40, 3.10)}
    ONE_OWNER = True
    edited = False

    def place(self, name):
        x, y = self.BEFORE[name]
        return vertex(V(x * self.scale, y * self.scale, 20 * self.scale))

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(name)
            return OwnOrBroken(self.place("c_p")) if name == "c_p" else BROKEN

        return expect

    def build(self, doc):
        s = self.scale
        self.edited = False
        body = m.body(doc)
        disk = m.sketch(doc, "Disk", [m.circle(0, 0, 10 * s)], body)
        m.pad(body, disk, 20 * s)
        self.tool = m.sketch(doc, "Tool", [m.circle(0, 20 * s, 3 * s)], body, placement=YZ)
        self.groove = groove = m.pocket(body, self.tool, 24 * s, "Groove")
        groove.SideType = "Symmetric"
        doc.recompute()
        self.sk = m.sketch(
            doc, "Small",
            m.rectangle(-9.40 * s, 3.10 * s, -8.80 * s, 3.30 * s) + m.rectangle(-1 * s, -8 * s, 1 * s, -7 * s),
            body, z=20 * s,
        )
        pocket = m.pocket(body, self.sk, 1 * s, "Small")
        doc.recompute()
        subs = [self.names(pocket, self.place(n))[0] for n in self.REFS]
        if self.ONE_OWNER:
            probe = body.newObject("Sketcher::SketchObject", "Probe")
            probe.AttachmentSupport = [(pocket, subs[0])]
            probe.MapMode = "Translate"
            probe.addExternal(pocket.Name, subs[1])
            self.ref(self.REFS[0], probe, "AttachmentSupport", self.expectation(self.REFS[0]), Attached())
            self.ref(self.REFS[1], probe, "ExternalGeometry", self.expectation(self.REFS[1]))
        else:
            for name, sub in zip(self.REFS, subs):
                pt = body.newObject("PartDesign::Point", "On" + name)
                pt.AttachmentSupport = [(pocket, sub)]
                pt.MapMode = "CenterOfMass"
                self.ref(name, pt, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = pocket
        doc.recompute()

    def edit(self, doc):
        # the groove's sketch moved 5 toward -x: the channel spans x -17..7
        self.tool.Placement = App.Placement(V(-5 * self.scale, 0, 0), YZ.Rotation)
        self.sk.delGeometries([0, 1, 2, 3])
        self.edited = True


class R2jClosedTwinGoneFreesElementSwapped(R2jClosedTwinGoneFreesElement):
    """y_ref attached, c_p external."""

    REFS = ("y_ref", "c_p")


class R2jClosedTwinGoneFreesElementTwoOwners(R2jClosedTwinGoneFreesElement):
    """The control: one datum point each."""

    ONE_OWNER = False
