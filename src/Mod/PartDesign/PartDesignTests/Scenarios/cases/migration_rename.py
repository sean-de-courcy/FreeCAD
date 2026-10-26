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

"""Corpus cases (ops#504, class E's E5 and E6): the naming migration of a file whose references
were renamed by a naming fix (`notes/naming-class-E.md` 3.5, 3.6; `TestNamingGate`, ops#387,
ops#417, ops#475).

Ports (`corpus/predicted/E.json`): `GateIndexStatus|status_after_edit|V2s`,
`GateRenamedIndexShift|renamed_edge|V2s`, `GateRenamedMoving|renamed_edge|V2s` and
`CompatRenameRehearsal|all_references` (the row's column is macOS: see below).

A case saves its document, rewrites the saved file as TestNamingGate does (the stamps aged to the
previous naming revision; for a rename, the producer's saved element map and the reference's saved
shadow given the same name no rebuild makes; for a moved name, two faces trading names in the map)
and opens it again. The first recompute after the open is the migration recompute, with the
case's edit made before it (ops#417: an edit before the first recompute).

Models (designed): `Renamed*`/`CompatRenameRehearsal`: a 10 x 6 rectangle padded 4 high (`Pad`);
a holder's references are renamed edges, a face and a vertex. `GateIndexStatus`: TestNamingGate's
face pad model (Pad1 a 20 x 10 x 10 box, Pad2 its top face padded by 3, Pad3 Pad2's side face at
x = 20 padded by 2).

Not a case of its own: `CompatFingerprintCoverage|all_subs|any` is a check of the writer (every
saved element sub of a solver document has `fp`), scored on the saved file by TestCompatCorpus; no
element is judged. The renamed face, edge and vertex references of `CompatRenameRehearsal` need
their saved fingerprints to be kept by place, so they hold the property for the three element
kinds. `CompatRenameRehearsal|all_references|macOS` is a platform column: on macOS OCCT's storage
order gives the same elements other indexes (ops#475). The case emulates that on any platform by
an edit before the first recompute that shifts the indexes (the chamfer of ops#417), so its
verdict is the Windows one."""

import os
import re
import shutil
import tempfile
import zipfile

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Extruded,
    Scenario,
    ScenarioError,
    Settled,
    X,
    Y,
    Z,
    edge,
    face,
    pieces,
    vertex,
)
from PartDesignTests.Scenarios import models as m


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


class Migrates(Scenario):
    """A scenario with one step, `migrate`: the document saved, its file rewritten (`rewriteFile`),
    opened again and edited (`editAfterOpen`) before the migration recompute."""

    abstract = True
    area = "migration_rename"
    CLASSES = ("E",)
    AXES = ("gen", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "port"
    TIER = "F"
    steps = ("migrate",)

    def migrate(self, doc):
        folder = getattr(self, "folder", None) or tempfile.mkdtemp(prefix="NamingScenario")
        self.folder = folder
        path = os.path.join(folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        files = readFile(path)
        xml = ageStamps(files["Document.xml"].decode("utf-8"))
        xml = self.rewriteFile(files, xml)
        files["Document.xml"] = xml.encode("utf-8")
        writeFile(path, files)
        self.doc = self.openDocument(path)
        self.editAfterOpen(self.doc)

    def rewriteFile(self, files, xml):
        return xml

    def editAfterOpen(self, doc):
        pass

    def newDocument(self, suffix="", interned=None):
        # The renames edit the saved map as text, where a plain document keeps its names (an
        # interned one keeps them in its name table): InternNames stays off in every
        # configuration, so the V2si oracle reruns the V2s case.
        return super().newDocument(suffix, False if interned is None else interned)

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class RenamedBase(Migrates):
    """A 10 x 6 rectangle padded 4 high; a holder's reference to elements of the pad that the file
    renames. The edit before the first recompute is `editAfterOpen`."""

    abstract = True
    renamed = ()  # (holder property, predicate's name) filled by the subclasses

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 10, 6), body)
        pad = m.pad(body, profile, 4)
        doc.recompute()
        self.padName = pad.Name
        self.buildHolder(doc, pad)

    def rewriteFile(self, files, xml):
        for index in self.renamedIndexes:
            xml = renameElement(files, xml, self.padName, index)
        return xml

    def shiftChamfer(self, doc):
        """The corner (10, 0) cut: the front and right edges shortened and a chamfer line added
        between them. The chamfer comes in the sketch's wire between the front and right lines, so
        the pad's edge, face and vertex indexes after the front line shift; the elements away from
        the corner keep their places."""
        m.setLines(doc.Profile, {0: ((0, 0), (8, 0)), 1: ((10, 2), (10, 6))})
        doc.Profile.addGeometry(m.polyline([(8, 0), (10, 2)]), False)


class RenamedEdge(RenamedBase):
    """The top back edge (y = 6, z = 4) is the holder's reference, renamed in the file."""

    abstract = True
    REFS = ("renamed_edge",)
    backY = 6

    def topBack(self):
        return edge("line", direction=X, through=(0, self.backY, 4))

    def buildHolder(self, doc, pad):
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSub", "Ref")
        sub = self.names(pad, self.topBack())
        holder.Ref = (pad, sub)
        self.renamedIndexes = sub
        self.ref("renamed_edge", holder, "Ref", self.expected)

    def expected(self):
        return self.topBack()


class GateRenamedIndexShift(RenamedEdge):
    """ops#417, row 334: the file's reference to the top back edge has a name the rebuild no
    longer makes; the profile's corner at (10, 0) is chamfered before the first recompute, which
    shifts the edge indexes and leaves the referenced edge in place. The edge is at its saved place:
    a correct system keeps it (E5: by place, with the migration warning)."""

    def editAfterOpen(self, doc):
        self.shiftChamfer(doc)


