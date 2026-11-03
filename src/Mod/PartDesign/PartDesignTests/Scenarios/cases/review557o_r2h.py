# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr557o-r2h (fork PR 557o round 2h, the rebase onto fork PR 405 and the stack on fork
PR 411): attacks on the resolution. (1) PR 411's held record and its early take (a feature
recomputed alone takes the held records of its closure) against this PR's frame `p` and sources
`q`: a record taken while its target still awaits its recompute pairs the old shape with sources
(and their digests) that already hold the edit. (2) PR 405's migration paths (the place pick, the
index carry, the exact check) with a rigid turn of the part onto itself, a turn with another
edit, and the cross-platform reorder emulated by traded names in the saved map.

Designed geometry only: a rectangle x -10..10, y -5..5 on the Body's XY plane (FlatFace), padded
10; the part turned onto itself by the sketch's AttachmentOffset (180 about Z through the origin),
so every face has a twin at its old place. References: an App::FeaturePython holder's links to
the Pad's front wall (y = -5) and its vertical edge at (10, -5), or the same of the Body. The
expectation follows the part (decision 212): after the turn the front wall is the wall at y = +5,
the edge the one at (-10, 5); a break is loud."""

import os
import shutil
import tempfile

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Scenario, X, Y, Z, edge, face
from PartDesignTests.Scenarios.harness import ScenarioError

import re
import zipfile
import types

# migration_rename.py's file helpers (copied: integration's old build has no such module)
def currentRevision():
    """The naming revision of this build, from a new V2 document's element map version."""
    doc = App.newDocument("NamingMigrationRevision")
    try:
        doc.HistoryAlgorithm = "V2"
        box = doc.addObject("Part::Box", "Box")
        match = re.search(r"\.F([0-9]+)", box.getCorrectElementMapVersion())
        return int(match.group(1))
    finally:
        App.closeDocument(doc.Name)


def ageStamps(xml):
    """The document's XML with every shape stamped with the previous naming revision."""
    previous = currentRevision() - 1

    def age(match):
        return re.sub(r"\.F[0-9]+", ".F%d" % previous, match.group(0))

    return re.sub(r'ElementMap="[^"]*"', age, xml)


def readFile(path):
    with zipfile.ZipFile(path) as archive:
        return {info.filename: archive.read(info.filename) for info in archive.infolist()}


