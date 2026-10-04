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

"""Loading files with interned names when the process disagrees with them (ops#6, Task 1 PR 8).

A file's references (`~<ID>`) mean what its own name table says. These tests open files, each in
a child `FreeCADCmd` of its own, where an ID means something else or the file lacks it:

- TestNamingLoadCollision: the child holds other content under one of the file's IDs (forced
  with `App.insertNameTableEntryForTesting`) before it opens the file: the names expand as the
  file meant them, none refers to the colliding ID, and after a recompute they still do; a new
  save holds no colliding ID. The same with every ID of every file colliding, also for a merge
  (`Document.importObjects`) and for the cross-document scenarios, which must still judge
  correct after the reopen and as an in-process run after the edit. Two cases on their own
  (ops#97): one ID that a model's map holds both as a name's prefix and embedded in another name,
  linked by those two names from the same file, so a load inlines it both ways (the escape rule
  of NameRemap::remapText); and, in each mixed cross-document scenario with A plain and B
  interned, one of B's IDs that only A's shadows carry in A's file.
- TestNamingLoadUnknown: the file's table lacks one entry, which the child knows with its real
  content: the references to it (and to the entries above it) are made unresolvable (`~!<ID>`)
  instead of resolving to the child's entry, with a warning; a recompute names everything again.
  In a cross-document scenario, no reference resolves wrong. (The entry is taken out of the
  table and the later ones renumbered; the references to it take the hash form, which a map
  may hold too.)
- TestNamingLoadNewerFormat: the file's `NamingFormat` is raised by hand: one warning, the maps
  with interned names are dropped and their objects recomputed, and the references go missing;
  a recompute names everything again. The same for a merge (`Document.mergeProject`) into an
  interned document (ops#97).
- TestNamingLoadProxy: a Python proxy whose state holds an interned subname. The state is saved
  base64-encoded, out of the save's scan, so the proxy gives it to the collector itself: the file
  holds its entries, and a load with them colliding remaps it after decoding.
- TestNamingLoadElementReference: an object in A references a fillet face of B whose name holds
  a reference (the ElementReferenceTest pattern, ops#18/#40), V2i. Opened with B closed, the
  reference names that face; with B's file absent, A's own table resolves its shadows, and a new
  save of A writes them unchanged.
"""

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import traceback
import unittest
import zipfile

import FreeCAD as App

from PartDesignTests import TestNamingDump as dump
from PartDesignTests import TestNamingSave as save
from PartDesignTests.Scenarios import crossdoc, models

__all__ = [
    "TestNamingLoadCollision",
    "TestNamingLoadUnknown",
    "TestNamingLoadNewerFormat",
    "TestNamingLoadProxy",
    "TestNamingLoadElementReference",
]

BOGUS = "Collision;_;1;XYZ;0;F;0;_;_"
UNKNOWN = re.compile(r"~!([0-9a-v]{13})")
NEWER_WARNING = "which this build doesn't read"
UNKNOWN_WARNING = "missing from the file's name table"


def rewriteFile(source, target, rewrite):
    """Copies the zip `source` to `target` with Document.xml and the map files passed through
    `rewrite(name, text)`."""
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Document.xml" or item.filename.endswith(".Map.txt"):
                data = rewrite(item.filename, data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)


def newerFormat(name, text):
    """A rewrite for rewriteFile: Document.xml's NamingFormat raised by one."""
    if name != "Document.xml":
        return text
    old = f'NamingFormat="{save.FORMAT}"'
    if old not in text:
        raise AssertionError(f"no {old}")
    return text.replace(old, f'NamingFormat="{save.FORMAT + 1}"', 1)


def withoutEntry(ids, id):
    """A rewrite for rewriteFile: the file without its table's entry `id`, whose IDs by index are
    `ids`. The later entries move up a line, so every index above it goes down by one, and the
    references to it (indices in the maps and the table) take the hash form, which the table no
    longer has."""
    removed = ids.index(id)

    def renumber(text):
        def replace(match):
            n = int(match.group(1))
            if n == removed:
                return "~" + id
            return f"~{n - 1}" if n > removed else match.group(0)

        return save.INDEX.sub(replace, text)

    def rewrite(name, text):
        if name != "Document.xml":
            return renumber(text)
        match = save.TABLE.search(text)
        _, contents = save.fileTable({"Document.xml": text})
        kept = [renumber(c) for i, c in enumerate(contents) if i != removed]
        body = match.group(3)
        lead, trail = body[: len(body) - len(body.lstrip())], body[len(body.rstrip()) :]
        body = lead + "\n".join([f"NameTableStart v2 {len(kept)}"] + kept) + trail
        text = (
            text[: match.start(2)]
            + str(len(kept))
            + text[match.end(2) : match.start(3)]
            + body
            + text[match.end(3) :]
        )
        return save.INLINE_MAP.sub(lambda m: renumber(m.group(0)), text)

    return rewrite


def chooseEntry(table):
    """An entry other entries refer to (so the IDs above it are affected too), else the first."""
    for id in sorted(table):
        if any(f"~{id}" in content for other, content in table.items() if other != id):
            return id
    return sorted(table)[0]


def chooseUnknown(table, raw):
    """An entry that a name of the dump `raw` has as its prefix (`~<ID>|`), one other entries
    refer to if there is one; else chooseEntry(). A prefix marked unknown (`~!<ID>|`) must stay
    in the map as it is: interned again, its text would become a node of its own, and the mark
    would show only in the expansion."""
    prefixes = sorted(set(re.findall(r" : ~([0-9a-v]{13})\|", raw)) & set(table))
    for id in prefixes:
        if any(f"~{id}" in content for other, content in table.items() if other != id):
            return id
    return prefixes[0] if prefixes else chooseEntry(table)


