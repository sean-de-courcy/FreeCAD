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
for pointer keys, between runs, or when OCCT's own result order varies (parallel booleans).

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

Environment variables:
- FREECAD_NAMING_GOLDEN_UPDATE=<dir>: TestNamingGolden writes the golden files into <dir> (the
  source tree's NamingGolden folder) instead of comparing.
- FREECAD_NAMING_DUMP_DIR=<dir>: where a failing test writes its dumps (default: the temp dir).
"""

import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

import FreeCAD as App
import Part

V = App.Vector

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NamingGolden")
MODES = ("V1", "V2")
REPEATS = 5
SEEDS = ("0x5eed0001", "0x9e3779b97f4a7c15")

# ---------------------------------------------------------------------------------------------
# Models. Each builds its objects in `doc` and returns the features whose shapes are dumped.
# ---------------------------------------------------------------------------------------------


def _body(doc):
    body = doc.addObject("PartDesign::Body", "Body")
    return body


def _originFeature(body, role):
    for feature in body.Origin.OriginFeatures:
        if feature.Role == role:
            return feature
    raise ValueError(role)


def _sketch(doc, name, geometry, body=None, z=0.0):
    sketch = doc.addObject("Sketcher::SketchObject", name)
    if body is not None:
        body.addObject(sketch)
    sketch.Placement = App.Placement(V(0, 0, z), App.Rotation())
    sketch.addGeometry(geometry, False)
    return sketch


def _polygon(points):
    """Line segments through the points, closed."""
    return [
        Part.LineSegment(V(*points[i], 0), V(*points[(i + 1) % len(points)], 0))
        for i in range(len(points))
    ]


def _rectangle(x0, y0, x1, y1):
    return _polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _circle(x, y, r):
    return Part.Circle(V(x, y, 0), V(0, 0, 1), r)


def _closedWire(points):
    """A closed polygon through the 3D points."""
    return Part.makePolygon([V(*p) for p in points + [points[0]]])


def _feature(doc, name, shape):
    feature = doc.addObject("Part::Feature", name)
    feature.Shape = shape
    return feature


def _box(doc, name, size, at=(0, 0, 0)):
    box = doc.addObject("Part::Box", name)
    box.Length, box.Width, box.Height = size
    box.Placement.Base = V(*at)
    return box


def _edgesWhere(shape, test):
    """1-based indexes of the edges whose centre passes `test`, in index order."""
    return [i + 1 for i, edge in enumerate(shape.Edges) if test(edge.CenterOfMass)]


def modelSketch(doc):
    """Sketch vertex Reference IDs (S7), with line ends that meet within Confusion but not
    exactly, and FaceMaker's face names in an extrusion of two faces (S6)."""
    faces = _sketch(
        doc,
        "Faces",
        _rectangle(0, 0, 20, 10) + [_circle(10, 5, 3)] + _rectangle(30, 0, 40, 10),
    )
    near = _sketch(
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
    body = _body(doc)
    profile = _sketch(doc, "Profile", _rectangle(0, 0, 20, 10) + [_circle(10, 5, 3)], body)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = profile
    pad.Length = 5
    cutter = _sketch(doc, "Cutter", _rectangle(2, 2, 5, 8), body, z=5)
    pocket = body.newObject("PartDesign::Pocket", "Pocket")
    pocket.Profile = cutter
    pocket.Type = "ThroughAll"
    return [pad, pocket]


def modelPadCollinear(doc):
    """Pad of a profile with two collinear edges: side faces compete for claims (S5)."""
    body = _body(doc)
    profile = _sketch(doc, "Profile", _polygon([(0, 0), (10, 0), (20, 0), (20, 10), (0, 10)]), body)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = profile
    pad.Length = 5
    return [pad]


def modelCutSplit(doc):
    """A box cut in two by a thinner box: faces split into pieces (S2)."""
    box = _box(doc, "Box", (10, 10, 10))
    slab = _box(doc, "Slab", (2, 14, 14), at=(4, -2, -2))
    cut = doc.addObject("Part::Cut", "Cut")
    cut.Base, cut.Tool = box, slab
    return [cut]


def modelFuseCommon(doc):
    """Fuse and common of two overlapping boxes (S1, list fields)."""
    a = _box(doc, "A", (10, 10, 10))
    b = _box(doc, "B", (10, 10, 10), at=(5, 5, 5))
    fuse = doc.addObject("Part::Fuse", "Fuse")
    fuse.Base, fuse.Tool = a, b
    common = doc.addObject("Part::Common", "Common")
    common.Base, common.Tool = a, b
    return [fuse, common]


def modelFilletChamfer(doc):
    """Fillet and chamfer of a chain of three top edges of a box (UPP index, list fields)."""
    features = []
    for kind in ("Fillet", "Chamfer"):
        box = _box(doc, kind + "Box", (10, 10, 10))
        doc.recompute()
        top = _edgesWhere(box.Shape, lambda c: abs(c.z - 10) < 1e-6)
        chain = [i for i in top if box.Shape.Edges[i - 1].CenterOfMass.x > 1e-6]
        feature = doc.addObject("Part::" + kind, kind)
        feature.Base = box
        feature.Edges = [(i, 1.0, 1.0) for i in chain[:3]]
        features.append(feature)
    return features


def modelPipeShell(doc):
    """Pipe shell of a rectangle along a line: the end sections' edges (S4)."""
    profile = _feature(doc, "Profile", _closedWire([(0, 0, 0), (4, 0, 0), (4, 2, 0), (0, 2, 0)]))
    spine = _feature(doc, "Spine", Part.makeLine(V(0, 0, 0), V(0, 0, 20)))
    sweep = doc.addObject("Part::Sweep", "Sweep")
    sweep.Sections = [profile]
    sweep.Spine = (spine, ["Edge1"])
    sweep.Solid = True
    return [sweep]


def modelLoftRevolve(doc):
    """Loft of two rectangles, and a 90 degree revolve of a rectangle (S1, S4)."""
    lower = _feature(doc, "Lower", _closedWire([(0, 0, 0), (10, 0, 0), (10, 6, 0), (0, 6, 0)]))
    upper = _feature(doc, "Upper", _closedWire([(2, 1, 10), (8, 1, 10), (8, 4, 10), (2, 4, 10)]))
    loft = doc.addObject("Part::Loft", "Loft")
    loft.Sections = [lower, upper]
    loft.Solid = True
    rectangle = _closedWire([(5, 0, 0), (10, 0, 0), (10, 0, 4), (5, 0, 4)])
    section = _feature(doc, "Section", Part.Face(rectangle))
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
    slices = _feature(doc, "Slices", Part.makeBox(10, 10, 10).slices(V(0, 0, 1), [5.0]))
    box = _box(doc, "Box", (10, 10, 10))
    plane = doc.addObject("Part::Plane", "Plane")
    plane.Length, plane.Width = 20, 20
    plane.Placement.Base = V(-5, -5, 5)
    section = doc.addObject("Part::Section", "Section")
    section.Base, section.Tool = box, plane
    return [slices, section]


def modelCompoundCopies(doc):
    """A compound of a fuse and a copy of its shape: the copy's names are duplicates."""
    a = _box(doc, "A", (10, 10, 10))
    b = _box(doc, "B", (10, 10, 10), at=(5, 5, 5))
    fuse = doc.addObject("Part::Fuse", "Fuse")
    fuse.Base, fuse.Tool = a, b
    doc.recompute()
    copyShape = fuse.Shape.copy()
    copyShape.translate(V(30, 0, 0))
    copy = _feature(doc, "Copy", copyShape)
    compound = doc.addObject("Part::Compound", "Compound")
    compound.Links = [fuse, copy]
    return [compound]


def modelRefine(doc):
    """Two Pads side by side, the second refined: coplanar faces merge (several names per
    element)."""
    body = _body(doc)
    first = _sketch(doc, "First", _rectangle(0, 0, 10, 10), body)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = first
    pad.Length = 5
    second = _sketch(doc, "Second", _rectangle(10, 0, 20, 10), body)
    pad2 = body.newObject("PartDesign::Pad", "Pad2")
    pad2.Profile = second
    pad2.Length = 5
    pad2.Refine = True
    return [pad2]


def modelLinearPattern(doc):
    """A LinearPattern of a Pad with overlapping copies (duplicate counts, S5)."""
    body = _body(doc)
    profile = _sketch(doc, "Profile", _rectangle(0, 0, 8, 4), body)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = profile
    pad.Length = 4
    pattern = body.newObject("PartDesign::LinearPattern", "LinearPattern")
    pattern.Originals = [pad]
    pattern.Direction = (_originFeature(body, "X_Axis"), [""])
    pattern.Length = 10
    pattern.Occurrences = 3
    pattern.Refine = False
    return [pad, pattern]


def modelOffsetThickness(doc):
    """Offset and Thickness of a box (list fields)."""
    box = _box(doc, "Box", (10, 10, 10))
    offset = doc.addObject("Part::Offset", "Offset")
    offset.Source = box
    offset.Value = 1
    shellBox = _box(doc, "ShellBox", (10, 10, 10), at=(20, 0, 0))
    doc.recompute()
    top = [
        i + 1 for i, face in enumerate(shellBox.Shape.Faces) if abs(face.CenterOfMass.z - 10) < 1e-6
    ]
    thickness = doc.addObject("Part::Thickness", "Thickness")
    thickness.Faces = (shellBox, [f"Face{top[0]}"])
    thickness.Value = 1
    return [offset, thickness]


MODELS = {
    "Sketch": modelSketch,
    "PadPocket": modelPadPocket,
    "PadCollinear": modelPadCollinear,
    "CutSplit": modelCutSplit,
    "FuseCommon": modelFuseCommon,
    "FilletChamfer": modelFilletChamfer,
    "PipeShell": modelPipeShell,
    "LoftRevolve": modelLoftRevolve,
    "Slice": modelSlice,
    "CompoundCopies": modelCompoundCopies,
    "Refine": modelRefine,
    "LinearPattern": modelLinearPattern,
    "OffsetThickness": modelOffsetThickness,
}

# ---------------------------------------------------------------------------------------------
# The dump
# ---------------------------------------------------------------------------------------------


class MaskError(Exception):
    pass


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


class Masker:
    """Replaces the tags (object IDs) in element names with `{ObjectName}`.

    V2: each section's tag is replaced, recursing into Linked and Connected Names; the name is
    decoded and encoded again, and must come back byte for byte with the tags left as they are.
    V1: the `:H<hex>` tags are replaced, after expanding the hasher's `#<hex>` string IDs. The
    length after a tag (`:H<hex>:<hex length>`) counts the characters of the name before it, tags
    included, so it depends on the tags' values: it is written `:L`.
    A tag that is no object's ID is written `#<tag>` (e.g. a slice's number), a negative object ID
    `{-ObjectName}`; 0 stays 0.
    """

    V1_TAG = re.compile(r":H(-?)([0-9a-f]*)(:[0-9a-f]+)?")
    V1_SID = re.compile(r"#([0-9a-f]+)")

    def __init__(self, doc):
        self.names = {str(obj.ID): obj.Name for obj in doc.Objects}

    def tag(self, tag):
        if tag in ("", "0"):
            return tag
        sign = "-" if tag.startswith("-") else ""  # e.g. a Pocket's tool, tagged -ID
        name = self.names.get(tag.lstrip("-"))
        return "{" + sign + name + "}" if name else "#" + tag

    def v2(self, name, mask=True):
        sections = App.getDecodedMappedName(name)
        if not sections:
            return name
        encoded = []
        for section in sections:
            section = dict(section)
            for field in ("linkedNames", "connectedElements"):
                names = [self.v2(n, mask) for n in section[field]]
                # sorted by bytes with the tags; with the tags masked, sorted again
                section[field] = sorted(names) if mask else names
            if mask:
                section["iterationTag"] = self.tag(section["iterationTag"])
            encoded.append(App.makeEncodedSection(**section))
        return "|".join(encoded)  # Data::NAME_SECTION_DELIMINATOR

    @classmethod
    def unsortedList(cls, name):
        """A Linked or Connected Names list in the name that isn't sorted by bytes and unique."""
        for section in App.getDecodedMappedName(name) or []:
            for field in ("linkedNames", "connectedElements"):
                names = list(section[field])
                if names != sorted(set(names)):
                    return names
                for linked in names:
                    found = cls.unsortedList(linked)
                    if found:
                        return found
        return None

    def maskV2(self, name):
        if self.v2(name, mask=False) != name:
            raise MaskError(f"decoding and encoding changes the name {name!r}")
        unsorted = self.unsortedList(name)
        if unsorted:
            raise MaskError(f"a list in {name!r} isn't sorted by bytes (ops#19): {unsorted!r}")
        return self.v2(name)

    def maskV1(self, name, table):
        if table:
            for _ in range(20):
                expanded = self.V1_SID.sub(
                    lambda m: "<" + str(table.get(int(m.group(1), 16), m.group(0))) + ">", name
                )
                if expanded == name:
                    break
                name = expanded
        def tag(match):
            value = match.group(2)
            if value:
                value = self.tag(str(int(value, 16) * (-1 if match.group(1) else 1)))
            return ":H" + value + (":L" if match.group(3) else "")

        return self.V1_TAG.sub(tag, name)


def dumpShape(shape, masker, mode, indexed=False):
    """The shape's elements and names as sorted lines."""
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
                if mode == "V2":
                    masked = masker.maskV2(name)
                else:
                    masked = masker.maskV1(name, table)
                lines.append(f"{key} : {masked}")
    return sorted(lines)


def dumpModel(model, mode, indexed=False):
    """Builds the model in a new document in `mode` and returns its dump as text."""
    doc = App.newDocument(f"NamingDump{model}{mode}")
    try:
        doc.HistoryAlgorithm = mode
        features = MODELS[model](doc)
        doc.recompute()
        masker = Masker(doc)
        out = [f"# {model} {mode}"]
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
        fileName = f"{model}.{mode}.txt"
        update = os.environ.get("FREECAD_NAMING_GOLDEN_UPDATE")
        if update:
            with open(os.path.join(update, fileName), "w", encoding="utf-8", newline="\n") as fh:
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


def _addTests():
    for cls in (TestNamingGolden, TestNamingSeeded, TestNamingRepeated):
        for model in MODELS:
            for mode in MODES:

                def test(self, model=model, mode=mode):
                    self.check(model, mode)

                test.__name__ = f"test{model}{mode}"
                test.__doc__ = f"{MODELS[model].__doc__.split('.')[0]} ({mode})"
                setattr(cls, test.__name__, test)


_addTests()