def writeFile(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def elementLine(lines, kind, index):
    """The position of the element's line in a saved element map: after `NameCount`, one line per
    element index, from 0."""
    section = next(
        i
        for i in range(len(lines) - 2)
        if lines[i] == kind and lines[i + 2].startswith("ChildCount")
    )
    count = next(i for i in range(section, len(lines)) if lines[i].startswith("NameCount"))
    return count + 1 + int(index[len(kind) :])


def swapNames(mapText, kind, a, b):
    """A saved element map with the names of elements `a` and `b` (`Face4`, `Face5`) traded."""
    lines = mapText.split("\n")
    i, j = elementLine(lines, kind, a), elementLine(lines, kind, b)
    lines[i], lines[j] = lines[j], lines[i]
    return "\n".join(lines)


def subShadow(xml, index):
    """The shadow of the one saved reference to `index`."""
    found = re.findall(r'<Sub value="%s" shadow="([^"]*)"' % index, xml)
    if len(found) != 1:
        raise ScenarioError("%d saved references to %s, not one" % (len(found), index))
    return found[0]


def renameElement(files, xml, producer, index):
    """The XML and the files with the element `index` of the producer's shape given a name no
    rebuild makes, in the producer's saved map and in the one reference's saved shadow: the file
    is consistent as saved (the name gives the stored index in the restored map), and the name
    is Missing in the rebuilt shape."""
    kind = re.match(r"[A-Za-z]+", index).group(0)
    mapFile = producer + ".Shape.Map.txt"
    lines = files[mapFile].decode("utf-8").split("\n")
    at = elementLine(lines, kind, index)
    line = re.fullmatch(r"(?P<name>.*)(?P<tail>\.[0-9]+ [0-9]+)", lines[at])
    if not line:
        raise ScenarioError("%s line %d isn't a name: %r" % (mapFile, at, lines[at]))
    name = line.group("name")
    renamed = re.sub(r";[A-Z,]+;_$", ";RNM;_", name)
    if renamed == name:
        raise ScenarioError("can't rename %r" % name)
    shadow = 'shadow="%s.%s"' % (name, index)
    if xml.count(shadow) != 1:
        raise ScenarioError("%d saved shadows of %s, not one" % (xml.count(shadow), index))
    lines[at] = renamed + line.group("tail")
    files[mapFile] = "\n".join(lines).encode("utf-8")
    return xml.replace(shadow, 'shadow="%s.%s"' % (renamed, index))



mr = types.SimpleNamespace(readFile=readFile, writeFile=writeFile, ageStamps=ageStamps,
                           renameElement=renameElement, swapNames=swapNames)

V = App.Vector
TURN = App.Placement(V(0, 0, 0), App.Rotation(Z, 180))


def originFeature(body, role):
    return [f for f in body.Origin.OriginFeatures if role in (getattr(f, "Role", ""), f.Name)][0]


class Box(Scenario):
    abstract = True
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("M3", "E7", "E2")
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r2h"
    TIER = "F"
    REFS = ("front", "corner_edge")
    held = "feature"  # or "body"
    turned = False  # whether the expectation follows the turn (set by the edit)

    def frontFace(self):
        y = 5 if self.turned else -5
        return face("plane", normal=V(0, 1 if self.turned else -1, 0), through=(0, y, 0))

    def cornerEdge(self):
        x, y = (-10, 5) if self.turned else (10, -5)
        return edge("line", direction=Z, through=(x, y, 0))

    def drawRectangle(self, sketch, reverse=False):
        pts = [V(-10, -5, 0), V(10, -5, 0), V(10, 5, 0), V(-10, 5, 0)]
        if reverse:
            pts = list(reversed(pts))
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.body = body
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        self.base.AttachmentSupport = [(originFeature(body, "XY_Plane"), "")]
        self.base.MapMode = "FlatFace"
        self.drawRectangle(self.base)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.base
        pad.Length = 10
        self.pad_ = pad
        doc.recompute()
        assert pad.isValid(), pad.getStatusString()
        target = pad if self.held == "feature" else body
        self.targetName = target.Name
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSub", "Front")
        holder.addProperty("App::PropertyLinkSub", "Corner")
        front = self.names(target, self.frontFace())
        corner = self.names(target, self.cornerEdge())
        holder.Front = (target, front)
        holder.Corner = (target, corner)
        self.holder = holder
        self.indexes = list(front) + list(corner)
        doc.recompute()
        self.ref("front", holder, "Front", lambda: self.want(self.frontFace))
        self.ref("corner_edge", holder, "Corner", lambda: self.want(self.cornerEdge))

    broken = False

    def want(self, predicate):
        return BROKEN if self.broken else predicate()

    def turn(self, doc):
        doc.getObject("Base").AttachmentOffset = TURN
        self.turned = True

    def resetHolder(self, doc):
        """A setter on the holder's links (the same values): its records are refreshed now."""
        holder = doc.getObject("Holder")
        holder.Front = holder.Front
        holder.Corner = holder.Corner


# ---- (1) PR 411's early take with this PR's sources


class RhTurnWithLengthen(Box):
    """Control (decision 234): the pad lengthened to 12 and the part turned onto itself in one
    recompute: one piece with another edit."""

    def edit(self, doc):
        doc.getObject("Pad").Length = 12
        self.turn(doc)
        doc.recompute()


class RhLengthenEarlyTakeThenTurn(Box):
    """The pad lengthened to 12; the holder's links set again (a setter while the Pad awaits its
    recompute: PR 411 holds the records); the sketch alone recomputed (obj.recompute(): the held
    records whose closure holds it are taken, with sources whose Pad digest holds the new Length,
    while the Pad's shape is the old one); then the part turned onto itself and the document
    recomputed. The other edit is invisible to the digest."""

    def edit(self, doc):
        doc.getObject("Pad").Length = 12
        self.resetHolder(doc)
        doc.getObject("Base").recompute()
        self.turn(doc)
        doc.recompute()


class RhLengthenEarlyTakeThenTurnBody(RhLengthenEarlyTakeThenTurn):
    held = "body"


class RhRedrawEarlyTakeThenTurn(Box):
    """As RhLengthenEarlyTakeThenTurn, the other edit every line of the sketch deleted and drawn
    again reversed at the same place (new IDs: decision 97 Q3's redraw in place)."""

    def edit(self, doc):
        base = doc.getObject("Base")
        base.delGeometries([0, 1, 2, 3])
        self.drawRectangle(base, reverse=True)
        self.resetHolder(doc)
        base.recompute()
        self.turn(doc)
        doc.recompute()


class RhRedrawEarlyTakeThenTurnBody(RhRedrawEarlyTakeThenTurn):
    held = "body"


class RhTurnEarlyTakeThenLengthen(Box):
    """The other order: the part turned onto itself, the links set again (held), the sketch alone
    recomputed (taken: the turned placement in the sources, the old shape and frame), then the
    pad lengthened and the document recomputed."""

    def edit(self, doc):
        self.turn(doc)
        self.resetHolder(doc)
        doc.getObject("Base").recompute()
        doc.getObject("Pad").Length = 12
        doc.recompute()


class RhTurnEarlyTakeThenLengthenBody(RhTurnEarlyTakeThenLengthen):
    held = "body"


class RhTurnEarlyTakeOnly(Box):
    """Control: the turn, the setter, the sketch alone, the document: nothing else edited."""

    def edit(self, doc):
        self.turn(doc)
        self.resetHolder(doc)
        doc.getObject("Base").recompute()
        doc.recompute()


class RhTurnEarlyTakeOnlyBody(RhTurnEarlyTakeOnly):
    held = "body"


# ---- (2) PR 405's migration paths with a turn


class Migrated(Box):
    """The document saved, its file rewritten (the stamps aged: a naming migration; `rewrite`),
    opened again, `beforeSave`/`afterOpen` edits around it, then the migration recompute."""

    abstract = True
    steps = ("migrate",)
    rename = False  # the referenced elements given names no rebuild makes (Missing)
    swap = False  # the front and back walls' names traded in the target's saved map (a reorder)

    def beforeSave(self, doc):
        pass

    def afterOpen(self, doc):
        pass

    def migrate(self, doc):
        self.beforeSave(doc)
        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        path = os.path.join(self.folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        files = mr.readFile(path)
        xml = mr.ageStamps(files["Document.xml"].decode("utf-8"))
        if self.rename:
            for index in self.indexes:
                xml = mr.renameElement(files, xml, self.targetName, index)
        if self.swap:
            mapFile = self.targetName + ".Shape.Map.txt"
            text = files[mapFile].decode("utf-8")
            files[mapFile] = mr.swapNames(text, "Face", self.indexes[0], self.backIndex).encode("utf-8")
        files["Document.xml"] = xml.encode("utf-8")
        mr.writeFile(path, files)
        self.doc = self.openDocument(path)
        self.afterOpen(self.doc)
        self.doc.recompute()

    def build(self, doc):
        super().build(doc)
        target = doc.getObject(self.targetName)
        self.backIndex = self.names(target, face("plane", normal=Y, through=(0, 5, 0)))[0]

    def newDocument(self, suffix="", interned=None):
        return super().newDocument(suffix, False if interned is None else interned)

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class RhMigratedTurnAfterOpen(Migrated):
    """The migration with the part turned onto itself after the open (an edit since the open)."""

    def afterOpen(self, doc):
        self.turn(doc)


class RhMigratedTurnAfterOpenBody(RhMigratedTurnAfterOpen):
    held = "body"


class RhMigratedTurnSaved(Migrated):
    """The part turned onto itself and saved before the recompute (saved touched), then the
    migration."""

    def beforeSave(self, doc):
        self.turn(doc)


class RhMigratedTurnSavedBody(RhMigratedTurnSaved):
    held = "body"


class RhMigratedRenamedTurnSaved(RhMigratedTurnSaved):
    """As RhMigratedTurnSaved, the references renamed in the file (Missing: the index carry and
    PR 405's place pick)."""

    rename = True


class RhMigratedRenamedTurnSavedBody(RhMigratedRenamedTurnSaved):
    held = "body"


class RhMigratedRenamedTurnAfterOpenBody(RhMigratedTurnAfterOpenBody):
    rename = True


class RhMigratedRenamedTurnLengthenSavedBody(RhMigratedRenamedTurnSavedBody):
    """As RhMigratedRenamedTurnSavedBody with the pad lengthened to 12 too (one piece with
    another edit, decision 234)."""

    def beforeSave(self, doc):
        self.turn(doc)
        doc.getObject("Pad").Length = 12


class RhMigratedSwappedTurnSavedBody(RhMigratedTurnSavedBody):
    """As RhMigratedTurnSavedBody, the front and back walls' names traded in the Body's saved map
    (OCCT's storage order on another platform, PR 405's reorder): the saved name gives the back
    wall's index in the restored map."""

    swap = True


class RhMigratedSwappedTurnSaved(RhMigratedTurnSaved):
    swap = True


class RhMigratedSwappedNoTurnBody(Migrated):
    """Control: the reorder alone, nothing turned."""

    held = "body"
    swap = True


# ---- (3) the early take hides a digest edit from decision 234: R2cPadReversedFlip's family


from PartDesignTests.Scenarios.harness import Attached

FLIP_X = App.Placement(V(0, 0, 0), App.Rotation(X, 180))


class FlipBox(Scenario):
    """review pr557s-r2c's R2cPadBase: a rectangle x -10..10, y -5..5 on the Body's XY plane
    (FlatFace), padded 10. References: the +y wall, the top and the bottom cap, each a sketch
    attached (FlatFace) to the face. The edit turns the base sketch 180 about X and sets the pad
    Reversed: the pad still goes up, the same solid (z 0..10); convention 10.1: the references
    stay where they are globally (R2cPadReversedFlip: correct on integration's naming for top and
    bottom, broken by the PR's decision 234 when made in one recompute)."""

    abstract = True
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("M3", "E5")
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r2h"
    TIER = "F"
    REFS = ("side_py", "top", "bottom")
    POINTS = {"side_py": (0, 5, 5), "top": (0, 0, 10), "bottom": (0, 0, 0)}

    def expect(self, name):
        return face(surface="plane", contains=V(*self.POINTS[name]))

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        self.base.AttachmentSupport = [(originFeature(body, "XY_Plane"), "")]
        self.base.MapMode = "FlatFace"
        pts = [V(-10, -5, 0), V(10, -5, 0), V(10, 5, 0), V(-10, 5, 0), V(-10, -5, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.base
        pad.Length = 10
        self.pad_ = pad
        doc.recompute()
        assert pad.isValid(), pad.getStatusString()
        self.owners = []
        for name in self.REFS:
            element = self.names(pad, self.expect(name))[0]
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(pad, element)]
            owner.MapMode = "FlatFace"
            doc.recompute()
            self.owners.append(owner)
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), Attached())

    def resetOwners(self):
        for owner in self.owners:
            owner.AttachmentSupport = owner.AttachmentSupport

    def check(self):
        box = self.pad_.Shape.BoundBox
        assert abs(box.ZMin) < 1e-6 and abs(box.ZMax - 10) < 1e-6, box


class RhReversedEarlyTakeThenFlip(FlipBox):
    """The pad set Reversed (it now goes down: z -10..0, not yet recomputed); the face sketches'
    AttachmentSupport set again (a setter while the Pad awaits its recompute: PR 411 holds the
    records); the base sketch alone recomputed (the held records taken: their sources' Pad digest
    holds Reversed, the shape and frame are the old ones); then the base sketch turned 180 about X
    and the document recomputed: the same solid as before. Decision 234 broke the one-recompute
    form; here the digest no longer shows the other edit."""

    def edit(self, doc):
        self.pad_.Reversed = True
        self.resetOwners()
        self.base.recompute()
        self.base.AttachmentOffset = FLIP_X
        doc.recompute()
        self.check()


class RhReversedEarlyTakeThenFlipNoSetter(FlipBox):
    """Control: as RhReversedEarlyTakeThenFlip without the setter (nothing held, so nothing taken
    early): decision 234's break expected."""

    def edit(self, doc):
        self.pad_.Reversed = True
        self.base.recompute()
        self.base.AttachmentOffset = FLIP_X
        doc.recompute()
        self.check()


class RhReversedSetterRecomputeThenFlip(FlipBox):
    """The setter's records taken at the end of a full recompute instead: the pad set Reversed,
    the setter, the document recomputed (the pad goes down), then flipped (turned 180 about X:
    the pad goes up again) and recomputed. Two edits in two recomputes: in the second, the part
    turned as one piece (decision 212: the references follow the turn)."""

    steps = ("reverse", "flip")
    POINTS_AFTER = {"side_py": (0, -5, 5), "top": (0, 0, 10), "bottom": (0, 0, 0)}

    def reverse(self, doc):
        self.pad_.Reversed = True
        self.resetOwners()
        doc.recompute()

    def flip(self, doc):
        self.base.AttachmentOffset = FLIP_X
        doc.recompute()
        self.check()

    def expect(self, name):
        if self.stepName == "reverse":
            # z -10..0: the +y wall at y = 5, the top cap is the sketch plane z = 0, bottom z = -10
            return face(surface="plane", contains=V(*{"side_py": (0, 5, -5), "top": (0, 0, -10), "bottom": (0, 0, 0)}[name]))
        if self.stepName == "flip":
            return face(surface="plane", contains=V(*{"side_py": (0, -5, 5), "top": (0, 0, 10), "bottom": (0, 0, 0)}[name]))
        return face(surface="plane", contains=V(*self.POINTS[name]))


class RhReversedSetterOnlyThenFlip(FlipBox):
    """Control: the setter (held), no early take: the pad set Reversed, the setter, the flip, one
    document recompute: decision 234's break expected."""

    def edit(self, doc):
        self.pad_.Reversed = True
        self.resetOwners()
        self.base.AttachmentOffset = FLIP_X
        doc.recompute()
        self.check()


class RhReversedEarlyTakeByOwnerThenFlip(FlipBox):
    """As RhReversedEarlyTakeThenFlip, the early take by the face sketches recomputed alone
    instead of the base sketch (each holds the Pad in its closure)."""

    def edit(self, doc):
        self.pad_.Reversed = True
        self.resetOwners()
        for owner in self.owners:
            owner.recompute()
        self.base.AttachmentOffset = FLIP_X
        doc.recompute()
        self.check()
