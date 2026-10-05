# SPDX-License-Identifier: LGPL-2.1-or-later

"""Element references through links whose target changes, and variant links (ops#42, ops#53).

Designed geometry. The part document has a spreadsheet configuration table (set up as
Spreadsheet's "Configuration table" dialog does) with two box sizes, "Small" (10 x 10 x 5, the
default) and "Large" (30 x 20 x 8), driving a PartDesign::AdditiveBox in a Body whose `Config` is a
CopyOnChange enumeration. Body2 holds a fixed Large box. A variant link (`LinkCopyOnChange` =
Tracking) shows a copy of the Body in its own configuration, made in the assembly's document.

The expectations are geometric: the face a reference names is the top face of the box the link
shows (z = its height), and a link's bounding box is that box.

Each case runs with V1 names, V2 names, and V2 names with the reference solver on.
"""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App
import JointObject

CONFIGS = {"Small": (10.0, 10.0, 5.0), "Large": (30.0, 20.0, 8.0)}
# Configuration: (history algorithm, reference solver).
NAMINGS = {"V1": ("V1", False), "V2": ("V2", False), "V2s": ("V2", True)}
TOL = 1e-6


def _newDocument(name, naming):
    doc = App.newDocument(name)
    algorithm, solver = NAMINGS[naming]
    if hasattr(doc, "HistoryAlgorithm"):
        doc.HistoryAlgorithm = algorithm
    if hasattr(doc, "ReferenceSolver"):
        # Explicitly, also when off: new documents start with it on (ops#7).
        doc.ReferenceSolver = solver
    return doc


def _bbox(shape):
    b = shape.BoundBox
    return [round(v, 6) for v in (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)]


def _box(config, height=None):
    length, width, h = CONFIGS[config]
    return [0.0, 0.0, 0.0, length, width, h if height is None else height]


def _buildPart(naming):
    """The part document: the configuration table, Body (Config, CopyOnChange) and Body2."""
    doc = _newDocument("VariantLinkPart", naming)
    sheet = doc.addObject("Spreadsheet::Sheet", "Sheet")
    body = doc.addObject("PartDesign::Body", "Body")
    # Rows are configurations: A1 shows the active one, A2:A3 are their names, and B1:D1
    # (aliases BoxL, BoxW, BoxH) are bound to the active row.
    sheet.set("A2", "Small")
    sheet.set("A3", "Large")
    for row, name in ((2, "Small"), (3, "Large")):
        for col, value in zip("BCD", CONFIGS[name]):
            sheet.set("%s%d" % (col, row), str(value))
    body.addProperty("App::PropertyEnumeration", "Config", "Configuration")
    body.setPropertyStatus("Config", "CopyOnChange")
    body.setExpression("Config.Enum", "Sheet.cells[<<A2:|>>]")
    doc.recompute()
    sheet.set("A1", "=hiddenref(Body.Config.String)")
    sheet.setExpression(
        ".cells.Bind.B1.D1",
        "tuple(.cells; <<B>> + str(hiddenref(Body.Config) + 2); "
        "<<D>> + str(hiddenref(Body.Config) + 2))",
    )
    doc.recompute()
    sheet.setAlias("B1", "BoxL")
    sheet.setAlias("C1", "BoxW")
    sheet.setAlias("D1", "BoxH")
    box = body.newObject("PartDesign::AdditiveBox", "Box")
    box.setExpression("Length", "Sheet.BoxL")
    box.setExpression("Width", "Sheet.BoxW")
    box.setExpression("Height", "Sheet.BoxH")
    body2 = doc.addObject("PartDesign::Body", "Body2")
    box2 = body2.newObject("PartDesign::AdditiveBox", "Box2")
    box2.Length, box2.Width, box2.Height = CONFIGS["Large"]
    doc.recompute()
    return doc


def _topFace(shape, height):
    """The name of the face at z = height, and of the vertex at (0, 0, height)."""
    face = next(
        "Face%d" % (i + 1)
        for i, f in enumerate(shape.Faces)
        if abs(f.BoundBox.ZMin - height) < TOL and abs(f.BoundBox.ZMax - height) < TOL
    )
    vertex = next(
        "Vertex%d" % (i + 1)
        for i, v in enumerate(shape.Vertexes)
        if (v.Point - App.Vector(0, 0, height)).Length < TOL
    )
    return face, vertex


class VariantLinkTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp())
        self.docs = []

    def tearDown(self):
        self.closeAll()
        shutil.rmtree(self.dir, ignore_errors=True)

    def closeAll(self):
        for name in reversed(self.docs):
            if name in App.listDocuments():
                App.closeDocument(name)
        self.docs = []

    def start(self, naming):
        """The part document, saved, and a saved, empty assembly document."""
        self.closeAll()
        self.part = _buildPart(naming)
        self.part.saveAs(os.path.join(self.dir, "VariantLinkPart.FCStd"))
        self.doc = _newDocument("VariantLinkAsm", naming)
        # A link to another document needs a saved owner.
        self.doc.saveAs(os.path.join(self.dir, "VariantLinkAsm.FCStd"))
        self.docs = [self.part.Name, self.doc.Name]

    def reopen(self):
        """Saves both documents, closes them and opens the assembly (the part loads with it)."""
        self.part.save()
        self.doc.save()
        path = self.doc.FileName
        self.closeAll()
        self.doc = App.openDocument(path)
        self.part = App.getDocument("VariantLinkPart")
        self.docs = [self.part.Name, self.doc.Name]

    def assertTopFace(self, link, sub, box, msg):
        self.assertNotIn("?", sub, msg + ": the reference is marked missing")
        face = link.getSubObject(sub)
        self.assertIsNotNone(face, msg + ": " + sub + " not found")
        self.assertAlmostEqual(face.BoundBox.ZMin, box[5], 6, msg + ": " + sub + " isn't the top")
        self.assertAlmostEqual(face.BoundBox.ZMax, box[5], 6, msg + ": " + sub + " isn't the top")


class TestLinkRetargetJoints(VariantLinkTestBase):
    """A Fixed joint between the top faces of LinkA (grounded) and LinkB, at their corner
    (0, 0, H), survives saving and reopening after the links' targets change (ops#42). Once
    LinkB is moved away and the assembly solved, both boxes are at (0, 0, 0)-(L, W, H) of the
    configuration they show."""

    def build(self, naming, variant, jointConfig):
        self.start(naming)
        body = self.part.getObject("Body")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        joints = self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.links = []
        for name in ("LinkA", "LinkB"):
            link = self.doc.addObject("App::Link", name)
            link.LinkedObject = body
            self.assembly.addObject(link)
            self.links.append(link)
        self.doc.recompute()
        if variant:
            for link in self.links:
                link.LinkCopyOnChange = "Tracking"
            self.doc.recompute()
            for link in self.links:
                link.Config = jointConfig
            self.doc.recompute()
        height = CONFIGS[jointConfig][2]
        refs = [[link, list(_topFace(link.Shape, height))] for link in self.links]
        self.links[1].Placement = App.Placement(App.Vector(60, 40, 20), App.Rotation(30, 20, 10))
        self.doc.recompute()
        ground = joints.newObject("App::FeaturePython", "GroundedJoint")
        JointObject.GroundedJoint(ground, self.links[0])
        self.joint = joints.newObject("App::FeaturePython", "Fixed")
        JointObject.Joint(self.joint, 0)
        if App.GuiUp:
            # As the joint commands do: without view providers, a reopened joint fails in
            # redrawJointPlacements and the solve leaves LinkB where it is (ops#113).
            JointObject.ViewProviderGroundedJoint(ground.ViewObject)
            JointObject.ViewProviderJoint(self.joint.ViewObject)
        self.joint.Proxy.setJointConnectors(self.joint, refs)
        self.doc.recompute()
        self.assertEqual(self.assembly.solve(), 0)
        self.doc.recompute()

    def checkReopened(self, config, msg):
        self.reopen()
        self.doc.recompute()
        self.doc.recompute()
        assembly = self.doc.getObject("Assembly")
        joint = self.doc.getObject("Fixed")
        linkA = self.doc.getObject("LinkA")
        linkB = self.doc.getObject("LinkB")
        linkB.Placement = App.Placement(App.Vector(60, 40, 20), App.Rotation(30, 20, 10))
        self.doc.recompute()
        self.assertEqual(assembly.solve(), 0, msg + ": solve")
        self.doc.recompute()
        box = _box(config)
        for link, ref in ((linkA, joint.Reference1), (linkB, joint.Reference2)):
            self.assertIs(ref[0], link, msg)
            self.assertTopFace(link, ref[1][0], box, msg + " " + link.Name)
        self.assertFalse(
            {"Invalid", "Error"} & set(joint.State), msg + ": joint " + str(joint.State)
        )
        self.assertEqual(_bbox(linkA.Shape), box, msg + ": LinkA")
        self.assertEqual(_bbox(linkB.Shape), box, msg + ": LinkB, the joint didn't hold")

    def runCase(self, variant, jointConfig, config, change=None):
        for naming in NAMINGS:
            with self.subTest(naming=naming):
                self.build(naming, variant, jointConfig)
                if change:
                    change()
                    self.doc.recompute()
                    self.doc.recompute()
                    self.assertEqual(self.assembly.solve(), 0, naming + ": solve after the change")
                    self.doc.recompute()
                self.checkReopened(config, naming)

    def test_variant_links(self):
        """Variant links on the non-default configuration, then the joint."""
        self.runCase(True, "Large", "Large")

    def test_variant_links_default(self):
        """Variant links on the default configuration (no copy), then the joint."""
        self.runCase(True, "Small", "Small")

    def test_plain_links(self):
        """Plain links."""
        self.runCase(False, "Small", "Small")

    def test_variant_switched_after_joint(self):
        """The joint on the default configuration, then both links switched to Large: each link
        moves to a new copy of the Body."""

        def change():
            for link in self.links:
                link.Config = "Large"

        self.runCase(True, "Small", "Large", change)

    def test_variant_source_edited(self):
        """Variant links on Large, the joint, then a cell of the part's sheet that no box uses
        edited: the links remake their copies, with new object IDs."""

        def change():
            self.part.getObject("Sheet").set("F1", "note")
            self.part.recompute()

        self.runCase(True, "Large", "Large", change)

    def test_plain_source_switched(self):
        """Plain links, the joint, then the part's own Body.Config switched to Large."""

        def change():
            self.part.getObject("Body").Config = "Large"
            self.part.recompute()

        self.runCase(False, "Small", "Large", change)

    def test_plain_retarget(self):
        """Plain links, the joint, then both links pointed at Body2 (the Large box)."""

        def change():
            for link in self.links:
                link.LinkedObject = self.part.getObject("Body2")

        self.runCase(False, "Small", "Large", change)


