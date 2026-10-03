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

"""Element name dumps of designed models, to check that names don't depend on order.

Element names must be the same on every platform and in every run. They can differ when the naming
code iterates a hash container, whose order differs between standard libraries (MSVC, libc++) and,
for pointer keys, between runs, or when OCCT's own result order varies (parallel booleans, an
offset's faces: ops#49).

Each model is built in a V1 and in a V2 document. A dump lists every element of the model's
features with its names, one line per element and name, sorted. An element is keyed by its type,
centroid and mass (length or area; a vertex by its point), not by its index, and the object IDs
(tags) in its names are replaced with object names. A V2 name's Linked and Connected Names are sets,
sorted by bytes with the tags in them (ops#19): the dump checks that, and sorts them again after
masking, since a new document's object IDs start at a random offset. Three checks use it:

- TestNamingGolden: the dump equals the golden file in NamingGolden/, which was generated on
  Windows. The same files are compared on every platform.
- TestNamingSeeded: two child processes run with FREECAD_NAMING_HASH_SEED set (the naming code's
  hash containers then iterate in another order, Part/App/NamingHash.h), and their dumps must equal
  a third child's, run without a seed.
- TestNamingRepeated: the model is built 5 times in this process, and the dumps with element
  indexes must be identical.

Each check also runs in V2i: a V2 document with InternNames on (ops#6, Task 1). Its names are
dumped through `App.expandMappedName`, and the dump must equal V2's: TestNamingGolden compares it
with the V2 golden file, so interning changes no name on any platform. TestNamingInterning checks
the exact bytes in one process (two documents from object ID 0, one plain and one interned), and
the interned names themselves against `NamingGolden/<Model>.V2i-ids.txt`.

The models are built in documents whose object IDs are above a bound (`models.newDocument`), so a
small tag that is no object's ID can't be masked as an object's name; TestNamingTagCollision
forces that case (ops#52).

Environment variables:
- FREECAD_NAMING_GOLDEN_UPDATE=<dir>: TestNamingGolden writes the golden files into <dir> (the
  source tree's NamingGolden folder) instead of comparing.
- FREECAD_NAMING_DUMP_DIR=<dir>: where a failing test writes its dumps (default: the temp dir).
"""

import difflib
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import Masker

V = App.Vector

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NamingGolden")
MODES = ("V1", "V2", "V2i")
REPEATS = 5
SEEDS = ("0x5eed0001", "0x9e3779b97f4a7c15")

# ---------------------------------------------------------------------------------------------
# Models. Each builds its objects in `doc` and returns the features whose shapes are dumped.
# The helpers are in Scenarios/models.py, shared with the naming scenarios.
# ---------------------------------------------------------------------------------------------


def modelSketch(doc):
    """Sketch vertex Reference IDs (S7), with line ends that meet within Confusion but not
    exactly, and FaceMaker's face names in an extrusion of two faces (S6)."""
    faces = models.sketch(
        doc,
        "Faces",
        models.rectangle(0, 0, 20, 10) + [models.circle(10, 5, 3)] + models.rectangle(30, 0, 40, 10),
    )
    near = models.sketch(
        doc,
        "Near",
        [
            Part.LineSegment(V(0, 0, 0), V(10, 0, 0)),
            Part.LineSegment(V(10 + 1e-9, 1e-9, 0), V(10, 10, 0)),
            Part.LineSegment(V(10, 10, 0), V(1e-9, 0, 0)),
        ],
    )
    # Part::Face names nothing (it keeps only the TopoDS shape); Part::Extrusion's faces go
    # through FaceMaker's names.
    extrusion = doc.addObject("Part::Extrusion", "Extrusion")
    extrusion.Base = faces
    extrusion.DirMode = "Custom"
    extrusion.Dir = V(0, 0, 1)
    extrusion.LengthFwd = 5
    extrusion.Solid = True
    return [faces, near, extrusion]


def modelPadPocket(doc):
    """Pad of a profile with a hole, and a Pocket through it (S5, S6)."""
    body = models.body(doc)
    profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10) + [models.circle(10, 5, 3)], body)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = profile
    pad.Length = 5
    cutter = models.sketch(doc, "Cutter", models.rectangle(2, 2, 5, 8), body, z=5)
    pocket = body.newObject("PartDesign::Pocket", "Pocket")
    pocket.Profile = cutter
    pocket.Type = "ThroughAll"
    return [pad, pocket]


