# SPDX-License-Identifier: LGPL-2.1-or-later
"""Derived parts from another document's saved studio (FreeCAD-CH, notes/derived-design.md).

Onshape's Derived feature takes parts from a studio of another document through a *version* of
it: the parts change only when the user updates the reference. Here a saved .FCStd stands for the
version (saving is "making a version"):

- `derive_from_file()` copies parts of a studio of a saved file into a studio of `doc`: per part
  a derived copy (a hidden Part::Feature held by the studio, with the `DerivedSource*` properties
  and the part's shape in its studio's frame) and a Derived feature on the copies
  (`PartDesign.makeDerivedCopies`), whose Bodies later features may change like any part.
- Opening `doc` never opens the source: the copies are saved in `doc`.
- `derived_state()` says whether the source file changed since (its stamp), or can't be found.
- `refresh_derived()` copies the parts again from the saved file, as one transaction; a part gone
  from the source leaves its copy empty, so its member fails "Missing source part", as Onshape's
  Derived fails after an update to a version without the part.

The source is always read from the saved file (a temporary copy of it is opened hidden), never
from an open document's unsaved state, so what is copied is what the stamp names.
"""

import hashlib
import os
import shutil
import tempfile

import FreeCAD as App

UP_TO_DATE = "up to date"
OUT_OF_DATE = "out of date"
NOT_FOUND = "not found"

STAMP_VERSION = "sha256:fcstd1:"

_PROPS = (
    ("DerivedSourceFile", "The source file, relative to this document's file"),
    ("DerivedSourcePath", "The source file's absolute path when the copy was made or refreshed"),
    ("DerivedSourceStudio", "The source studio's internal name (empty: the document's top level)"),
    ("DerivedSourceStudioLabel", "The source studio's label"),
    ("DerivedSourcePart", "The source part's internal name, which a refresh looks for"),
    ("DerivedSourceLabel", "The source part's label"),
    ("DerivedSourceStamp", "The source file's stamp when the copy was made or refreshed"),
)


class DerivedError(ValueError):
    """A derive or a refresh that can't be done; nothing was changed."""


def _pd():
    import PartDesign

    return PartDesign


def stamp(path):
    """The stamp of a saved file: the sha256 of its bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return STAMP_VERSION + digest.hexdigest()


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _relative(doc, path):
    if not doc.FileName:
        return ""
    try:
        return os.path.relpath(path, os.path.dirname(doc.FileName)).replace("\\", "/")
    except ValueError:  # another drive
        return ""


def _studio_of(doc, name):
    """The studio argument PartDesign takes: the document for its top level, else the App::Part."""
    if not name:
        return doc
    studio = doc.getObject(name)
    if studio is None or not studio.isDerivedFrom("App::Part"):
        raise DerivedError("Derived: the source has no part studio " + name)
    return studio


def _studio_name(studio):
    return "" if studio is None or studio.isDerivedFrom("App::Document") else studio.Name


def _studio_label(doc, studio):
    return _pd().studioLabel(studio if studio is not None else doc)


class _SavedSource:
    """The saved state of a source file, opened hidden from a temporary copy, closed on exit."""

    def __init__(self, path):
        self.path = path
        self.doc = None
        self.tmp = None
        self.active = None

    def __enter__(self):
        if not os.path.isfile(self.path):
            raise DerivedError("Derived: the source file is not found: " + self.path)
        self.stamp = stamp(self.path)
        self.tmp = tempfile.mkdtemp(prefix="fcderived")
        copy = os.path.join(self.tmp, os.path.basename(self.path))
        shutil.copyfile(self.path, copy)
        # The hidden open and close leave no active document: keep the caller's (D1)
        self.active = App.ActiveDocument.Name if App.ActiveDocument else None
        self.doc = App.openDocument(copy, hidden=True)
        return self

    def __exit__(self, *exc):
        if self.doc is not None:
            try:
                App.closeDocument(self.doc.Name)
            except Exception:
                pass
        if self.active and App.ActiveDocument is None and self.active in App.listDocuments():
            App.setActiveDocument(self.active)
            if App.GuiUp:
                import FreeCADGui

                FreeCADGui.setActiveDocument(self.active)
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    def parts(self, studio_name):
        """The derivable parts of the studio, by internal name."""
        studio = _studio_of(self.doc, studio_name)
        return {b.Name: b for b in _pd().derivableParts(studio)}


def list_source(path):
    """The studios of the saved file path that hold derivable parts, for a chooser:
    [(studio internal name ("" for the top level), studio label, [(part name, part label)])]."""
    pd = _pd()
    out = []
    with _SavedSource(path) as source:
        for studio in pd.derivedStudios(source.doc):
            parts = pd.derivableParts(studio)
            name = _studio_name(studio)
            label = _studio_label(source.doc, studio if name else None)
            out.append((name, label, [(b.Name, b.Label) for b in parts]))
    return out


def _studio_frame(body):
    """The body's shape as its studio sees it: placed relative to the studio's origin."""
    import Part

    studio = None
    parent = body.getParentGeoFeatureGroup()
    while parent is not None:
        if parent.isDerivedFrom("App::Part") and parent.getParentGeoFeatureGroup() is None:
            studio = parent
        parent = parent.getParentGeoFeatureGroup()
    shape = body.Shape.copy()
    if studio is not None:
        shape.Placement = studio.getGlobalPlacement().inverse().multiply(
            body.getGlobalPlacement()
        )
    else:
        shape.Placement = body.getGlobalPlacement()
    # An independent copy with no element map of the other document's (its tags and string
    # hasher mean nothing here; the copy's own names start from it)
    fresh = Part.Shape()
    fresh.importBrepFromString(shape.exportBrepToString())
    return fresh


def _set_copy(copy, body, studio_doc, studio_name, path, owner, file_stamp):
    copy.DerivedSourceFile = _relative(owner, path)
    copy.DerivedSourcePath = os.path.abspath(path)
    copy.DerivedSourceStudio = studio_name
    studio = studio_doc.getObject(studio_name) if studio_name else None
    if not studio_name or studio is not None:
        copy.DerivedSourceStudioLabel = _studio_label(studio_doc, studio)
    copy.DerivedSourceStamp = file_stamp
    if body is None:
        import Part

        copy.Shape = Part.Shape()
    else:
        copy.DerivedSourceLabel = body.Label
        copy.Shape = _studio_frame(body)


def _new_copy(owner, studio, part_name):
    copy = owner.addObject("Part::Feature", "DerivedCopy")
    for name, doc in _PROPS:
        copy.addProperty("App::PropertyString", name, "Derived", doc)
        copy.setEditorMode(name, 1)
    copy.DerivedSourcePart = part_name
    if studio is not None and not studio.isDerivedFrom("App::Document"):
        studio.addObject(copy)
    copy.Visibility = False
    return copy


def derive_from_file(doc, studio, path, source_studio, part_names):
    """A Derived feature in studio (doc for its top level, else an App::Part of doc) of the parts
    part_names (internal names) of the studio source_studio ("" for the top level) of the saved
    file path. One transaction; recomputes doc. Returns the lead. Raises DerivedError, with
    nothing changed, for a missing file, doc's own file, a missing studio or part."""
    if not part_names:
        raise DerivedError("Derived: choose the parts to derive")
    if doc.FileName and _norm(doc.FileName) == _norm(path):
        raise DerivedError("Derived: the source is this document: derive from its own studio")
    with _SavedSource(path) as source:
        parts = source.parts(source_studio)
        missing = [n for n in part_names if n not in parts]
        if missing:
            raise DerivedError(
                "Derived: the source studio has no part " + ", ".join(missing)
            )
        doc.openTransaction("Derived")
        try:
            copies = []
            for name in part_names:
                copy = _new_copy(doc, studio, name)
                _set_copy(copy, parts[name], source.doc, source_studio, path, doc, source.stamp)
                copies.append(copy)
            lead = _pd().makeDerivedCopies(studio, copies)
        except Exception:
            doc.abortTransaction()
            raise
        doc.commitTransaction()
    doc.recompute()
    return lead