def entryUsedOutsideTheTable(entries):
    """An ID that Document.xml refers to outside its table (a shadow), or None."""
    _, table = save.nameTable(entries)
    rest = save.TABLE.sub("", entries["Document.xml"])
    for id in sorted(save.REF.findall(rest)):
        if id in table:
            return id
    return None


def linksToInterned(path):
    """The objects of a saved file with an element reference to an interned name (a link's
    shadow holds one)."""
    xml = save.fileEntries(path)["Document.xml"]
    objects = xml[xml.index("<ObjectData") :].split('<Object name="')[1:]
    return {
        block.split('"', 1)[0]
        for block in objects
        if re.search(r'<X?Link [^>]*\bshadow(ed)?="[^"]*~', block)
    }


def blocks(raw):
    """A dump's feature blocks, by feature name."""
    return {block.split()[0]: block for block in raw.split("\n[")[1:]}


def refsAbove(table, id):
    """`id` and every entry of `table` that refers to it, directly or not."""
    above = {id}
    changed = True
    while changed:
        changed = False
        for other, content in table.items():
            if other not in above and any(f"~{a}" in content for a in above):
                above.add(other)
                changed = True
    return above


class HoldsName:
    """A FeaturePython proxy whose state holds a subname, as an add-on's proxy may."""

    def __init__(self, obj=None, sub=""):
        self.sub = sub
        if obj is not None:
            obj.Proxy = self

    def dumps(self):
        return {"sub": self.sub}

    def loads(self, state):
        self.sub = state["sub"]


def proxyName():
    """A plain V2 name with an embedded name that no model has, and its subname."""
    edge = App.makeEncodedSection(
        referenceIDs=["Edge1"], iterationTag="5", opCode="PRX", elementType="E", mapperFlags=["IDX"]
    )
    face = App.makeEncodedSection(
        linkedNames=[edge], iterationTag="7", opCode="PRX", elementType="F", mapperFlags=["GEN"]
    )
    return face


def mappedPart(subname):
    return subname.split(";", 1)[1].rsplit(".", 1)[0]


def bothRoles(names):
    """(ID, name, name): an ID that one of `names` has as its prefix and another embeds, or None.
    In canonical form only a reference at the start, followed by `|`, is a prefix."""
    prefixed, embedded = {}, {}
    for name in sorted(names):
        for match in save.REF.finditer(name):
            if match.start() == 0 and name[match.end() : match.end() + 1] == "|":
                prefixed.setdefault(match.group(1), name)
            else:
                embedded.setdefault(match.group(1), name)
    for id in sorted(prefixed):
        if id in embedded and embedded[id] != prefixed[id]:
            return id, prefixed[id], embedded[id]
    return None


def shadowsOf(path):
    """[(sub, mapped name)] of the links' shadows in a saved file's Document.xml, in order. The
    link stores its subs as index names; the mapped names are in the shadows."""
    text = save.fileEntries(path)["Document.xml"]
    links = re.findall(r'<Link obj="[^"]*" sub="([^"]*)" shadowed="([^"]*)"', text)
    return [(html.unescape(sub), mappedPart(html.unescape(shadow))) for sub, shadow in links]


# ---------------------------------------------------------------------------------------------
# The child processes
# ---------------------------------------------------------------------------------------------


def _expanded(model, doc, features):
    return dump._dumpFeatures(model, [doc.getObject(n) for n in features], None, "V2i")


def _raw(model, doc, features):
    return dump._dumpFeatures(model, [doc.getObject(n) for n in features], None, "V2")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _missingReferences(doc):
    """The objects with an element reference marked missing ("?Face1")."""
    names = []
    for obj in doc.Objects:
        for prop in obj.PropertiesList:
            if "Link" not in obj.getTypeIdOfProperty(prop):
                continue
            try:
                subs = list(_strings(getattr(obj, prop)))
            except Exception:
                continue
            if any(sub.rsplit(".", 1)[-1].startswith("?") for sub in subs):
                names.append(obj.Name)
                break
    return sorted(names)


def hasStaticShape(path):
    """Whether a saved document has a static shape (`Part::Feature`): a recompute doesn't name it
    again, so a map dropped on load stays missing there, and what is built on it takes other
    names."""
    text = save.fileEntries(path)["Document.xml"]
    return '<Object type="Part::Feature"' in text


def _unresolved(raw):
    """The references in the dump `raw` that this process's table doesn't know (`~!` marks
    aren't references)."""
    return sorted(r for r in refsOf(raw) if App.getNameTableEntry(r) is None)


def _openModel(model, path, features, suffix):
    """Opens a model file: its raw and expanded names, then the same after a recompute, and a new
    save of it."""
    doc = App.openDocument(path)
    raw = _raw(model, doc, features)
    result = {
        "raw": raw,
        "unresolved": _unresolved(raw),
        "expanded": _expanded(model, doc, features),
        "touched": sorted(o.Name for o in doc.Objects if "Touched" in o.State),
        "mapSizes": {n: doc.getObject(n).Shape.ElementMapSize for n in features},
        "missing": _missingReferences(doc),
    }
    for obj in doc.Objects:
        obj.touch()
    doc.recompute()
    result["recomputedRaw"] = _raw(model, doc, features)
    result["recomputedUnresolved"] = _unresolved(result["recomputedRaw"])
    result["recomputed"] = _expanded(model, doc, features)
    again = path.replace(".FCStd", f"-{suffix}.FCStd")
    doc.saveAs(again)
    result["again"] = again
    App.closeDocument(doc.Name)
    return result