def modelPadCollinear(doc):
    """Pad of a profile with two collinear edges: side faces compete for claims (S5)."""
    body = models.body(doc)
    profile = models.sketch(doc, "Profile", models.polygon([(0, 0), (10, 0), (20, 0), (20, 10), (0, 10)]), body)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = profile
    pad.Length = 5
    return [pad]


def modelCutSplit(doc):
    """A box cut in two by a thinner box: faces split into pieces (S2)."""
    box = models.box(doc, "Box", (10, 10, 10))
    slab = models.box(doc, "Slab", (2, 14, 14), at=(4, -2, -2))
    cut = doc.addObject("Part::Cut", "Cut")
    cut.Base, cut.Tool = box, slab
    return [cut]


def modelCompoundCut(doc):
    """A compound of two overlapping boxes cut by a cylinder on their shared corner: the two
    quarter faces of the cylinder's side lie at the same place, and OCCT's history reports only
    one of them (ops#25)."""
    first = models.box(doc, "First", (1, 2, 2))
    second = models.box(doc, "Second", (2, 1, 2))
    cylinder = doc.addObject("Part::Cylinder", "Cylinder")
    cylinder.Radius = 0.5
    cylinder.Height = 2
    compound = doc.addObject("Part::Compound", "Compound")
    compound.Links = [first, second]
    cut = doc.addObject("Part::Cut", "Cut")
    cut.Base, cut.Tool, cut.Refine = compound, cylinder, False
    return [cut]


def modelFuseCommon(doc):
    """Fuse and common of two overlapping boxes (S1, list fields)."""
    a = models.box(doc, "A", (10, 10, 10))
    b = models.box(doc, "B", (10, 10, 10), at=(5, 5, 5))
    fuse = doc.addObject("Part::Fuse", "Fuse")
    fuse.Base, fuse.Tool = a, b
    common = doc.addObject("Part::Common", "Common")
    common.Base, common.Tool = a, b
    return [fuse, common]


def modelFilletChamfer(doc):
    """Fillet and chamfer of a chain of three top edges of a box (UPP index, list fields)."""
    features = []
    for kind in ("Fillet", "Chamfer"):
        box = models.box(doc, kind + "Box", (10, 10, 10))
        doc.recompute()
        top = models.edgesWhere(box.Shape, lambda c: abs(c.z - 10) < 1e-6)
        chain = [i for i in top if box.Shape.Edges[i - 1].CenterOfMass.x > 1e-6]
        feature = doc.addObject("Part::" + kind, kind)
        feature.Base = box
        feature.Edges = [(i, 1.0, 1.0) for i in chain[:3]]
        features.append(feature)
    return features


def modelPipeShell(doc):
    """Pipe shell of a rectangle along a line: the end sections' edges (S4)."""
    profile = models.feature(doc, "Profile", models.closedWire([(0, 0, 0), (4, 0, 0), (4, 2, 0), (0, 2, 0)]))
    spine = models.feature(doc, "Spine", Part.makeLine(V(0, 0, 0), V(0, 0, 20)))
    sweep = doc.addObject("Part::Sweep", "Sweep")
    sweep.Sections = [profile]
    sweep.Spine = (spine, ["Edge1"])
    sweep.Solid = True
    return [sweep]


def modelLoftRevolve(doc):
    """Loft of two rectangles, and a 90 degree revolve of a rectangle (S1, S4)."""
    lower = models.feature(doc, "Lower", models.closedWire([(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)]))
    upper = models.feature(doc, "Upper", models.closedWire([(2, 1, 10), (8, 1, 10), (8, 4, 10), (2, 4, 10)]))
    loft = doc.addObject("Part::Loft", "Loft")
    loft.Sections = [lower, upper]
    loft.Solid = True
    rectangle = models.closedWire([(5, 0, 0), (10, 0, 0), (10, 0, 4), (5, 0, 4)])
    section = models.feature(doc, "Section", Part.Face(rectangle))
    revolve = doc.addObject("Part::Revolution", "Revolve")
    revolve.Source = section
    revolve.Axis = V(0, 0, 1)
    revolve.Base = V(0, 0, 0)
    revolve.Angle = 90
    revolve.Solid = True
    return [loft, revolve]