class TestLinkRetargetProperties(VariantLinkTestBase):
    """The other link property types follow a retarget too (ops#42), and a reference that
    doesn't pass through the retargeted link keeps its name."""

    def test_retarget_link_properties(self):
        for naming in NAMINGS:
            with self.subTest(naming=naming):
                self.start(naming)
                body = self.part.getObject("Body")
                link = self.doc.addObject("App::Link", "LinkA")
                link.LinkedObject = body
                other = self.doc.addObject("App::Link", "LinkC")
                other.LinkedObject = body
                group = self.doc.addObject("App::Part", "Group")
                group.addObject(link)
                self.doc.recompute()
                top, corner = _topFace(link.Shape, CONFIGS["Small"][2])
                left = next(
                    "Face%d" % (i + 1)
                    for i, f in enumerate(other.Shape.Faces)
                    if abs(f.BoundBox.XMin) < TOL and abs(f.BoundBox.XMax) < TOL
                )
                refs = self.doc.addObject("App::FeaturePython", "Refs")
                refs.addProperty("App::PropertyLinkSub", "Sub")
                refs.addProperty("App::PropertyLinkSubList", "SubList")
                refs.addProperty("App::PropertyXLinkSubList", "XSubList")
                refs.addProperty("App::PropertyXLinkSub", "Path")
                refs.Sub = (link, [top])
                refs.SubList = [(link, [top, corner]), (other, [left])]
                refs.XSubList = [(link, [top]), (other, [left])]
                # A subname path through a container.
                refs.Path = (group, ["LinkA." + top])
                self.doc.recompute()

                link.LinkedObject = self.part.getObject("Body2")
                self.doc.recompute()
                self.reopen()
                self.doc.recompute()

                link = self.doc.getObject("LinkA")
                other = self.doc.getObject("LinkC")
                group = self.doc.getObject("Group")
                refs = self.doc.getObject("Refs")
                large, small = _box("Large"), _box("Small")
                self.assertTopFace(link, refs.Sub[1][0], large, naming + " Sub")
                subList = refs.SubList
                self.assertIs(subList[0][0], link)
                self.assertTopFace(link, subList[0][1][0], large, naming + " SubList")
                self.assertNotIn("?", subList[0][1][1], naming + " SubList vertex")
                corner = link.getSubObject(subList[0][1][1])
                self.assertTrue(
                    (corner.Point - App.Vector(0, 0, large[5])).Length < TOL,
                    naming + " SubList vertex at " + str(corner.Point),
                )
                xSubList = {obj.Name: subs for obj, subs in refs.XSubList}
                self.assertTopFace(link, xSubList["LinkA"][0], large, naming + " XSubList")
                self.assertTopFace(group, refs.Path[1][0], large, naming + " path")
                # LinkC still shows the Small box: its left face is unchanged.
                self.assertEqual(_bbox(other.Shape), small)
                for name, sub in (
                    ("SubList", subList[1][1][0]),
                    ("XSubList", xSubList["LinkC"][0]),
                ):
                    self.assertNotIn("?", sub, naming + " " + name + " LinkC")
                    face = other.getSubObject(sub)
                    self.assertAlmostEqual(face.BoundBox.XMin, 0.0, 6, naming + " " + name)
                    self.assertAlmostEqual(face.BoundBox.XMax, 0.0, 6, naming + " " + name)

    def test_target_document_closed(self):
        """Closing the part document while the assembly stays open detaches the link's target,
        which is not a retarget: the saved reference keeps its mapped name (ops#40, ops#42)."""
        for naming in NAMINGS:
            with self.subTest(naming=naming):
                self.start(naming)
                link = self.doc.addObject("App::Link", "LinkA")
                link.LinkedObject = self.part.getObject("Body")
                self.doc.recompute()
                top, _ = _topFace(link.Shape, CONFIGS["Small"][2])
                refs = self.doc.addObject("App::FeaturePython", "Refs")
                refs.addProperty("App::PropertyXLinkSub", "Target")
                refs.Target = (link, [top])
                self.doc.recompute()
                self.part.save()
                App.closeDocument(self.part.Name)
                self.doc.save()
                with zipfile.ZipFile(self.doc.FileName) as z:
                    text = z.read("Document.xml").decode("utf-8")
                prop = re.search(
                    r'<Property name="Target" type="App::PropertyXLinkSub"[^>]*>(.*?)</Property>',
                    text,
                    re.S,
                )
                # One sub is saved on the XLink tag itself, several as Sub tags.
                subs = re.findall(
                    r'(?:<Sub value|<XLink [^>]*\bsub)="([^"]*)"(?: shadow="([^"]*)")?',
                    prop.group(1),
                )
                self.assertEqual(len(subs), 1, naming)
                self.assertEqual(subs[0][0], top, naming)
                self.assertTrue(subs[0][1].startswith(";"), naming + ": shadow " + subs[0][1])

    def test_target_document_closed_reopened(self):
        """The part document closed while the assembly stays open, then the assembly saved and
        reopened (ops#119). `Target` reaches the box's top face through LinkA, `Direct` (an XLink)
        straight in the part, beside it. While the part is closed, the assembly is recomputed,
        saved, and a file without `NamingRevision` is opened, so the consumer pass runs (ops#116):
        none of them reaches the part's destroyed objects. Reopened, with the part closed until
        then or reopened in between, each reference names the top face again: the same face,
        never another one."""
        height = CONFIGS["Small"][2]
        for naming in NAMINGS:
            for reopenPart in (False, True):
                with self.subTest(naming=naming, reopenPart=reopenPart):
                    self.start(naming)
                    body = self.part.getObject("Body")
                    link = self.doc.addObject("App::Link", "LinkA")
                    link.LinkedObject = body
                    self.doc.recompute()
                    top, _ = _topFace(link.Shape, height)
                    refs = self.doc.addObject("App::FeaturePython", "Refs")
                    refs.addProperty("App::PropertyXLinkSub", "Target")
                    refs.addProperty("App::PropertyXLinkSub", "Direct")
                    refs.Target = (link, [top])
                    refs.Direct = (body, [_topFace(body.Shape, height)[0]])
                    self.doc.recompute()
                    self.part.save()
                    partPath = self.part.FileName
                    App.closeDocument(self.part.Name)

                    # Objects made now can take the closed part's addresses.
                    other = _newDocument("VariantLinkOther", naming)
                    self.docs.append(other.Name)
                    for i in range(20):
                        other.addObject("Part::Box", "Box%d" % i)
                    other.recompute()
                    otherPath = os.path.join(self.dir, "VariantLinkOther.FCStd")
                    other.saveAs(otherPath)
                    App.closeDocument(other.Name)
                    _withoutNamingRevision(otherPath)
                    self.doc.recompute()
                    App.openDocument(otherPath)
                    self.doc.save()
                    if reopenPart:
                        App.openDocument(partPath)
                        self.doc.recompute()
                        self.doc.save()

                    path = self.doc.FileName
                    self.closeAll()
                    self.doc = App.openDocument(path)
                    self.part = App.getDocument("VariantLinkPart")
                    self.docs = [self.part.Name, self.doc.Name]
                    self.doc.recompute()
                    link = self.doc.getObject("LinkA")
                    refs = self.doc.getObject("Refs")
                    msg = "%s, part reopened %s" % (naming, reopenPart)
                    self.assertIs(refs.Target[0], link, msg)
                    self.assertTopFace(link, refs.Target[1][0], _box("Small"), msg + ": Target")
                    body = self.part.getObject("Body")
                    self.assertIs(refs.Direct[0], body, msg)
                    self.assertTopFace(body, refs.Direct[1][0], _box("Small"), msg + ": Direct")