def _mergeModel(model, path, features):
    doc = App.newDocument(f"Merged{model}")
    doc.InternNames = False  # into a plain document (new ones start interned: ops#6 Q6)
    doc.mergeProject(path)
    result = {"expanded": _expanded(model, doc, features)}
    App.closeDocument(doc.Name)
    return result


def _guard(function, *args):
    try:
        return function(*args)
    except Exception:
        return {"error": traceback.format_exc()}


def _openCrossDoc(info, pathA):
    """Opens A (B too), touches and recomputes both, judges A's references: their verdicts."""
    scenario = getattr(crossdoc, info["scenario"])(info["config"])
    scenario.folder = os.path.dirname(pathA)
    scenario.doc = App.openDocument(pathA)
    target = App.getDocument(info["nameB"])
    scenario.documents = [scenario.doc.Name, target.Name]
    try:
        scenario.recordRefs(scenario.doc)
        for obj in scenario.doc.Objects + target.Objects:
            obj.touch()
        target.recompute()
        scenario.doc.recompute()
        scenario.stepName = "reopen"
        return {n: scenario.judge(r, "reopen").verdict for n, r in scenario.refs.items()}
    finally:
        for name in scenario.documents:
            if name in App.listDocuments():
                App.closeDocument(name)


def _childCollideOne(manifest):
    forced = {}
    for model, info in manifest["collideOne"].items():
        forced[model] = App.insertNameTableEntryForTesting(info["id"], BOGUS)
    out = {}
    for model, info in manifest["collideOne"].items():
        saved = manifest["models"][model]
        out[model] = _guard(_openModel, model, saved["path"], saved["features"], "one")
        out[model]["forced"] = forced[model]
    return out


def _childCollideAll(manifest):
    forced = 0
    for id in manifest["collideAll"]:
        forced += App.insertNameTableEntryForTesting(id, BOGUS)
    out = {"forced": forced, "models": {}, "merged": {}}
    for model in manifest["collideOne"]:
        saved = manifest["models"][model]
        out["models"][model] = _guard(_openModel, model, saved["path"], saved["features"], "all")
        out["merged"][model] = _guard(_mergeModel, model, saved["path"], saved["features"])
    out["crossdoc"] = save._childCrossDoc({"crossdoc": manifest["crossdoc"]})
    try:
        doc = App.openDocument(manifest["proxy"]["path"])
        sub = doc.getObject("Holder").Proxy.sub
        out["proxy"] = {"sub": sub, "expanded": App.expandMappedName(mappedPart(sub))}
        App.closeDocument(doc.Name)
    except Exception:
        out["proxy"] = {"error": traceback.format_exc()}
    return out


def _childUnknown(manifest):
    out = {"models": {}, "crossdoc": {}}
    for model, info in manifest["unknown"].items():
        App.insertNameTableEntryForTesting(info["id"], info["content"])  # the real content
    for model, info in manifest["unknown"].items():
        saved = manifest["models"][model]
        out["models"][model] = _guard(_openModel, model, info["path"], saved["features"], "unk")
    for key, info in manifest["unknownCrossDoc"].items():
        App.insertNameTableEntryForTesting(info["id"], info["content"])
        out["crossdoc"][key] = _guard(_openCrossDoc, manifest["crossdoc"][key], info["pathA"])
    return out


def _mergeNewer(model, path, original, features):
    """Merges the newer-format file, then the original, each into a new interned document: the
    first's names right after the merge, and both after a recompute (masked: the merged objects
    get new IDs)."""
    out = {}
    docs = []
    try:
        for key, source in (("newer", path), ("original", original)):
            doc = App.newDocument(f"Merged{key.capitalize()}{model}")
            docs.append(doc.Name)
            dump._setMode(doc, "V2i")
            doc.mergeProject(source)
            if key == "newer":
                out["raw"] = _raw(model, doc, features)
                out["unresolved"] = _unresolved(out["raw"])
                out["touched"] = sorted(o.Name for o in doc.Objects if "Touched" in o.State)
            for obj in doc.Objects:
                obj.touch()
            doc.recompute()
            objects = [doc.getObject(n) for n in features]
            out[key] = dump._dumpFeatures(model, objects, dump.Masker(doc), "V2i")
            if key == "newer":
                out["recomputedUnresolved"] = _unresolved(_raw(model, doc, features))
    finally:
        for name in docs:
            App.closeDocument(name)
    return out


def _childNewer(manifest):
    out = {"models": {}, "crossdoc": {}, "merged": {}}
    for model, info in manifest["newer"].items():
        saved = manifest["models"][model]
        out["models"][model] = _guard(_openModel, model, info["path"], saved["features"], "new")
        out["merged"][model] = _guard(
            _mergeNewer, model, info["path"], saved["path"], saved["features"]
        )
    for key, info in manifest["newerCrossDoc"].items():
        out["crossdoc"][key] = _guard(_openCrossDoc, manifest["crossdoc"][key], info["pathA"])
    return out


def _expandedShadows(doc, path):
    """Saves `doc` as `path`: its links' shadows, raw and expanded here."""
    doc.saveAs(path)
    return [(sub, name, App.expandMappedName(name)) for sub, name in shadowsOf(path)]