def modelSlice(doc):
    """Slices of an untagged cube (ops#46's case), and a Part::Section of a box by a plane (S3,
    S4)."""
    slices = models.feature(doc, "Slices", Part.makeBox(10, 10, 10).slices(V(0, 0, 1), [5.0]))
    box = models.box(doc, "Box", (10, 10, 10))
    plane = doc.addObject("Part::Plane", "Plane")
    plane.Length, plane.Width = 20, 20
    plane.Placement.Base = V(-5, -5, 5)
    section = doc.addObject("Part::Section", "Section")
    section.Base, section.Tool = box, plane
    return [slices, section]


def modelCompoundCopies(doc):
    """A compound of a fuse and a copy of its shape: the copy's names are duplicates."""
    a = models.box(doc, "A", (10, 10, 10))
    b = models.box(doc, "B", (10, 10, 10), at=(5, 5, 5))
    fuse = doc.addObject("Part::Fuse", "Fuse")
    fuse.Base, fuse.Tool = a, b
    doc.recompute()
    copyShape = fuse.Shape.copy()
    copyShape.translate(V(30, 0, 0))
    copy = models.feature(doc, "Copy", copyShape)
    compound = doc.addObject("Part::Compound", "Compound")
    compound.Links = [fuse, copy]
    return [compound]


def modelRefine(doc):
    """Two Pads side by side, the second refined: coplanar faces merge (several names per
    element)."""
    body = models.body(doc)
    first = models.sketch(doc, "First", models.rectangle(0, 0, 10, 10), body)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = first
    pad.Length = 5
    second = models.sketch(doc, "Second", models.rectangle(10, 0, 20, 10), body)
    pad2 = body.newObject("PartDesign::Pad", "Pad2")
    pad2.Profile = second
    pad2.Length = 5
    pad2.Refine = True
    return [pad2]


def modelLinearPattern(doc):
    """A LinearPattern of a Pad with overlapping copies (duplicate counts, S5)."""
    body = models.body(doc)
    profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 8, 4), body)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = profile
    pad.Length = 4
    pattern = body.newObject("PartDesign::LinearPattern", "LinearPattern")
    pattern.Originals = [pad]
    pattern.Direction = (models.originFeature(body, "X_Axis"), [""])
    pattern.Length = 10
    pattern.Occurrences = 3
    pattern.Refine = False
    return [pad, pattern]


def modelPatternSteps(doc):
    """Two-step patterns of a Pad with overlapping copies: a MultiTransform of LinX (3) then
    LinY (2), and a LinearPattern with a second direction (3 x 2): the numbers in their
    instances' TRF sections (ops#6)."""

    def linear(body, name, axis, offset, occurrences):
        pattern = doc.addObject("PartDesign::LinearPattern", name)
        pattern.Direction = (models.originFeature(body, axis), [""])
        pattern.Mode = "Spacing"
        pattern.Offset = offset
        pattern.Occurrences = occurrences
        return pattern

    body = models.body(doc)
    profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 8, 4), body)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = profile
    pad.Length = 4
    multi = doc.addObject("PartDesign::MultiTransform", "MultiTransform")
    multi.Originals = [pad]
    multi.Refine = False
    body.addObject(multi)
    linX = linear(body, "LinX", "X_Axis", 5, 3)
    linY = linear(body, "LinY", "Y_Axis", 3, 2)
    body.addObject(linX)
    body.addObject(linY)
    multi.Transformations = [linX, linY]

    body2 = doc.addObject("PartDesign::Body", "Body2")
    profile2 = models.sketch(doc, "Profile2", models.rectangle(0, 0, 8, 4), body2)
    pad2 = body2.newObject("PartDesign::Pad", "Pad2")
    pad2.Profile = profile2
    pad2.Length = 4
    pattern = linear(body2, "LinearPattern", "X_Axis", 5, 3)
    pattern.Originals = [pad2]
    pattern.Direction2 = (models.originFeature(body2, "Y_Axis"), [""])
    pattern.Mode2 = "Spacing"
    pattern.Spacings2 = []  # a new pattern's is [0.0], a gap of 0 (ops#93)
    pattern.Offset2 = 3
    pattern.Occurrences2 = 2
    pattern.Refine = False
    body2.addObject(pattern)
    return [multi, pattern]


