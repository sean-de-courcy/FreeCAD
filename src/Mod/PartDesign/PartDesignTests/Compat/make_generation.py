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

"""Saves a generation of the CI reopen corpus (FreeCAD-CH ops#323, notes/beta-compatibility.md
3.1, 3.5).

Run with the FreeCADCmd of the build that saves the generation (a release build, or before the
beta B1's own build for gen0):

    FREECAD_COMPAT_OUT=<folder>/gen<k> FreeCADCmd make_generation.py

Optionally FREECAD_COMPAT_MODELS="A B" for a partial generation (only those models). For each
model it builds the documents (`models.py`), checks them (every object valid, the stated
volumes), records them (`CompatRecord.record`) and saves `<stem>.FCStd` per document and
`<model>.oracle.json`, then `MANIFEST`: JSON with the build, the date, the fork release, the
naming revision, each model's documents in their open order, and each file's SHA-256. A folder
that already has a MANIFEST is refused: generations are immutable.
"""

import datetime
import hashlib
import json
import os
import re
import sys
import zipfile

import FreeCAD as App

import CompatRecord
from PartDesignTests.Compat import models
from PartDesignTests.Scenarios import models as m

FORMAT = 1
VOLUME_TOLERANCE = 1e-7  # relative: the stated volumes are exact


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def documentAttribute(path, name):
    """An attribute of the saved file's `Document` element, or None."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("Document.xml").decode("utf-8", errors="replace")
    found = re.search(r"<Document [^>]*\b" + name + r'="([^"]*)"', xml)
    return found.group(1) if found else None


def newModelDocument(folder, stem, docs):
    """A new document saved as `<folder>/<stem>.FCStd`, as a beta user's are: V2 naming,
    InternNames and the reference solver on, set explicitly so a preference can't change them."""
    doc = m.newDocument(stem)
    doc.HistoryAlgorithm = "V2"
    doc.InternNames = True
    doc.ReferenceSolver = True
    doc.saveAs(os.path.join(folder, stem + ".FCStd"))
    docs.append(doc)
    return doc


def _stem(doc):
    return os.path.splitext(os.path.basename(doc.FileName))[0]


def _find(docs, key):
    """The object for a volume key: `Name`, or `stem#Name` in a model of several documents."""
    stem, _, name = key.rpartition("#")
    for doc in docs:
        if stem and _stem(doc) != stem:
            continue
        obj = doc.getObject(name)
        if obj is not None:
            return obj
    raise AssertionError(f"no object {key}")


def check(model, docs, expected):
    """Raises unless every object is valid and every stated volume is met."""
    for doc in docs:
        for obj in doc.Objects:
            if "Invalid" in obj.State:
                raise AssertionError(f"{model}: {_stem(doc)}#{obj.Name} is invalid")
    for key, volume in (expected or {}).get("volumes", {}).items():
        actual = _find(docs, key).Shape.Volume
        if abs(actual - volume) > VOLUME_TOLERANCE * max(abs(volume), 1.0):
            raise AssertionError(f"{model}: {key} volume {actual}, expected {volume}")


def _closeAll(docs):
    for doc in docs:
        if doc.Name in App.listDocuments():
            App.closeDocument(doc.Name)


def reopened(folder, stems):
    """{stem: record} of the saved files as this build reopens them, in order, with no
    recompute."""
    docs = []
    try:
        for stem in stems:
            docs.append(App.openDocument(os.path.join(folder, stem + ".FCStd")))
        return {_stem(doc): CompatRecord.record(doc) for doc in docs}
    finally:
        _closeAll(docs)


def buildModel(name, folder):
    """Builds, checks, records and saves one model; returns its documents' stems, in open order.

    The oracle holds two records per document: `records`, the live state just before the save
    (what a recompute must give), and the saved file as this build reopens it (what an open must
    give: a restore can set a property the live document left alone, e.g. a LinearPattern's
    Spacings2), kept as `openedDelta` over `records` (`CompatRecord.delta`; nearly always
    small). `restoreDifferences` lists where they differ, for reading."""
    docs = []
    try:
        expected = models.MODELS[name](lambda stem: newModelDocument(folder, stem, docs))
        for doc in docs:
            doc.recompute()
        check(name, docs, expected)
        records = {}
        for doc in docs:
            records[_stem(doc)] = CompatRecord.record(doc)
        for doc in docs:
            doc.save()
        stems = [_stem(doc) for doc in docs]
    finally:
        _closeAll(docs)
    for stem in stems:
        for backup in os.listdir(folder):
            if backup.startswith(stem + ".") and backup.endswith(".FCBak"):
                os.remove(os.path.join(folder, backup))
    opened = reopened(folder, stems)
    differences = []
    deltas = {}
    for stem in stems:
        lines, _ = CompatRecord.compare(records[stem], opened[stem], "open")
        differences += [f"{stem}: {line}" for line in lines]
        deltas[stem] = CompatRecord.delta(records[stem], opened[stem])
        rebuilt = CompatRecord.applyDelta(records[stem], deltas[stem])
        if CompatRecord.compare(opened[stem], rebuilt, "open")[0]:
            raise AssertionError(f"{name}: {stem}'s reopened record isn't its delta's")
    CompatRecord.dump(
        {
            "format": FORMAT,
            "model": name,
            "documents": stems,
            "records": records,
            "openedDelta": deltas,
            "restoreDifferences": differences,
        },
        os.path.join(folder, name + ".oracle.json"),
        compact=True,
    )
    return stems


def generate(folder, names=None):
    """Saves the models (all, or `names`) into `folder` and writes its MANIFEST."""
    folder = os.path.realpath(folder)
    if os.path.exists(os.path.join(folder, "MANIFEST")):
        raise RuntimeError(f"{folder} already holds a generation")
    os.makedirs(folder, exist_ok=True)
    generation = re.fullmatch(r"gen(\d+)", os.path.basename(folder))
    manifest = {
        "format": FORMAT,
        "generation": int(generation.group(1)) if generation else None,
        "build": " ".join(str(v) for v in App.Version()),
        "platform": sys.platform,
        "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "forkRelease": App.getForkRelease(),
        "models": {},
    }
    for name in names or models.MODELS:
        manifest["models"][name] = buildModel(name, folder)
    first = next(iter(manifest["models"].values()))[0]
    manifest["namingRevision"] = int(
        documentAttribute(os.path.join(folder, first + ".FCStd"), "NamingRevision")
    )
    files = {}
    for model, stems in manifest["models"].items():
        for fileName in [s + ".FCStd" for s in stems] + [model + ".oracle.json"]:
            files[fileName] = sha256(os.path.join(folder, fileName))
    manifest["files"] = files
    with open(os.path.join(folder, "MANIFEST"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return manifest


def main():
    folder = os.environ.get("FREECAD_COMPAT_OUT")
    if not folder:
        raise SystemExit("set FREECAD_COMPAT_OUT to the generation's folder (gen<k>)")
    names = os.environ.get("FREECAD_COMPAT_MODELS", "").split() or None
    manifest = generate(folder, names)
    size = sum(os.path.getsize(os.path.join(folder, f)) for f in manifest["files"])
    App.Console.PrintMessage(
        f"Generation {manifest['generation']} in {folder}: {len(manifest['models'])} models, "
        f"{len(manifest['files'])} files, {size / 1024:.0f} KB, fork release "
        f"{manifest['forkRelease']}, naming revision {manifest['namingRevision']}\n"
    )


if __name__ == "__main__":
    main()