def _openBothRoles(info):
    doc = App.openDocument(info["path"])
    try:
        feature = doc.getObject(info["feature"])
        out = {
            "raw": _raw(info["model"], doc, [info["feature"]]),
            "expanded": _expanded(info["model"], doc, [info["feature"]]),
            "subs": _expandedShadows(doc, info["path"].replace(".FCStd", "-opened.FCStd")),
        }
        feature.touch()
        doc.getObject("Holder").touch()
        doc.recompute()
        out["recomputed"] = _expanded(info["model"], doc, [info["feature"]])
        again = info["path"].replace(".FCStd", "-recomputed.FCStd")
        out["recomputedSubs"] = [[s, x] for s, _, x in _expandedShadows(doc, again)]
        return out
    finally:
        App.closeDocument(doc.Name)


def _childBothRoles(manifest):
    info = manifest["bothRoles"]
    forced = App.insertNameTableEntryForTesting(info["id"], BOGUS)
    out = _guard(_openBothRoles, info)
    out["forced"] = forced
    return out


def _childCollideCrossDoc(manifest):
    cases = manifest["collideCrossDoc"]
    for info in cases.values():
        App.insertNameTableEntryForTesting(info["id"], BOGUS)  # two cases may share an ID
    out = save._childCrossDoc({"crossdoc": {key: info["crossdoc"] for key, info in cases.items()}})
    for key, info in cases.items():
        entry = App.getNameTableEntry(info["id"])  # (content, depth)
        out[key]["forced"] = entry is not None and entry[0] == BOGUS
    return out


def _referencedFace(ref):
    _, subs = ref.Target
    face = ref.Target[0].Shape.getElement(subs[0])
    return {"sub": subs[0], "area": face.Area, "surface": face.Surface.__class__.__name__}


def _childElementReference(manifest):
    info = manifest["elementRef"]
    out = {}
    try:
        doc = App.openDocument(info["closed"])  # opens B
        out["closed"] = _referencedFace(doc.getObject("Ref"))
        out["closed"]["unresolved"] = save._resolves([info["closed"]])
        for name in list(App.listDocuments()):
            App.closeDocument(name)
    except Exception:
        out["closed"] = {"error": traceback.format_exc()}
    try:
        doc = App.openDocument(info["absent"])  # B's file isn't there
        out["absent"] = {
            "unresolved": save._resolves([info["absent"]]),
            "documents": sorted(App.listDocuments()),
        }
        again = info["absent"].replace(".FCStd", "-again.FCStd")
        doc.saveAs(again)
        out["absent"]["again"] = again
        App.closeDocument(doc.Name)
    except Exception:
        out["absent"] = {"error": traceback.format_exc()}
    return out


PARTS = {
    "collideOne": _childCollideOne,
    "collideAll": _childCollideAll,
    "unknown": _childUnknown,
    "newer": _childNewer,
    "elementRef": _childElementReference,
    "bothRoles": _childBothRoles,
    "collideCrossDoc": _childCollideCrossDoc,
}


def childMain(manifestPath, outPath, part):
    with open(manifestPath, encoding="utf-8") as fh:
        manifest = json.load(fh)
    result = PARTS[part](manifest)
    with open(outPath, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)


CHILD_SCRIPT = """\
import os, traceback
try:
    from PartDesignTests import TestNamingLoad
    TestNamingLoad.childMain(os.environ["FREECAD_NAMING_LOAD_MANIFEST"],
                             os.environ["FREECAD_NAMING_LOAD_OUT"],
                             os.environ["FREECAD_NAMING_LOAD_PART"])
except Exception:
    with open(os.environ["FREECAD_NAMING_LOAD_OUT"] + ".error", "w") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
"""


# ---------------------------------------------------------------------------------------------
# This process: build, save, derive the files, run the children
# ---------------------------------------------------------------------------------------------


def _saveElementReference(folder):
    """B: a box with one edge filleted (its fillet face's name holds a reference); A: an object
    whose XLinkSub references that face. Both V2i, saved in `folder`; A also copied alone into
    another folder, where B's file is absent."""
    import Part  # noqa: F401  (the Part types)

    docs = []
    try:
        docB = App.newDocument("ElementRefB")
        docs.append(docB.Name)
        docB.HistoryAlgorithm, docB.InternNames = "V2", True
        box = docB.addObject("Part::Box", "Box")
        fillet = docB.addObject("Part::Fillet", "Fillet")
        fillet.Base = box
        fillet.Edges = [(1, 1.0, 1.0)]
        docB.recompute()
        docB.saveAs(os.path.join(folder, "ElementRefB.FCStd"))
        reverse = fillet.Shape.ElementReverseMap
        faces = [n for n in reverse if n.startswith("Face") and "~" in reverse[n]]
        if len(faces) != 1:
            raise AssertionError(f"one fillet face with a reference expected: {faces}")
        face = fillet.Shape.getElement(faces[0])
        docA = App.newDocument("ElementRefA")
        docs.append(docA.Name)
        docA.HistoryAlgorithm, docA.InternNames = "V2", True
        pathA = os.path.join(folder, "ElementRefA.FCStd")
        docA.saveAs(pathA)  # an XLink needs its owner saved
        ref = docA.addObject("App::FeaturePython", "Ref")
        ref.addProperty("App::PropertyXLinkSub", "Target")
        ref.Target = (fillet, [faces[0]])
        docA.recompute()
        docA.save()
        alone = os.path.join(folder, "alone")
        os.makedirs(alone)
        shutil.copy(pathA, alone)
        return {
            "closed": pathA,
            "absent": os.path.join(alone, "ElementRefA.FCStd"),
            "face": {
                "sub": faces[0],
                "area": face.Area,
                "surface": face.Surface.__class__.__name__,
            },
            "mapped": reverse[faces[0]],
        }
    finally:
        for name in docs:
            if name in App.listDocuments():
                App.closeDocument(name)