def modelOffsetThickness(doc):
    """Offset and Thickness of a box (list fields)."""
    box = models.box(doc, "Box", (10, 10, 10))
    offset = doc.addObject("Part::Offset", "Offset")
    offset.Source = box
    offset.Value = 1
    shellBox = models.box(doc, "ShellBox", (10, 10, 10), at=(20, 0, 0))
    doc.recompute()
    top = [
        i + 1 for i, face in enumerate(shellBox.Shape.Faces) if abs(face.CenterOfMass.z - 10) < 1e-6
    ]
    thickness = doc.addObject("Part::Thickness", "Thickness")
    thickness.Faces = (shellBox, [f"Face{top[0]}"])
    thickness.Value = 1
    return [offset, thickness]


def modelOffsetSplitCylinder(doc):
    """Offset of a cylinder whose side is two half-cylinder faces (ops#49). The two faces meet at
    two tangent lines, which Join=Arc keeps, so the lines are named after the same two faces and
    told apart only by their index; the circles get arc faces, whose order OCCT varies between
    runs. (Thickness takes the same path, makeElementThickSolid; it isn't here because its face
    reference into the extrusion goes missing in TestNamingLoadNewerFormat, as designed.)"""
    circle = Part.Circle(V(0, 0, 0), V(0, 0, 1), 5)
    arcs = [Part.ArcOfCircle(circle, a, a + math.pi) for a in (0, math.pi)]
    profile = models.sketch(doc, "Profile", arcs)
    cylinder = doc.addObject("Part::Extrusion", "Cylinder")
    cylinder.Base = profile
    cylinder.DirMode = "Custom"
    cylinder.Dir = V(0, 0, 1)
    cylinder.LengthFwd = 10
    cylinder.Solid = True
    offset = doc.addObject("Part::Offset", "Offset")
    offset.Source = cylinder
    offset.Value = 1
    return [offset]


MODELS = {
    "Sketch": modelSketch,
    "PadPocket": modelPadPocket,
    "PadCollinear": modelPadCollinear,
    "CutSplit": modelCutSplit,
    "CompoundCut": modelCompoundCut,
    "FuseCommon": modelFuseCommon,
    "FilletChamfer": modelFilletChamfer,
    "PipeShell": modelPipeShell,
    "LoftRevolve": modelLoftRevolve,
    "Slice": modelSlice,
    "CompoundCopies": modelCompoundCopies,
    "Refine": modelRefine,
    "LinearPattern": modelLinearPattern,
    "PatternSteps": modelPatternSteps,
    "OffsetThickness": modelOffsetThickness,
    "OffsetSplitCylinder": modelOffsetSplitCylinder,
}

# ---------------------------------------------------------------------------------------------
# The dump
# ---------------------------------------------------------------------------------------------


def _number(value):
    text = f"{value:.4f}"
    return "0.0000" if text == "-0.0000" else text


def _elementKey(kind, element):
    if kind == "Vertex":
        point, mass = element.Point, 0.0
    else:
        try:
            point = element.CenterOfMass
        except Exception:
            box = element.BoundBox
            point = V(box.Center)
        mass = element.Area if kind == "Face" else element.Length
    coords = ",".join(_number(c) for c in (point.x, point.y, point.z))
    return f"{kind} c=({coords}) m={_number(mass)}"


def _algorithm(mode):
    """The document's HistoryAlgorithm in a mode: V2i is V2 with InternNames on."""
    return "V2" if mode == "V2i" else mode