def _faceAt(shape, height):
    """The name of the face at z = height."""
    return next(
        "Face%d" % (i + 1)
        for i, f in enumerate(shape.Faces)
        if abs(f.BoundBox.ZMin - height) < TOL and abs(f.BoundBox.ZMax - height) < TOL
    )


class TestLinkTargetReopened(VariantLinkTestBase):
    """A reference through a Link (`Target`), and an XLink straight into the part beside it
    (`Direct`), follow an edit of the part made after the part document was closed and reopened
    in the session (ops#120). The part is a 10 x 10 x 5 box; the edit, a fillet on its vertical
    edge at x = y = 0, renumbers the top face. Each reference then names the top face (z = 5) or
    is broken loudly; it never names another face. With objects allocated between the close and
    the reopen, the part's new objects can't take the old ones' addresses, which hid a missing
    registration before."""

    HEIGHT = 5.0

    def runCase(self, reopen, allocate=False):
        for naming in ("V2", "V2s"):
            with self.subTest(naming=naming):
                self.closeAll()
                part = _newDocument("LinkTargetPart", naming)
                body = part.addObject("PartDesign::Body", "Body")
                box = body.newObject("PartDesign::AdditiveBox", "Box")
                box.Length, box.Width, box.Height = 10.0, 10.0, self.HEIGHT
                part.recompute()
                part.saveAs(os.path.join(self.dir, "LinkTargetPart.FCStd"))
                doc = _newDocument("LinkTargetAsm", naming)
                doc.saveAs(os.path.join(self.dir, "LinkTargetAsm.FCStd"))
                self.docs = [part.Name, doc.Name]
                link = doc.addObject("App::Link", "LinkA")
                link.LinkedObject = body
                doc.recompute()
                top = _faceAt(link.Shape, self.HEIGHT)
                refs = doc.addObject("App::FeaturePython", "Refs")
                refs.addProperty("App::PropertyXLinkSub", "Target")
                refs.addProperty("App::PropertyXLinkSub", "Direct")
                refs.Target = (link, [top])
                refs.Direct = (body, [_faceAt(body.Shape, self.HEIGHT)])
                doc.recompute()
                if reopen:
                    part.save()
                    path = part.FileName
                    App.closeDocument(part.Name)
                    if allocate:
                        other = App.newDocument("LinkTargetOther")
                        self.docs.append(other.Name)
                        for i in range(200):
                            other.addObject("PartDesign::Body", "Body%d" % i)
                    part = App.openDocument(path)
                    self.docs.append(part.Name)
                    body = part.getObject("Body")
                    doc.recompute()

                edge = next(
                    "Edge%d" % (i + 1)
                    for i, e in enumerate(body.Shape.Edges)
                    if e.BoundBox.XMax < TOL and e.BoundBox.YMax < TOL and e.BoundBox.ZLength > 1
                )
                fillet = body.newObject("PartDesign::Fillet", "Fillet")
                fillet.Base = (part.getObject("Box"), [edge])
                fillet.Radius = 2.0
                part.recompute()
                doc.recompute()
                self.assertNotEqual(
                    _faceAt(link.Shape, self.HEIGHT), top, "the fillet must renumber the top face"
                )
                for name, obj in (("Target", link), ("Direct", body)):
                    msg = "%s %s, reopened %s, allocations %s" % (naming, name, reopen, allocate)
                    value = getattr(refs, name)
                    self.assertIs(value[0], obj, msg)
                    sub = value[1][0]
                    if "?" in sub:
                        continue  # broken loudly
                    face = obj.getSubObject(sub)
                    self.assertIsNotNone(face, msg + ": " + sub + " not found")
                    self.assertAlmostEqual(face.BoundBox.ZMin, self.HEIGHT, 6, msg + ": " + sub)
                    self.assertAlmostEqual(face.BoundBox.ZMax, self.HEIGHT, 6, msg + ": " + sub)

    def test_never_closed(self):
        self.runCase(False)

    def test_reopened(self):
        self.runCase(True)

    def test_reopened_after_allocations(self):
        self.runCase(True, allocate=True)


