# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection parity with Onshape (FreeCAD-CH, PLAN decision 350; notes/selection-parity.md).

P1: a multi-pick field stays armed for the next pick. A new Extrude's first region decides where
it opens (hands-on check A-1): the move restarts the edit, and the Profile field that took the
pick disarmed with the old dialog, so the second region became a plain selection and the Extrude
kept one region (journey S4b). Onshape's Profile field stays active and each region click adds.

Designed geometry: the Enclosure 40 x 40 x 10 at the origin (ResultBoxGuiCase.enclosure). A sketch
in the Enclosure at z 0 with two regions apart from it: R1 10 x 10 at x 100..110 (100 mm^2) and R2
5 x 10 at x 120..125 (50 mm^2), y 5..15. Neither touches the Enclosure, so the Pad opens New after
its first region; padded 10 (the default length) from both: (100 + 50) x 10 = 1500.
Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestDialogFlowGui import DialogFlowCase
from PartDesignTests.TestExpressionFieldsGui import pump, waitFor

ENCLOSURE = 16000


def visibleField(name):
    """The task view's visible reference field of that objectName, or None."""
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    found = [
        widget
        for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget, name)
        if widget.metaObject().className() == "PartDesignGui::ReferenceField"
        and widget.isVisible()
    ]
    return found[0] if found else None


def armed(field):
    return field is not None and bool(field.property("armed"))


class TestProfileFieldStaysArmedGui(DialogFlowCase):
    """P1: the Profile field after the first region of a new Extrude."""

    def regionsSketch(self):
        """The two-region sketch in the Enclosure; returns it and its regions' names {R1, R2}."""
        geometry = models.rectangle(100, 5, 110, 15) + models.rectangle(120, 5, 125, 15)
        sk = models.sketch(self.doc, "Regions", geometry, self.body)
        sk.MakeInternals = True
        self.doc.recompute()
        regions = {}
        for i, face in enumerate(sk.InternalShape.Faces):
            for name, area in (("R1", 100), ("R2", 50)):
                if abs(face.Area - area) < 1e-6:
                    regions[name] = "InternalFace%d" % (i + 1)
        self.assertEqual(sorted(regions), ["R1", "R2"], regions)
        return sk, regions

    def pickRegion(self, sk, region):
        """A region picked in the 3D view, through the sketch's part as the view gives it."""
        part = sk.getParentGeoFeatureGroup()
        Gui.Selection.addSelection(self.doc.Name, part.Name, sk.Name + "." + region)
        pump(0.3)

    def testSecondRegionAfterTheOpeningMoveIsAdded(self):
        """Nothing selected, Pad: its Profile field is armed. R1 picked: the pad and its sketch
        move to a new part (the edit restarts), and the Profile field is armed again. R2 picked:
        the Profile holds both regions, nothing is left selected; OK: the new part 1500, the
        Enclosure 16000."""
        self.enclosure()
        sk, regions = self.regionsSketch()
        bodies = self.bodyNames()
        made = self.newPad()
        self.assertTrue(waitFor(lambda: armed(visibleField("fieldProfile"))), "Profile isn't armed")

        self.pickRegion(sk, regions["R1"])
        self.assertTrue(
            waitFor(lambda: len(self.newBodies(bodies)) == 1),
            "the first region didn't open the pad in a new part",
        )
        [part] = self.newBodies(bodies)
        self.assertTrue(waitFor(lambda: made.getParentGeoFeatureGroup() == part))
        self.waitForPanel()
        self.assertTrue(
            waitFor(lambda: armed(visibleField("fieldProfile"))),
            "the Profile field disarmed after the first region",
        )

        self.pickRegion(sk, regions["R2"])
        self.assertTrue(
            waitFor(lambda: made.Profile is not None and len(made.Profile[1]) == 2),
            "the second region wasn't added: %s" % (made.Profile,),
        )
        self.assertEqual(sorted(made.Profile[1]), sorted([regions["R1"], regions["R2"]]))
        self.assertEqual(Gui.Selection.getSelectionEx(self.doc.Name), [])
        self.assertTrue(armed(visibleField("fieldProfile")))
        self.close(ok=True)
        self.doc.recompute()
        self.assertTrue(made.isValid(), made.getStatusString())
        self.assertAlmostEqual(part.Shape.Volume, 1500, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, ENCLOSURE, places=3)