def dumpShape(shape, masker, mode, indexed=False):
    """The shape's elements and names as sorted lines. V2i names are expanded first. Without a
    masker, the names are written as they are."""
    table = {}
    if mode == "V1" and shape.Hasher is not None:
        try:
            table = dict(shape.Hasher.Table)
        except Exception:
            table = {}
    reverse = shape.ElementReverseMap
    lines = []
    kinds = (("Face", shape.Faces), ("Edge", shape.Edges), ("Vertex", shape.Vertexes))
    for kind, elements in kinds:
        for index, element in enumerate(elements, 1):
            key = _elementKey(kind, element)
            if indexed:
                key = f"{kind}{index} {key}"
            names = reverse.get(f"{kind}{index}")
            if names is None:
                names = []
            elif isinstance(names, str):
                names = [names]
            if not names:
                lines.append(f"{key} : -")
            for name in names:
                if mode == "V2i":
                    name = App.expandMappedName(name)
                if masker is None:
                    masked = name
                elif mode == "V1":
                    masked = masker.maskV1(name, table)
                else:
                    masked = masker.maskV2(name)
                lines.append(f"{key} : {masked}")
    return sorted(lines)


def _setMode(doc, mode):
    doc.HistoryAlgorithm = _algorithm(mode)
    # Explicitly, also when off: FREECAD_INTERN_NAMES=1 turns it on in new documents.
    doc.InternNames = mode == "V2i"


def _dumpFeatures(model, features, masker, mode, indexed=False):
    """The dump of the model's features. Its header names the algorithm, so that a V2i dump can
    equal the V2 one."""
    out = [f"# {model} {_algorithm(mode)}"]
    for feature in features:
        shape = feature.Shape
        errors = [] if feature.isValid() else [" INVALID"]
        out.append(
            f"[{feature.Name} {feature.TypeId}{''.join(errors)}] "
            f"faces={len(shape.Faces)} edges={len(shape.Edges)} "
            f"vertexes={len(shape.Vertexes)} names={shape.ElementMapSize}"
        )
        out.extend(dumpShape(shape, masker, mode, indexed))
    return "\n".join(out) + "\n"


def dumpModel(model, mode, indexed=False):
    """Builds the model in a new document in `mode` and returns its dump as text."""
    doc = models.newDocument(f"NamingDump{model}{mode}")
    try:
        _setMode(doc, mode)
        features = MODELS[model](doc)
        doc.recompute()
        return _dumpFeatures(model, features, Masker(doc), mode, indexed)
    finally:
        App.closeDocument(doc.Name)


def _dumpDir():
    path = os.environ.get("FREECAD_NAMING_DUMP_DIR") or tempfile.gettempdir()
    os.makedirs(path, exist_ok=True)
    return path


def _diff(expected, actual, fromName, toName, limit=60):
    lines = list(
        difflib.unified_diff(
            expected.splitlines(), actual.splitlines(), fromName, toName, lineterm="", n=1
        )
    )
    more = f"\n... {len(lines) - limit} more lines" if len(lines) > limit else ""
    return "\n".join(lines[:limit]) + more