def _copies(lead):
    pd = _pd()
    lead = pd.derivedLead(lead) or lead
    out = []
    for member in pd.derivedMembers(lead):
        base = member.BaseFeature
        if base is not None and pd.isDerivedCopy(base):
            out.append(base)
    return lead, out


def source_path(copy):
    """Where copy's source file is: relative to its document's file first, else the absolute path;
    None when neither exists."""
    owner = copy.Document
    if copy.DerivedSourceFile and owner.FileName:
        rel = os.path.normpath(os.path.join(os.path.dirname(owner.FileName), copy.DerivedSourceFile))
        if os.path.isfile(rel):
            return rel
    if copy.DerivedSourcePath and os.path.isfile(copy.DerivedSourcePath):
        return copy.DerivedSourcePath
    return None


def derived_state(obj):
    """The state of a Derived feature on derived copies (its lead, a member, or a copy):
    UP_TO_DATE, OUT_OF_DATE (the source file changed since) or NOT_FOUND. None for a Derived
    feature of this document's own studio."""
    pd = _pd()
    copies = [obj] if pd.isDerivedCopy(obj) else _copies(obj)[1]
    if not copies:
        return None
    path = source_path(copies[0])
    if path is None:
        return NOT_FOUND
    current = stamp(path)
    return UP_TO_DATE if all(c.DerivedSourceStamp == current for c in copies) else OUT_OF_DATE


def refresh_derived(lead):
    """Copies the parts of lead's Derived feature again from the saved source file, as one
    transaction, and recomputes. A part the source no longer has leaves its copy empty (its
    member then fails "Missing source part"). Raises DerivedError, with nothing changed, when the
    source file is not found. Returns the lead."""
    lead, copies = _copies(lead)
    if not copies:
        raise DerivedError("Derived: not a Derived feature from another document")
    doc = lead.Document
    path = source_path(copies[0])
    if path is None:
        raise DerivedError(
            "Derived: the source file is not found: "
            + (copies[0].DerivedSourceFile or copies[0].DerivedSourcePath)
        )
    with _SavedSource(path) as source:
        studio_name = copies[0].DerivedSourceStudio
        try:
            parts = source.parts(studio_name)
        except DerivedError:
            parts = {}
        doc.openTransaction("Refresh Derived")
        try:
            for copy in copies:
                _set_copy(
                    copy, parts.get(copy.DerivedSourcePart), source.doc, studio_name, path, doc,
                    source.stamp,
                )
        except Exception:
            doc.abortTransaction()
            raise
        doc.commitTransaction()
    doc.recompute()
    return lead