class GateRenamedMoving(RenamedEdge):
    """Row 334', the control: the same file, with the profile's back side moved to y = 7 before the
    first recompute: nothing sits at the saved place and a Missing entry has no name to keep it
    by, so the design's answer is the loud break (E5)."""

    def expected(self):
        return BROKEN if self.stepName == "migrate" else self.topBack()

    def editAfterOpen(self, doc):
        m.setLines(doc.Profile, {1: ((10, 0), (10, 7)), 2: ((10, 7), (0, 7)), 3: ((0, 7), (0, 0))})


class CompatRenameRehearsal(RenamedBase):
    """E6's rename rehearsal on a designed model: a holder references the pad's three vertical
    edges at (10, 6), (0, 6) and (0, 0), its back face (y = 6) and its vertex (10, 6, 4); the file
    renames all of them, and the corner (10, 0) is chamfered before the first recompute, so the indexes
    shift as OCCT's storage order does on another platform (ops#475). Every reference is on its
    element by geometry, kept by place."""

    REFS = ("all_references", "face_reference", "vertex_reference")

    @staticmethod
    def verticals():
        corners = [(10, 6), (0, 6), (0, 0)]
        return pieces(
            edge(
                "line",
                direction=Z,
                where=lambda e: any(
                    abs(e.Vertexes[0].Point.x - x) < 1e-6 and abs(e.Vertexes[0].Point.y - y) < 1e-6
                    for x, y in corners
                ),
            )
        )

    @staticmethod
    def backFace():
        return face("plane", normal=Y, through=(0, 6, 0))

    @staticmethod
    def corner():
        return vertex((10, 6, 4))

    def buildHolder(self, doc, pad):
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSubList", "Edges")
        holder.addProperty("App::PropertyLinkSub", "Face")
        holder.addProperty("App::PropertyLinkSub", "Vertex")
        edges = self.verticals().select(pad.Shape)
        face_ = self.names(pad, self.backFace())
        vertex_ = self.names(pad, self.corner())
        holder.Edges = (pad, edges)
        holder.Face = (pad, face_)
        holder.Vertex = (pad, vertex_)
        self.renamedIndexes = list(edges) + face_ + vertex_
        self.ref("all_references", holder, "Edges", self.verticals)
        self.ref("face_reference", holder, "Face", self.backFace)
        self.ref("vertex_reference", holder, "Vertex", self.corner)

    def editAfterOpen(self, doc):
        self.shiftChamfer(doc)


class CompatRenameRehearsalAsIs(CompatRenameRehearsal):
    """The rehearsal's first run (E6): the same renamed file opened as it is, with no edit before the
    migration recompute. The indexes are those of the saved file, so the index carry holds today."""

    def editAfterOpen(self, doc):
        pass


class GateIndexStatus(Migrates):
    """ops#387, row 333: TestNamingGate's face pad model. Pad3's profile is Pad2's side face at
    x = 20 (FaceC); the file's FaceC holds the name of the face at x = 0 (FaceD), as a naming fix
    that moved a name leaves it. Step `migrate`: the aged file opened; the migration recompute puts
    the reference back on the face at its place, with the status "kept by its place after a naming
    migration". Step `edit`: Pad2 is made 4 high and recomputed; the reference resolves by its own
    name again, so the record of the place keep is over and the owner has no warning left."""

    REFS = ("status_after_edit",)
    steps = ("migrate", "edit")
    FACE_C = (20, 5, 11.5)
    FACE_D = (0, 5, 11.5)
    padLength = 3

    def faceC(self):
        return face(contains=(20, 5, 10 + self.padLength / 2))

    def expected(self):
        if self.stepName == "edit":
            return Settled(self.faceC())
        return self.faceC()

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad1 = m.pad(body, profile, 10, name="Pad1")
        doc.recompute()
        pad2 = body.newObject("PartDesign::Pad", "Pad2")
        pad2.Profile = (pad1, face(contains=(10, 5, 10)).one(pad1.Shape))
        pad2.Length = self.padLength
        doc.recompute()
        self.nameC = face(contains=self.FACE_C).one(pad2.Shape)[0]
        self.nameD = face(contains=self.FACE_D).one(pad2.Shape)[0]
        pad3 = body.newObject("PartDesign::Pad", "Pad3")
        pad3.Profile = (pad2, [self.nameD])
        pad3.Length = 2
        doc.recompute()
        # a first save with Pad3 on FaceD gives the shadow of a reference to FaceD
        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        first = os.path.join(self.folder, "First.FCStd")
        doc.saveAs(first)
        self.shadowD = subShadow(readFile(first)["Document.xml"].decode("utf-8"), self.nameD)
        pad3.Profile = (pad2, [self.nameC])
        doc.recompute()
        self.ref("status_after_edit", pad3, "Profile", self.expected, Extruded(2, X))

    def migrate(self, doc):
        path = os.path.join(self.folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        files = readFile(path)
        xml = ageStamps(files["Document.xml"].decode("utf-8"))
        shadowC = subShadow(xml, self.nameC)
        nameD = self.shadowD[: -len(self.nameD)]  # the name with its dot
        xml = xml.replace('shadow="%s"' % shadowC, 'shadow="%s%s"' % (nameD, self.nameC))
        mapFile = "Pad2.Shape.Map.txt"
        files[mapFile] = swapNames(
            files[mapFile].decode("utf-8"), "Face", self.nameC, self.nameD
        ).encode("utf-8")
        files["Document.xml"] = xml.encode("utf-8")
        writeFile(path, files)
        self.doc = self.openDocument(path)

    def edit(self, doc):
        self.padLength = 4
        doc.Pad2.Length = self.padLength

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)