def _save(model, mode, label, text):
    path = os.path.join(_dumpDir(), f"naming-dump.{model}.{mode}.{label}.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------------------------
# Child processes (TestNamingSeeded)
# ---------------------------------------------------------------------------------------------


def childMain(outPath):
    """Dumps every model in both modes into a JSON file. Run in a child process."""
    result = {}
    for model in MODELS:
        for mode in MODES:
            try:
                result[f"{model}.{mode}"] = dumpModel(model, mode)
            except Exception as e:
                result[f"{model}.{mode}"] = f"ERROR {type(e).__name__}: {e}\n"
    with open(outPath, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=0, sort_keys=True)


CHILD_SCRIPT = """\
import os, traceback
try:
    from PartDesignTests import TestNamingDump
    TestNamingDump.childMain(os.environ["FREECAD_NAMING_CHILD_OUT"])
except Exception:
    with open(os.environ["FREECAD_NAMING_CHILD_OUT"] + ".error", "w") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
"""


def _freecadCmd():
    names = ("FreeCADCmd.exe", "FreeCADCmd") if sys.platform == "win32" else ("FreeCADCmd",)
    base = os.path.basename(sys.executable).lower()
    if base.startswith("freecadcmd"):
        return sys.executable
    for folder in ("bin", "MacOS", ""):
        for name in names:
            path = os.path.join(App.getHomePath(), folder, name)
            if os.path.isfile(path):
                return path
    raise FileNotFoundError("FreeCADCmd next to " + App.getHomePath())


_childDumps = None


def childDumps():
    """{label: {"<model>.<mode>": dump}} for the unseeded child and one child per seed. Runs the
    children once per process, in parallel."""
    global _childDumps
    if _childDumps is not None:
        return _childDumps
    workDir = tempfile.mkdtemp(prefix="naming-dump-")
    script = os.path.join(workDir, "child.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(CHILD_SCRIPT)
    exe = _freecadCmd()
    runs = {}
    for label, seed in [("unseeded", None)] + [(f"seed{s}", s) for s in SEEDS]:
        env = dict(os.environ)
        env.pop("FREECAD_NAMING_HASH_SEED", None)
        if seed:
            env["FREECAD_NAMING_HASH_SEED"] = seed
        out = os.path.join(workDir, label + ".json")
        env["FREECAD_NAMING_CHILD_OUT"] = out
        log = open(os.path.join(workDir, label + ".log"), "w")
        proc = subprocess.Popen(
            [exe, script], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=workDir
        )
        runs[label] = (proc, out, log)
    _childDumps = {}
    for label, (proc, out, log) in runs.items():
        try:
            proc.wait(timeout=900)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        if os.path.isfile(out):
            with open(out, encoding="utf-8") as fh:
                _childDumps[label] = json.load(fh)
        else:
            error = out + ".error"
            reason = open(error).read() if os.path.isfile(error) else f"no output ({workDir})"
            _childDumps[label] = {"ERROR": reason}
    return _childDumps


# ---------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------


class TestNamingGolden(unittest.TestCase):
    """The dump equals the golden file generated on Windows."""

    def check(self, model, mode):
        actual = dumpModel(model, mode)
        fileName = f"{model}.{_algorithm(mode)}.txt"  # V2i expands to V2: no file of its own
        update = os.environ.get("FREECAD_NAMING_GOLDEN_UPDATE")
        if update:
            if mode != "V2i":
                path = os.path.join(update, fileName)
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(actual)
            return
        with open(os.path.join(GOLDEN_DIR, fileName), encoding="utf-8") as fh:
            expected = fh.read().replace("\r\n", "\n")
        if actual != expected:
            path = _save(model, mode, "actual", dumpModel(model, mode, indexed=True))
            self.fail(
                f"names differ from {fileName} (full dump with indexes: {path}):\n"
                + _diff(expected, actual, "golden", "actual")
            )


class TestNamingSeeded(unittest.TestCase):
    """Seeding the naming code's hash containers doesn't change the names."""

    def check(self, model, mode):
        dumps = childDumps()
        key = f"{model}.{mode}"
        base = dumps["unseeded"].get(key, dumps["unseeded"].get("ERROR", "missing"))
        self.assertFalse(base.startswith("ERROR"), base)
        messages = []
        for seed in SEEDS:
            label = f"seed{seed}"
            seeded = dumps[label].get(key, dumps[label].get("ERROR", "missing"))
            if seeded != base:
                path = _save(model, mode, label, seeded)
                messages.append(
                    f"FREECAD_NAMING_HASH_SEED={seed} changes the names ({path}):\n"
                    + _diff(base, seeded, "unseeded", label, limit=30)
                )
        if messages:
            _save(model, mode, "unseeded", base)
            self.fail("\n".join(messages))


class TestNamingRepeated(unittest.TestCase):
    """Building the model again in the same process gives the same names at the same indexes
    (OCCT's parallel booleans, pointer-keyed containers)."""

    def check(self, model, mode):
        first = dumpModel(model, mode, indexed=True)
        for run in range(2, REPEATS + 1):
            again = dumpModel(model, mode, indexed=True)
            if again != first:
                path1 = _save(model, mode, "run1", first)
                path = _save(model, mode, f"run{run}", again)
                self.fail(
                    f"run {run} of {REPEATS} differs from run 1 ({path1}, {path}):\n"
                    + _diff(first, again, "run1", f"run{run}")
                )


class TestNamingInterning(unittest.TestCase):
    """Interning changes no byte of a name (ops#6, Task 1). The model is built in two documents
    whose object IDs start at 0 (`clearDocument`), so their tags are equal and nothing is masked:
    one plain, one with InternNames on. The interned names must expand to the plain names, element
    by element (keyed index-free, ops#49), and equal `NamingGolden/<Model>.V2i-ids.txt` as they
    are, which fixes the IDs on every platform."""

    def build(self, model, mode):
        doc = App.newDocument(f"NamingInterning{model}{mode}")
        doc.clearDocument()
        _setMode(doc, mode)
        features = MODELS[model](doc)
        doc.recompute()
        return doc, features

    def check(self, model):
        plainDoc, plainFeatures = self.build(model, "V2")
        try:
            plain = _dumpFeatures(model, plainFeatures, None, "V2")
        finally:
            App.closeDocument(plainDoc.Name)
        internedDoc, internedFeatures = self.build(model, "V2i")
        try:
            expanded = _dumpFeatures(model, internedFeatures, None, "V2i")
            interned = _dumpFeatures(model, internedFeatures, None, "V2")
        finally:
            App.closeDocument(internedDoc.Name)

        if expanded != plain:
            _save(model, "V2", "plain", plain)
            path = _save(model, "V2i", "expanded", expanded)
            self.fail(
                f"interned names don't expand to the plain ones ({path}):\n"
                + _diff(plain, expanded, "plain", "expanded")
            )
        # The interned form: escapes only stand for embedded names, which are references now
        self.assertNotIn("^", interned)
        if "^" in plain:
            self.assertIn("~", interned)

        fileName = f"{model}.V2i-ids.txt"
        update = os.environ.get("FREECAD_NAMING_GOLDEN_UPDATE")
        if update:
            with open(os.path.join(update, fileName), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(interned)
            return
        with open(os.path.join(GOLDEN_DIR, fileName), encoding="utf-8") as fh:
            expected = fh.read().replace("\r\n", "\n")
        if interned != expected:
            path = _save(model, "V2i", "ids", interned)
            self.fail(
                f"interned names differ from {fileName} ({path}):\n"
                + _diff(expected, interned, "golden", "actual")
            )


class TestNamingTagCollision(unittest.TestCase):
    """A document whose object IDs start at 0 gives the Slice model's first object, Slices, the
    ID 1: the slice's own tag, which `Masker` then writes as `{Slices}` instead of `#1` (ops#52).
    `Document.clearDocument` restarts the IDs at 0, which forces the case."""

    def testCollisionForced(self):
        """Control: in a document starting at 0, the slice tag is masked as Slices"""
        doc = App.newDocument("NamingDumpCollision")
        try:
            doc.clearDocument()
            doc.HistoryAlgorithm = "V2"
            slices = MODELS["Slice"](doc)[0]
            doc.recompute()
            self.assertEqual(slices.ID, 1)
            text = "\n".join(dumpShape(slices.Shape, Masker(doc), "V2"))
            self.assertIn(";{Slices};SLC;", text)
            self.assertNotIn(";#1;SLC;", text)
        finally:
            App.closeDocument(doc.Name)

    def testNewDocumentAvoidsCollision(self):
        """The dump turns down a document starting at 0 and matches the golden file"""
        create, made = App.newDocument, []

        def newDocument(*args, **kwargs):
            doc = create(*args, **kwargs)
            if not made:
                doc.clearDocument()
            made.append(doc.Name)
            return doc

        with unittest.mock.patch.object(App, "newDocument", newDocument):
            actual = dumpModel("Slice", "V2")
        self.assertGreaterEqual(len(made), 2, "the document starting at 0 was used")
        with open(os.path.join(GOLDEN_DIR, "Slice.V2.txt"), encoding="utf-8") as fh:
            expected = fh.read().replace("\r\n", "\n")
        self.assertEqual(actual, expected)


def _addTests():
    for cls in (TestNamingGolden, TestNamingSeeded, TestNamingRepeated):
        for model in MODELS:
            for mode in MODES:

                def test(self, model=model, mode=mode):
                    self.check(model, mode)

                test.__name__ = f"test{model}{mode}"
                test.__doc__ = f"{MODELS[model].__doc__.split('.')[0]} ({mode})"
                setattr(cls, test.__name__, test)
    for model in MODELS:

        def test(self, model=model):
            self.check(model)

        test.__name__ = f"test{model}"
        test.__doc__ = f"{MODELS[model].__doc__.split('.')[0]} (V2 and V2i)"
        setattr(TestNamingInterning, test.__name__, test)


_addTests()