def _saveProxy(folder):
    doc = App.newDocument("ProxyHolder")
    try:
        doc.HistoryAlgorithm, doc.InternNames = "V2", True
        plain = proxyName()
        sub = "Box.;" + App.internMappedName(plain) + ".Face1"
        HoldsName(doc.addObject("App::FeaturePython", "Holder"), sub)
        path = os.path.join(folder, "ProxyHolder.FCStd")
        doc.saveAs(path)
        return {"path": path, "plain": plain, "sub": sub}
    finally:
        App.closeDocument(doc.Name)


def _saveBothRoles(folder):
    """The first dump model with a feature whose map holds an ID both as a name's prefix and
    embedded in another name, V2i, and a holder that links those two elements by their mapped
    names: the file's map and its XML each have the ID in both roles."""
    for model in dump.MODELS:
        doc = models.newDocument(f"BothRoles{model}")
        try:
            dump._setMode(doc, "V2i")
            features = dump.MODELS[model](doc)
            doc.recompute()
            for feature in features:
                elementMap = feature.Shape.ElementMap
                found = bothRoles(elementMap)
                if not found:
                    continue
                id, prefixed, embedded = found
                holder = doc.addObject("App::FeaturePython", "Holder")
                holder.addProperty("App::PropertyLinkSubListGlobal", "Refs")
                holder.Refs = [(feature, [f";{n}.{elementMap[n]}" for n in (prefixed, embedded)])]
                doc.recompute()
                path = os.path.join(folder, "BothRoles.FCStd")
                doc.saveAs(path)
                return {
                    "path": path,
                    "model": model,
                    "feature": feature.Name,
                    "id": id,
                    "expanded": _expanded(model, doc, [feature.Name]),
                    "subs": [[s, App.expandMappedName(n)] for s, n in shadowsOf(path)],
                    "shadows": [n for _, n in shadowsOf(path)],
                }
        finally:
            App.closeDocument(doc.Name)
    raise AssertionError("no dump model has an ID both as a prefix and embedded in one map")


def _deriveCollideCrossDoc(folder, manifest):
    """Each mixed cross-document scenario with A plain and B interned (config V2): one of B's IDs
    that A's file holds outside its table (in a shadow), in a copy of the scenario's folder."""
    manifest["collideCrossDoc"] = {}
    for key, info in manifest["crossdoc"].items():
        if info["config"] != "V2":
            continue
        entries = save.fileEntries(info["pathA"])
        id = entryUsedOutsideTheTable(entries)
        if id is None:
            continue
        copy = os.path.join(folder, f"{key}-collide")
        shutil.copytree(info["folder"], copy)
        derived = dict(info, folder=copy)
        for path in ("pathA", "pathB"):
            derived[path] = os.path.join(copy, os.path.basename(info[path]))
        manifest["collideCrossDoc"][key] = {
            "id": id,
            "crossdoc": derived,
            # A's own maps: plain, so the ID reaches A's file through its shadows only
            "mapsWithRefs": sorted(
                n for n, text in entries.items() if n.endswith(".Map.txt") and "~" in text
            ),
        }


def _derive(folder, manifest):
    """The files with a changed table or format, and the IDs the children make collide."""
    manifest["collideOne"] = {}
    manifest["unknown"] = {}
    manifest["newer"] = {}
    collideAll = set()
    for model, info in manifest["models"].items():
        entries = save.fileEntries(info["path"])
        _, table = save.nameTable(entries)
        if not table:
            continue
        collideAll |= set(table)
        id = chooseEntry(table)
        manifest["collideOne"][model] = {"id": id, "above": sorted(refsAbove(table, id))}
        unknown = os.path.join(folder, f"{model}-unknown.FCStd")
        id = chooseUnknown(table, info["raw"])
        rewriteFile(info["path"], unknown, withoutEntry(list(table), id))
        manifest["unknown"][model] = {
            "path": unknown,
            "id": id,
            "content": table[id],
            "above": sorted(refsAbove(table, id)),
            "prefix": f" : ~{id}|" in info["raw"],
        }
        newer = os.path.join(folder, f"{model}-newer.FCStd")
        rewriteFile(info["path"], newer, newerFormat)
        manifest["newer"][model] = {"path": newer}
    manifest["unknownCrossDoc"] = {}
    manifest["newerCrossDoc"] = {}
    for key, info in manifest["crossdoc"].items():
        for path in (info["pathA"], info["pathB"]):
            collideAll |= set(save.nameTable(save.fileEntries(path))[1])
        entries = save.fileEntries(info["pathA"])
        table = save.nameTable(entries)[1]
        id = entryUsedOutsideTheTable(entries)
        for kind in ("unknown", "newer"):
            if kind == "unknown" and id is None:
                continue
            copy = os.path.join(folder, f"{key}-{kind}")
            shutil.copytree(info["folder"], copy)
            pathA = os.path.join(copy, os.path.basename(info["pathA"]))
            rewrite = withoutEntry(list(table), id) if kind == "unknown" else newerFormat
            rewriteFile(info["pathA"], pathA, rewrite)
            derived = {"pathA": pathA}
            if kind == "unknown":
                derived.update(id=id, content=table[id])
            manifest[f"{kind}CrossDoc"][key] = derived
    collideAll |= set(save.nameTable(save.fileEntries(manifest["proxy"]["path"]))[1])
    manifest["collideAll"] = sorted(collideAll)
    _deriveCollideCrossDoc(folder, manifest)


_saved = None