def _withoutNamingRevision(path):
    """Rewrites the file as one saved before ops#116: no `NamingRevision`."""
    with zipfile.ZipFile(path) as z:
        entries = [(info, z.read(info.filename)) for info in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in entries:
            if info.filename == "Document.xml":
                text = data.decode("utf-8")
                assert "NamingRevision=" in text, "the file has no NamingRevision"
                data = re.sub(r' NamingRevision="[0-9]+"', "", text).encode("utf-8")
            z.writestr(info, data)


class TestVariantLinkRecompute(VariantLinkTestBase):
    """After an edit of a variant link's source part, one recompute of the assembly shows the
    link in its own configuration (ops#53): the copies the edit makes are recomputed in the same
    pass, not left touched with the source's default configuration."""

    def test_source_edit_one_recompute(self):
        for naming in NAMINGS:
            with self.subTest(naming=naming):
                self.start(naming)
                link = self.doc.addObject("App::Link", "L")
                link.LinkedObject = self.part.getObject("Body")
                self.doc.recompute()
                link.LinkCopyOnChange = "Tracking"
                self.doc.recompute()
                link.Config = "Large"
                self.doc.recompute()
                self.assertEqual(_bbox(link.Shape), _box("Large"), naming)

                sheet = self.part.getObject("Sheet")
                for edit, cell, value, box in (
                    ("a cell no box uses", "F1", "note", _box("Large")),
                    ("the Large height", "D3", "12", _box("Large", 12.0)),
                ):
                    sheet.set(cell, value)
                    self.part.recompute()
                    self.doc.recompute()
                    msg = "%s, after editing %s and one recompute" % (naming, edit)
                    self.assertEqual(_bbox(link.Shape), box, msg)
                    touched = [o.Name for o in self.doc.Objects if "Touched" in o.State]
                    self.assertEqual(touched, [], msg + ": left touched")
                    # The part's own Body stays in its default configuration.
                    self.assertEqual(
                        _bbox(self.part.getObject("Body").Shape), _box("Small"), msg + ": source"
                    )


def _addVariantFeature(doc, body, base, feature, suppressed=None):
    """Adds `feature` ("fillet" or "pocket") to `body` after `base`, a box. `suppressed`, when
    given, is an expression for its Suppressed property."""
    if feature == "fillet":
        # The vertical edge at x = y = 0, so the top face keeps its z and loses a corner.
        feat = body.newObject("PartDesign::Fillet", "Fillet")
        edge = next(
            "Edge%d" % (i + 1)
            for i, e in enumerate(base.Shape.Edges)
            if e.BoundBox.XMax < TOL and e.BoundBox.YMax < TOL
        )
        feat.Base = (base, [edge])
        feat.Radius = 2
    else:
        # A 4 x 4 x 2 pocket down from the top, by a sketch on the top face's plane.
        import Part
        import Sketcher  # noqa: F401

        sketch = body.newObject("Sketcher::SketchObject", "PocketSketch")
        sketch.AttachmentSupport = (base, ["Face6"])
        sketch.MapMode = "FlatFace"
        corners = [App.Vector(x, y, 0) for x, y in ((3, 3), (7, 3), (7, 7), (3, 7))]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        feat = body.newObject("PartDesign::Pocket", "Pocket")
        feat.Profile = sketch
        feat.Length = 2
    if suppressed:
        feat.setExpression("Suppressed", suppressed)
    doc.recompute()
    return feat


def _buildFeaturePart(naming, feature):
    """The part document of _buildPart(), where the Large configuration also has `feature`
    (suppressed in Small, by the configuration table's column E), and Body3: a fixed Large box
    with the feature."""
    doc = _buildPart(naming)
    sheet = doc.getObject("Sheet")
    body = doc.getObject("Body")
    sheet.set("E2", "1")  # Small: suppressed
    sheet.set("E3", "0")  # Large: the feature is there
    sheet.setExpression(
        ".cells.Bind.E1.E1",
        "tuple(.cells; <<E>> + str(hiddenref(Body.Config) + 2); "
        "<<E>> + str(hiddenref(Body.Config) + 2))",
    )
    doc.recompute()
    sheet.setAlias("E1", "Plain")
    doc.recompute()
    _addVariantFeature(doc, body, doc.getObject("Box"), feature, "Sheet.Plain")
    body3 = doc.addObject("PartDesign::Body", "Body3")
    box3 = body3.newObject("PartDesign::AdditiveBox", "Box3")
    box3.Length, box3.Width, box3.Height = CONFIGS["Large"]
    doc.recompute()
    _addVariantFeature(doc, body3, box3, feature)
    return doc


def _describe(face):
    b = face.BoundBox
    return "%s z %.3g..%.3g, x %.3g..%.3g" % (
        type(face.Surface).__name__,
        b.ZMin,
        b.ZMax,
        b.XMin,
        b.XMax,
    )


class TestVariantTopologyChanged(VariantLinkTestBase):
    """A reference to a link's top face, made while the link shows the Small box, after the link
    moves to a Large box that also has a fillet or a pocket (ops#106): as a variant (Config set to
    Large, which unsuppresses the feature) and as a plain retarget (to Body3). A retarget keeps
    only the reference's index (ops#42, option A); the new target's faces are numbered
    differently. The reference must name the Large box's top face, or be marked missing: never
    another face. Checked after the recompute and again after saving and reopening."""

    def runCase(self, naming, feature, move):
        self.closeAll()
        self.part = _buildFeaturePart(naming, feature)
        self.part.saveAs(os.path.join(self.dir, "VariantLinkPart.FCStd"))
        self.doc = _newDocument("VariantLinkAsm", naming)
        self.doc.saveAs(os.path.join(self.dir, "VariantLinkAsm.FCStd"))
        self.docs = [self.part.Name, self.doc.Name]
        link = self.doc.addObject("App::Link", "LinkA")
        link.LinkedObject = self.part.getObject("Body")
        self.doc.recompute()
        if move == "variant":
            link.LinkCopyOnChange = "Tracking"
            self.doc.recompute()
        top, _ = _topFace(link.Shape, CONFIGS["Small"][2])
        refs = self.doc.addObject("App::FeaturePython", "Refs")
        refs.addProperty("App::PropertyLinkSub", "Sub")
        refs.Sub = (link, [top])
        self.doc.recompute()
        if move == "variant":
            link.Config = "Large"
        else:
            link.LinkedObject = self.part.getObject("Body3")
        self.doc.recompute()
        self.doc.recompute()
        self.assertEqual(_bbox(link.Shape), _box("Large"), "the link shows the Large box")
        self.assertTopOrMissing(link, refs.Sub[1][0], "%s, %s %s" % (naming, move, feature))
        self.reopen()
        self.doc.recompute()
        self.doc.recompute()
        link = self.doc.getObject("LinkA")
        refs = self.doc.getObject("Refs")
        self.assertTopOrMissing(
            link, refs.Sub[1][0], "%s, %s %s, reopened" % (naming, move, feature)
        )

    def assertTopOrMissing(self, link, sub, msg):
        if "?" in sub:
            return
        face = link.getSubObject(sub)
        self.assertIsNotNone(face, msg + ": " + sub + " not found")
        height = CONFIGS["Large"][2]
        self.assertTrue(
            abs(face.BoundBox.ZMin - height) < TOL and abs(face.BoundBox.ZMax - height) < TOL,
            "%s: %s names another face (%s), not the top or missing" % (msg, sub, _describe(face)),
        )


def _addTopologyCases():
    for naming in NAMINGS:
        for feature in ("fillet", "pocket"):
            for move in ("variant", "retarget"):

                def case(self, naming=naming, feature=feature, move=move):
                    self.runCase(naming, feature, move)

                name = "test_%s_%s_%s" % (move, feature, naming)
                case.__name__ = name
                case.__doc__ = "%s: the link moves to Large with a %s by %s." % (
                    naming,
                    feature,
                    "its Config" if move == "variant" else "LinkedObject",
                )
                setattr(TestVariantTopologyChanged, name, case)


_addTopologyCases()


def _savedProperty(path, prop):
    """The saved XML of the property `prop` in the document file at `path`."""
    with zipfile.ZipFile(path) as z:
        text = z.read("Document.xml").decode("utf-8")
    match = re.search(r'<Property name="%s" [^>]*>(.*?)</Property>' % prop, text, re.S)
    return match.group(1)


def _stripRetargetChecks(path):
    """Rewrites the document file at `path` without its saved retarget checks, as a build
    without ops#109 saves it."""
    with zipfile.ZipFile(path) as z:
        entries = [(info, z.read(info.filename)) for info in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in entries:
            if info.filename == "Document.xml":
                data = re.sub(rb' retarget="[^"]*"', b"", data)
            z.writestr(info, data)


def _ageStamps(path):
    """Rewrites the document file at `path` as a file of the previous naming revision (ops#103):
    its shapes' element map versions end in `.F<n-1>` (V2 only; a V1 file has no revision)."""
    doc = App.newDocument("VariantLinkRevision")
    try:
        doc.HistoryAlgorithm = "V2"
        version = doc.addObject("Part::Box", "Box").getCorrectElementMapVersion()
    finally:
        App.closeDocument(doc.Name)
    previous = ".F%d" % (int(re.search(r"\.F([0-9]+)", version).group(1)) - 1)
    with zipfile.ZipFile(path) as z:
        entries = [(info, z.read(info.filename)) for info in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in entries:
            if info.filename == "Document.xml":
                data = re.sub(
                    rb'ElementMap="[^"]*"',
                    lambda m: re.sub(rb"\.F[0-9]+", previous.encode(), m.group(0)),
                    data,
                )
            z.writestr(info, data)


# The reference properties of TestRetargetCheckSaved, and how each gives its reference to the
# link's top face.
REFERENCE_PROPS = {
    "Sub": ("App::PropertyLinkSub", lambda refs: refs.Sub[1][0]),
    "SubList": ("App::PropertyLinkSubList", lambda refs: refs.SubList[0][1][0]),
    "XSubList": ("App::PropertyXLinkSubList", lambda refs: refs.XSubList[0][1][0]),
}


class TestRetargetCheckSaved(VariantLinkTestBase):
    """A variant switch saved before the new copy's first recompute (ops#109). The switch makes
    the references to the link's top face index-only and holds the old top face's fingerprint
    for the copy's first recompute (ops#106). The file keeps that check, so the reopened file's
    first recompute runs it: with a fillet or a pocket in the Large variant, the index names a
    side face there and the reference goes missing; without one, the top face stands."""

    def saveInWindow(self, naming, feature):
        """References to the top face made on Small, the link switched to Large, and both
        documents saved and closed without a recompute: the copy has never been recomputed.
        Returns the assembly's path."""
        self.closeAll()
        self.part = _buildFeaturePart(naming, feature) if feature else _buildPart(naming)
        self.part.saveAs(os.path.join(self.dir, "VariantLinkPart.FCStd"))
        self.doc = _newDocument("VariantLinkAsm", naming)
        self.doc.saveAs(os.path.join(self.dir, "VariantLinkAsm.FCStd"))
        self.docs = [self.part.Name, self.doc.Name]
        link = self.doc.addObject("App::Link", "LinkA")
        link.LinkedObject = self.part.getObject("Body")
        self.doc.recompute()
        link.LinkCopyOnChange = "Tracking"
        self.doc.recompute()
        top, _ = _topFace(link.Shape, CONFIGS["Small"][2])
        refs = self.doc.addObject("App::FeaturePython", "Refs")
        for name, (kind, _) in REFERENCE_PROPS.items():
            refs.addProperty(kind, name)
        refs.Sub = (link, [top])
        refs.SubList = [(link, [top])]
        refs.XSubList = [(link, [top])]
        self.doc.recompute()
        link.Config = "Large"
        self.assertIsNot(link.LinkedObject, self.part.getObject("Body"), "no copy was made")
        self.part.save()
        self.doc.save()
        path = self.doc.FileName
        self.closeAll()
        return path

    def openAndRecompute(self, path):
        """Opens the assembly, recomputes it, and returns the link and the references by
        property."""
        self.doc = App.openDocument(path)
        self.part = App.getDocument("VariantLinkPart")
        self.docs = [self.part.Name, self.doc.Name]
        self.doc.recompute()
        self.doc.recompute()
        link = self.doc.getObject("LinkA")
        self.assertEqual(_bbox(link.Shape), _box("Large"), "the link shows the Large box")
        refs = self.doc.getObject("Refs")
        return link, {name: get(refs) for name, (_, get) in REFERENCE_PROPS.items()}

    def test_changed_topology_goes_missing(self):
        for naming in NAMINGS:
            for feature in ("fillet", "pocket"):
                with self.subTest(naming=naming, feature=feature):
                    msg = "%s, %s" % (naming, feature)
                    path = self.saveInWindow(naming, feature)
                    for name in REFERENCE_PROPS:
                        saved = _savedProperty(path, name)
                        self.assertIn(' retarget="', saved, "%s %s: no check saved" % (msg, name))
                    link, subs = self.openAndRecompute(path)
                    for name, sub in subs.items():
                        self.assertIn(
                            "?", sub, "%s %s: %s isn't marked missing" % (msg, name, sub)
                        )

    def test_check_survives_a_migration(self):
        """Both files from the previous naming revision (ops#103): the first recompute
        re-derives references from geometry, which leaves the check alone (it runs only on a
        lookup by name); the check runs after it and passes, and the references name the top
        face."""
        for naming in NAMINGS:
            with self.subTest(naming=naming):
                path = self.saveInWindow(naming, None)
                _ageStamps(path)
                _ageStamps(os.path.join(self.dir, "VariantLinkPart.FCStd"))
                link, subs = self.openAndRecompute(path)
                for name, sub in subs.items():
                    self.assertTopFace(link, sub, _box("Large"), naming + " " + name)
                self.doc.save()
                for name in REFERENCE_PROPS:
                    saved = _savedProperty(self.doc.FileName, name)
                    self.assertNotIn(' retarget="', saved, naming + " " + name)

    def test_same_topology_keeps_the_top(self):
        """Control: the Large variant has the Small one's faces; the check passes and the
        references name the top face, with the check in the file and without it (a file from a
        build without ops#109)."""
        for naming in NAMINGS:
            for saved in (True, False):
                with self.subTest(naming=naming, saved=saved):
                    msg = "%s, check %s" % (naming, "saved" if saved else "stripped")
                    path = self.saveInWindow(naming, None)
                    if not saved:
                        _stripRetargetChecks(path)
                    link, subs = self.openAndRecompute(path)
                    for name, sub in subs.items():
                        self.assertTopFace(link, sub, _box("Large"), msg + " " + name)
                    # The checks are used up: a save now writes none.
                    self.doc.save()
                    for name in REFERENCE_PROPS:
                        saved = _savedProperty(self.doc.FileName, name)
                        self.assertNotIn(' retarget="', saved, msg + " " + name)