def saved():
    """The manifest of the files saved and derived here, and the children's results under
    "child". Runs once per process."""
    global _saved
    if _saved is not None:
        return _saved
    # The canonical path: on macOS the temporary folder is reached through a symlink
    # (/var -> /private/var), and an XLink's relative path is taken from the owner's canonical
    # folder, so A would store a path that climbs to the root and still finds B from A's copy.
    folder = os.path.realpath(tempfile.mkdtemp(prefix="naming-load-"))
    manifest = {
        "folder": folder,
        "models": save._saveModels(folder),
        "crossdoc": save._saveCrossDoc(),
        "elementRef": _saveElementReference(folder),
        "proxy": _saveProxy(folder),
        "bothRoles": _saveBothRoles(folder),
    }
    _derive(folder, manifest)
    manifestPath = os.path.join(folder, "manifest.json")
    with open(manifestPath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    script = os.path.join(folder, "child.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(CHILD_SCRIPT)
    runs = {}
    for part in PARTS:
        out = os.path.join(folder, f"child-{part}.json")
        env = dict(os.environ)
        env.pop("FREECAD_INTERN_NAMES", None)
        env["FREECAD_NAMING_LOAD_MANIFEST"] = manifestPath
        env["FREECAD_NAMING_LOAD_OUT"] = out
        env["FREECAD_NAMING_LOAD_PART"] = part
        logPath = os.path.join(folder, f"child-{part}.log")
        log = open(logPath, "w")
        proc = subprocess.Popen(
            [dump._freecadCmd(), script], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=folder
        )
        runs[part] = (proc, out, log, logPath)
    manifest["child"] = {}
    manifest["logs"] = {}
    for part, (proc, out, log, logPath) in runs.items():
        try:
            proc.wait(timeout=900)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        with open(logPath, encoding="utf-8", errors="replace") as fh:
            manifest["logs"][part] = fh.read()
        if os.path.isfile(out):
            with open(out, encoding="utf-8") as fh:
                manifest["child"][part] = json.load(fh)
        else:
            error = out + ".error"
            reason = open(error).read() if os.path.isfile(error) else f"no output ({folder})"
            manifest["child"][part] = {"ERROR": reason}
    _saved = manifest
    return _saved


def child(test, part):
    result = saved()["child"][part]
    test.assertNotIn("ERROR", result, result.get("ERROR"))
    return result


def checked(test, value):
    test.assertNotIn("error", value, value.get("error"))
    return value


def refsOf(text):
    return set(save.REF.findall(text))


# ---------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------


class TestNamingLoadCollision(unittest.TestCase):
    """The process holds other content under the file's IDs: the file's names keep their
    meaning, inline."""

    def checkModel(self, result, info, colliding):
        self.assertEqual(result["expanded"], info["expanded"], "expanded names after the open")
        self.assertEqual(result["recomputed"], info["expanded"], "expanded names after a recompute")
        self.assertEqual(refsOf(result["raw"]) & colliding, set(), "a name refers to a collision")
        self.assertEqual(result["unresolved"], [], "a reference the table doesn't know")
        entries = save.fileEntries(result["again"])
        _, table = save.nameTable(entries)
        self.assertEqual(set(table) & colliding, set(), "a new save holds a colliding entry")
        self.assertEqual(sorted(save.refsIn(entries.values()) - set(table)), [])
        indices = save.indicesIn(save.mapTexts(entries))
        self.assertEqual(sorted(i for i in indices if i >= len(table)), [])

    def checkOne(self, model):
        info = saved()["models"][model]
        collision = saved()["collideOne"][model]
        result = checked(self, child(self, "collideOne")[model])
        self.assertTrue(result["forced"], "the collision wasn't forced")
        self.checkModel(result, info, {collision["id"]})
        self.assertIn("collide with this session's", saved()["logs"]["collideOne"])

    def checkAll(self, model):
        info = saved()["models"][model]
        colliding = set(saved()["collideAll"])
        result = child(self, "collideAll")
        self.assertEqual(result["forced"], len(colliding))
        self.checkModel(checked(self, result["models"][model]), info, colliding)
        merged = checked(self, result["merged"][model])
        self.assertEqual(merged["expanded"], info["expanded"], "expanded names after a merge")

    def checkCrossDoc(self, key):
        self.checkCrossDocResult(
            saved()["crossdoc"][key], checked(self, child(self, "collideAll")["crossdoc"][key])
        )

    def checkCrossDocOne(self, key):
        """One of B's IDs collides, which A's file holds only in A's shadows (A plain)."""
        case = saved()["collideCrossDoc"][key]
        self.assertEqual(case["mapsWithRefs"], [], "the premise: A's own maps are plain")
        result = checked(self, child(self, "collideCrossDoc")[key])
        self.assertTrue(result["forced"], "the collision wasn't forced")
        self.checkCrossDocResult(case["crossdoc"], result)
        self.assertIn("collide with this session's", saved()["logs"]["collideCrossDoc"])

    def testPrefixAndEmbedded(self):
        """An ID that a map holds as one name's prefix and embedded in another, both names also
        linked from the file's XML, collides: both stay what the file meant."""
        info = saved()["bothRoles"]
        id = info["id"]
        entries = save.fileEntries(info["path"])
        rest = save.TABLE.sub("", entries["Document.xml"])
        self.assertIn(f"~{id}|", rest, "the premise: the XML holds the ID as a prefix")
        self.assertRegex(rest, rf"~{id}(?!\|)", "the premise: the XML holds the ID embedded")
        self.assertEqual(bothRoles(info["shadows"])[0], id, "the premise: in the two shadows")
        # (the map's two roles are how _saveBothRoles chose the ID)
        result = child(self, "bothRoles")
        self.assertTrue(result["forced"], "the collision wasn't forced")
        checked(self, result)
        self.assertEqual(result["expanded"], info["expanded"], "expanded names after the open")
        self.assertEqual(result["recomputed"], info["expanded"], "expanded names after a recompute")
        self.assertNotIn(f"~{id}", result["raw"])
        self.assertEqual([[s, x] for s, _, x in result["subs"]], info["subs"], "linked names")
        self.assertEqual(result["recomputedSubs"], info["subs"], "linked names after a recompute")
        for _, name, _ in result["subs"]:
            self.assertNotIn(f"~{id}", name)
        self.assertIn("collide with this session's", saved()["logs"]["bothRoles"])

    def checkCrossDocResult(self, info, result):
        for name, record in result["reopen"].items():
            self.assertEqual(record["verdict"], "correct", f"{name} after the reopen: {record}")
        inProcess = info["inProcess"]
        self.assertIsInstance(inProcess, dict, inProcess)
        for name, record in result["edit"].items():
            for field in ("verdict", "stored", "outcome", "subs", "names"):
                a, b = record[field], inProcess[name][field]
                if field == "names" and a and b:
                    a = [save.GEOMETRY_ID.sub("g#", n) if n else n for n in a]
                    b = [save.GEOMETRY_ID.sub("g#", n) if n else n for n in b]
                self.assertEqual(a, b, f"{name} after the edit: {field}")


class TestNamingLoadUnknown(unittest.TestCase):
    """The file's table lacks an entry the child knows: its references go missing, never resolve
    to the child's entry."""

    def checkModel(self, model):
        info = saved()["models"][model]
        unknown = saved()["unknown"][model]
        result = checked(self, child(self, "unknown")["models"][model])
        above = set(unknown["above"])
        self.assertEqual(refsOf(result["raw"]) & above, set(), "a reference to a missing entry")
        self.assertEqual(result["unresolved"], [], "an unmarked reference the table doesn't know")
        marked = set(UNKNOWN.findall(result["raw"]))
        self.assertTrue(marked, "no reference was marked missing")
        self.assertLessEqual(marked, above)
        if unknown["prefix"]:
            self.assertIn(f" : ~!{unknown['id']}|", result["raw"], "the marked prefix is kept")
        self.assertIn(UNKNOWN_WARNING, saved()["logs"]["unknown"])
        # A recompute names everything again, except what holds a copy of a restored shape (a
        # Part::Feature's static shape): that keeps the mark, missing as before (in the
        # expansion: the mark can sit in a node the name embeds)
        recomputed = result["recomputed"].splitlines()
        expected = info["expanded"].splitlines()
        self.assertEqual(len(recomputed), len(expected))
        for line, before in zip(recomputed, expected):
            if line != before:
                self.assertIn("~!", line, "a name after a recompute")

    def checkCrossDoc(self, key):
        result = checked(self, child(self, "unknown")["crossdoc"][key])
        self.assertNotIn("wrong", result.values(), result)


class TestNamingLoadNewerFormat(unittest.TestCase):
    """A file of a newer naming format: its interned maps are dropped and recomputed, and no
    reference resolves."""

    def checkModel(self, model):
        info = saved()["models"][model]
        result = checked(self, child(self, "newer")["models"][model])
        self.assertIn(NEWER_WARNING, saved()["logs"]["newer"])
        # The maps are dropped, not kept with their references marked missing, and none of the
        # file's names comes back: this process knows none of its IDs (ops#97: a TopoShape's
        # cache brought the dropped map back)
        self.assertNotIn("~!", result["raw"])
        self.assertEqual(result["unresolved"], [], "a reference this process doesn't know")
        self.assertEqual(result["recomputedUnresolved"], [], "after a recompute")
        interned = {
            line.split()[0].strip("[")
            for line in info["raw"].split("\n[")
            if "~" in line.split("\n", 1)[-1]
        }
        for name in interned:
            if name in result["mapSizes"]:
                self.assertIn(name, result["touched"], f"{name} is recomputed")
        # Every element reference to an interned name is missing from the open on (the update
        # of all references after an open marks it), and only those
        broken = linksToInterned(info["path"])
        self.assertEqual(result["missing"], sorted(broken), "the missing element references")
        # A recompute names everything again, unless a static shape's names are missing
        if hasStaticShape(info["path"]):
            return
        if not broken:
            self.assertEqual(result["recomputedRaw"], info["raw"], "names after a recompute")
            return
        # A feature whose reference is missing fails, reported, rather than taking another element
        # (HelixBinderFace's FaceBinder of a helix face, as a PartDesign Fillet of a Pad's edge
        # would). In a file saved with the reference solver on (new documents since ops#7's Q7),
        # the solver finds the element again by the reference's saved fingerprint, and the
        # feature comes back as it was.
        recomputed, expected = blocks(result["recomputedRaw"]), blocks(info["raw"])
        self.assertEqual(list(recomputed), list(expected))
        for name, block in recomputed.items():
            if name in broken and not info.get("solver"):
                self.assertIn(" INVALID]", block.split("\n", 1)[0], f"{name} fails")
            else:
                self.assertEqual(block, expected[name], f"{name}: names after a recompute")

    def checkMerge(self, model):
        """Merged into an interned document, as opened: the maps are dropped and their objects
        recomputed (an import restores its objects as an open does), and a recompute names
        everything as the original file merged the same way, unless a static shape's names are
        missing."""
        info = saved()["models"][model]
        result = checked(self, child(self, "newer")["merged"][model])
        self.assertNotIn("~!", result["raw"])
        self.assertEqual(result["unresolved"], [], "a reference this process doesn't know")
        self.assertEqual(result["recomputedUnresolved"], [], "after a recompute")
        interned = {
            line.split()[0].strip("[")
            for line in info["raw"].split("\n[")
            if "~" in line.split("\n", 1)[-1]
        }
        self.assertTrue(interned, "the premise: the file has interned maps")
        for name in interned:
            self.assertIn(name, result["touched"], f"{name} is recomputed")
        if not hasStaticShape(info["path"]):
            self.assertEqual(result["newer"], result["original"], "names after a recompute")

    def checkCrossDoc(self, key):
        result = checked(self, child(self, "newer")["crossdoc"][key])
        self.assertNotIn("wrong", result.values(), result)


class TestNamingLoadProxy(unittest.TestCase):
    """A Python proxy's state, saved encoded, holds an interned subname."""

    def testFileHoldsTheEntries(self):
        """The file's table holds the entries of the subname's references, which only the
        encoded state holds."""
        info = saved()["proxy"]
        entries = save.fileEntries(info["path"])
        _, table = save.nameTable(entries)
        refs = refsOf(info["sub"])
        self.assertTrue(refs, "the premise: the subname is interned")
        self.assertLessEqual(refs, set(table))
        rest = save.TABLE.sub("", entries["Document.xml"])
        self.assertEqual(refsOf(rest), set(), "the premise: the state is encoded")

    def testCollisionOnLoad(self):
        """With the entries colliding, the loaded state's subname means what the file meant."""
        info = saved()["proxy"]
        result = checked(self, child(self, "collideAll")["proxy"])
        self.assertEqual(result["expanded"], info["plain"])
        self.assertNotEqual(result["sub"], info["sub"], "the subname was remapped")
        self.assertEqual(refsOf(result["sub"]) & set(saved()["collideAll"]), set())


class TestNamingLoadElementReference(unittest.TestCase):
    """A references a fillet face of B whose name holds a reference (V2i)."""

    def testTargetClosed(self):
        """Opening A opens B: the reference names the fillet face, and resolves."""
        info = saved()["elementRef"]
        result = checked(self, child(self, "elementRef")["closed"])
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(result["sub"], info["face"]["sub"])
        self.assertEqual(result["surface"], info["face"]["surface"])
        self.assertAlmostEqual(result["area"], info["face"]["area"])
        self.assertIn("~", info["mapped"], "the premise: the face's name holds a reference")

    def testTargetAbsent(self):
        """B's file is absent: A's shadows resolve from A's own table, and a new save of A writes
        them as they were."""
        info = saved()["elementRef"]
        before = save.fileEntries(info["absent"])
        self.assertEqual(
            set(re.findall(r'<XLink file="([^"]*)"', before["Document.xml"])),
            {"ElementRefB.FCStd"},
            "the premise: A links B by a path relative to A's folder, so B is absent from A's copy",
        )
        result = checked(self, child(self, "elementRef")["absent"])
        self.assertNotIn("ElementRefB", result["documents"])
        self.assertEqual(result["unresolved"], [])
        after = save.fileEntries(result["again"])
        xlink = re.compile(r"<XLink .*?/>|<XLink .*?</XLink>", re.S)
        stamp = re.compile(r' stamp="[^"]*"')  # an XLink to an absent file keeps no stamp

        def links(entries):
            return [stamp.sub("", x) for x in xlink.findall(entries["Document.xml"])]

        self.assertTrue(
            refsOf("".join(xlink.findall(before["Document.xml"]))),
            "the premise: A's shadow is interned",
        )
        self.assertEqual(links(after), links(before))
        self.assertEqual(save.nameTable(after), save.nameTable(before))
        self.assertNotIn("~!", after["Document.xml"])


def _addTests():
    for model in dump.MODELS:
        doc = dump.MODELS[model].__doc__.split(".")[0]
        for cls, method in (
            (TestNamingLoadCollision, "checkOne"),
            (TestNamingLoadCollision, "checkAll"),
            (TestNamingLoadUnknown, "checkModel"),
            (TestNamingLoadNewerFormat, "checkModel"),
            (TestNamingLoadNewerFormat, "checkMerge"),
        ):
            suffix = {"checkOne": "One", "checkAll": "All", "checkMerge": "Merged"}.get(method, "")

            def test(self, model=model, method=method):
                if model not in saved()["unknown"]:
                    self.skipTest("the model's file holds no interned names")
                getattr(self, method)(model)

            test.__name__ = f"test{model}{suffix}"
            test.__doc__ = f"{doc} (V2i)"
            setattr(cls, test.__name__, test)
    for name, config in save.CROSSDOC:
        key = f"{name}.{config}"
        for cls in (TestNamingLoadCollision, TestNamingLoadUnknown, TestNamingLoadNewerFormat):

            def test(self, key=key, cls=cls):
                if cls is TestNamingLoadUnknown and key not in saved()["unknownCrossDoc"]:
                    self.skipTest("A's file has no shadow with an interned name")
                self.checkCrossDoc(key)

            test.__name__ = f"test{name}{config}"
            test.__doc__ = f"{name} ({config})"
            setattr(cls, test.__name__, test)
        if config == "V2":  # mixed: A plain, B interned

            def test(self, key=key):
                if key not in saved()["collideCrossDoc"]:
                    self.skipTest("A's file has no shadow with an interned name")
                self.checkCrossDocOne(key)

            test.__name__ = f"test{name}{config}One"
            test.__doc__ = f"{name} ({config}), one of B's IDs colliding"
            setattr(TestNamingLoadCollision, test.__name__, test)


_addTests()
