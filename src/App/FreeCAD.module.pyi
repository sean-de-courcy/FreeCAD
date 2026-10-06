# SPDX-License-Identifier: LGPL-2.1-or-later

"""Typed public signatures for the ``FreeCAD`` application module.

This source-adjacent stub file carries the callable surface together with the
simple helper aliases, reexports, module globals, and typing-only support that
those signatures use.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, TypeAlias, overload

from Base.Metadata import module
from . import Console as Console  # pylint: disable=no-name-in-module,unused-import
from . import Units as Units  # pylint: disable=no-name-in-module,unused-import

module(
    Name="FreeCAD",
    Namespace="App",
    Include="ApplicationPy.h",
    CallbackOwner="ApplicationPy",
    CallbackPrefix="s",
)

_FileTypeModules: TypeAlias = dict[str, str | list[str] | None]
_LogLevelName: TypeAlias = Literal["Default", "Error", "Warning", "Message", "Log", "Trace"]
GuiUp: int
ActiveDocument: Document | None
Gui: Any
"""Optional GUI module alias installed by GUI initialization; use FreeCADGui for typed APIs."""

# Parameter and configuration access
def ParamGet(path: str, /) -> ParameterGrp:
    """Return the parameter group rooted at one application preference path."""
    ...

def saveParameter(name: str = "User parameter", /) -> None:
    """Persist one named parameter tree to disk, defaulting to the user parameter set."""
    ...

def Version() -> list[str]:
    """Return the FreeCAD version components as strings."""
    ...

def ConfigGet(key: str, /) -> str:
    """Return one application configuration value by key."""
    ...

def ConfigSet(key: str, value: str, /) -> None:
    """Store one application configuration value by key."""
    ...

def ConfigDump() -> dict[str, str]:
    """Return the current flat application configuration mapping."""
    ...

# Import and export registration
def addImportType(extension: str, module: str, /) -> None:
    """Register one importer module for a file extension."""
    ...

def changeImportModule(extension: str, old_module: str, new_module: str, /) -> None:
    """Replace one importer module registration for a file extension."""
    ...

@overload
def getImportType() -> _FileTypeModules:
    """Return the full extension-to-module map for all registered importers."""
    ...

@overload
def getImportType(extension: str, /) -> list[str]:
    """Return the importer modules registered for one specific extension."""
    ...

def addExportType(extension: str, module: str, /) -> None:
    """Register one exporter module for a file extension."""
    ...

def addTranslatableExportType(description: str, extensions: list[str], module: str, /) -> None:
    """Register one exporter together with a translated file-dialog description.

    ``description`` should be registered with the translation system using the
    ``FileFormat`` context.
    """
    ...

def changeExportModule(extension: str, old_module: str, new_module: str, /) -> None:
    """Replace one exporter module registration for a file extension."""
    ...

@overload
def getExportType() -> _FileTypeModules:
    """Return the full extension-to-module map for all registered exporters."""
    ...

@overload
def getExportType(extension: str, /) -> list[str]:
    """Return the exporter modules registered for one specific extension."""
    ...

# Resource and user paths
def getResourceDir() -> str:
    """Return the root resource directory shipped with FreeCAD."""
    ...

def getLibraryDir() -> str:
    """Return the directory that contains FreeCAD shared libraries."""
    ...

def getTempPath() -> str:
    """Return the temporary directory used by FreeCAD."""
    ...

def getUserCachePath() -> str:
    """Return the user cache directory used by FreeCAD."""
    ...

def getUserConfigDir() -> str:
    """Return the user configuration directory."""
    ...

def getUserAppDataDir() -> str:
    """Return the user application-data directory."""
    ...

def getUserMacroDir(actual: bool = False, /) -> str:
    """Return the standard user macro directory, or the effective user-defined path."""
    ...

def getHelpDir() -> str:
    """Return the directory that contains bundled help resources."""
    ...

def getHomePath() -> str:
    """Return the current FreeCAD home directory."""
    ...

# Document lifecycle
def loadFile(path: str, doc: str = "", module: str = "", /) -> None:
    """Load one file by delegating to an importer module.

    When ``module`` is empty, FreeCAD chooses an importer from the file extension.
    If several importers match, the first registered importer is used; if none
    matches, an exception is raised.
    """
    ...

def open(name: str, hidden: bool = False, temporary: bool = False) -> Document:
    """Open a document file and return the created document; see ``openDocument``."""
    ...

def openDocument(name: str, hidden: bool = False, temporary: bool = False) -> Document:
    """Create a document, load an existing project file, and return it.

    ``hidden`` suppresses creation of the document 3D view. ``temporary`` hides
    the document in the tree view. An I/O exception is raised when the file does
    not exist or cannot be loaded. Non-file restore failures may leave the
    created document open for recovery.
    """
    ...

def newDocument(
    name: str | None = None,
    label: str | None = None,
    hidden: bool = False,
    temp: bool = False,
) -> Document:
    """Create and return a new document.

    ``name`` is the internal document name and is made unique automatically.
    ``label`` is the optional user-changeable label. ``hidden`` suppresses
    creation of the document 3D view. ``temp`` marks the document as temporary
    so it is not saved.
    """
    ...

def closeDocument(document: str | Document, /) -> None:
    """Close one document by name or object."""
    ...

def writeRecoverySnapshotToTransientDir(
    document: Document,
    /,
    *,
    compressed: bool = True,
    save_binary_brep: bool = True,
    save_thumbnail: bool = False,
) -> bool:
    """Write one recovery snapshot for a document into its transient directory."""
    ...

# Document queries and observers
def activeDocument() -> Document | None:
    """Return the current active document, if any."""
    ...

def setActiveDocument(name: str, /) -> None:
    """Make one named document the active document."""
    ...

def getDocument(name: str, /) -> Document:
    """Return one loaded document by name, raising if no such document exists."""
    ...

def listDocuments(sort: bool = False, /) -> dict[str, Document]:
    """Return the loaded documents keyed by name, optionally sorted by dependency order."""
    ...

def addDocumentObserver(observer: object, /) -> None:
    """Register one document observer object."""
    ...

def removeDocumentObserver(observer: object, /) -> None:
    """Unregister one document observer object."""
    ...

# Logging, dependency queries, and transactions
def setLogLevel(tag: str, level: _LogLevelName | int, /) -> None:
    """Set one named log channel to a numeric or named level."""
    ...

def getLogLevel(tag: str, /) -> int:
    """Return the numeric level of one named log channel."""
    ...

def checkLinkDepth(depth: int, /) -> int:
    """Clamp or validate one proposed link depth value."""
    ...

def getLinksTo(
    obj: DocumentObject | None = None,
    options: int = 0,
    maxCount: int = 0,
    /,
) -> tuple[DocumentObject, ...]:
    """Return objects that link to the given object.

    ``options & 1`` searches recursively. ``options & 2`` checks link arrays.
    ``maxCount`` limits the number of returned links.
    """
    ...

def getDependentObjects(
    obj: DocumentObject | Sequence[DocumentObject],
    options: int = 0,
    /,
) -> tuple[DocumentObject, ...]:
    """Return objects that depend on one object or object sequence.

    The result includes the input objects. ``options & 1`` sorts the result in
    topological order; ``options & 2`` excludes Link-type dependencies.
    """
    ...

def setActiveTransaction(name: str, persist: bool = False, /) -> int:
    """Start or select the active transaction and return its identifier.

    While active, document changes open transactions with this application-wide
    name and identifier. ``persist`` is kept for compatibility and has no effect.
    """
    ...

def getActiveTransaction() -> tuple[str, int] | None:
    """Return the current transaction name and identifier, if any."""
    ...

def closeActiveTransaction(abort: bool = False, id: int = 0, /) -> None:
    """Close or abort the current transaction."""
    ...

def isRestoring() -> bool:
    """Return whether FreeCAD is currently restoring document state."""
    ...

def checkAbort() -> None:
    """Raise ``Base.FreeCADAbort`` when the current operation was aborted.

    This only works while a sequencer or Python progress indicator is active,
    such as during document restore or recomputation. Users usually request the
    abort by pressing Esc.
    """
    ...

def getDecodedMappedName(name: str, /) -> list[dict]:
    """Returns the decoding of `name` in the form of a dictionary."""
    ...

def makeEncodedSection(
    *,
    referenceIDs: list[str] = [],
    linkedNames: list[str] = [],
    iterationTag: str = "0",
    opCode: str = "MKR",
    index: str = "0",
    elementType: str = "E",
    duplicateCount: str = "0",
    mapperFlags: list[str] = [],
    connectedElements: list[str] = [],
) -> str:
    """Returns an encoded mapped section generated with the input arguments."""
    ...

def getNameAncestors(name: str, /) -> list[str]:
    """Return the ancestor set of a V2 mapped name, sorted.

    The set holds the name itself, every prefix before a top-level `|`, and every Linked or
    Connected Name embedded at any depth: the structural evidence of the reference solver.
    `name` is a bare mapped name, without the `;` prefix or an element suffix.

    Below a pattern instance's section (`...;TRF;<k>;...`) the ancestors are the instance's
    copies, written `\\x1e<pattern tag>;<k>\\x1e<name>` (ops#91).
    """
    ...

def isPieceOf(name: str, old: str, /) -> bool:
    """Return whether V2 mapped name `name` is a split piece of `old`.

    A piece is `old` followed by one or more sections that carry the MOD flag and `old`'s element
    type.
    """
    ...

def expandMappedName(name: str, /) -> str:
    """Return the full V2 form of mapped name `name`, which may be interned (ops#6).

    Every `~<ID>` the process's name table knows is replaced by its expansion, escaped as V2
    escapes embedded names, so an interned name expands to the plain V2 string byte for byte.
    Unknown IDs are kept. A plain name comes back unchanged.
    """
    ...

def internMappedName(name: str, /) -> str:
    """Return the interned form of V2 mapped name `name`, and add its nodes to the name table.

    Each Linked and Connected Name becomes `~<ID>`, and the sections before the last become one
    `~<ID>|` prefix. For tests: nothing in FreeCAD interns names yet.
    """
    ...

def getMappedNameId(name: str, /) -> str | None:
    """Return the ID of V2 mapped name `name` as a node of the name table (13 base32 characters).

    The name's node is added to the table, so `~<ID>` can be embedded in another name. Returns
    None if its ID is taken by another content (a collision). For tests.
    """
    ...

def getNameTableContentId(content: str, /) -> str:
    """Return the ID the name table gives entry content `content` as it is (13 base32
    characters), without interning it or adding anything: what a load computes for a file's
    entry (ops#6). getMappedNameId() interns the name first, so a content kept in full form
    gets the ID of its interned form there. For tests.
    """
    ...

def getNameTableEntry(id: str, /) -> tuple[str, int] | None:
    """Return the name table's entry for `id` (`<ID>` or `~<ID>`): its interned content and its
    depth. Returns None for an ID the table doesn't have. For tests.
    """
    ...

def insertNameTableEntryForTesting(id: str, content: str, /) -> bool:
    """Put `content` into the name table under `id` (`<ID>` or `~<ID>`), whatever the content's
    own ID, if `id` is free. Returns False if it was taken. For tests that force a collision
    with the entries of a file opened afterwards (ops#6).
    """
    ...

def getReferenceReport(obj: DocumentObject, /) -> list[dict[str, Any]]:
    """Return what the reference solver did with `obj`'s element references (ops#7).

    One dict per reference the solver resolved beyond the exact lookup, or left broken, plus one
    per missing reference it has no entry for, sorted by property and index. Keys: `property`,
    `index`, `sub`, `old` (the old mapped name), `status` (`resolved`, `broken`, `index`,
    `expanded` or `guessed`), `tier` (0-3 for `resolved`; 1, or 4 for a continuation, for
    `expanded`; 3, or 1 for a split's piece, for `guessed`), `new`
    (the element it resolved to, the first for `expanded`), `pieces` (`expanded`: every element),
    `candidates` (element names), `candidate_names` (their mapped names), `candidate_roles`
    (why each is one: `place` for an element where a moved one was, `name` for the element the
    reference's name holds, `piece`, `structural`, `geometric`, `index`, `guess` for a guess
    rule's pick, or empty),
    `candidate_distances` (each one's centre from the saved centre, or None), `evidence` and
    `target`.

    A reference with a guess record (ops#127: resolved by geometry, a continuation or split
    expanded, a naming migration's index carry) is listed too, even before the solver ran again
    (a reopened file: `evidence` `saved guess`, `status` and `tier` as its kind gives; key on
    `guess_kind`, not `status`). Keys for it: `guess_kind`
    (`tier2`, `tier3`, `continued`, `expanded`, `index`, `rejected`, or a guess rule's:
    `nearest`, the nearest of several structural candidates by a wider tier 3; `geometric`, the
    nearest without a structural candidate, by the same wider tier 3; `piece`, the piece of a
    split element that holds its saved centre; empty without a record),
    `original` (`{"index", "name"}`: what the reference stood for), `alternatives` (a list of
    `{"index", "role", "distance"}`, the other elements it could be), `headline` and `warning`
    (the owner's warning text, empty if none).
    """
    ...

def repairReference(
    obj: DocumentObject, property: str, index: int, candidate: str, force: bool = False, /
) -> None:
    """Set reference `index` of `obj`'s link property `property` to `candidate`.

    `candidate` must be one of the candidates or alternatives that getReferenceReport() lists
    for it, or its original; with `force`, any element of the target (a re-pick); raises
    ValueError otherwise. The reference loses its guess record, the owner its warning, and the
    owner is touched (ops#127). The reference is written as the solver writes a resolution, so the
    owner follows it (a sketch moves its external geometry to the candidate). In a
    PropertyLinkSub, a candidate that another reference of the property already names is not
    added twice: the repaired reference goes. The property's report is cleared until the next
    update, so a second broken reference of it is repaired after a recompute.
    """
    ...

def acceptReference(obj: DocumentObject, property: str, index: int, /) -> None:
    """Accept the guess that reference `index` of `obj`'s link property `property` holds (ops#127).

    The element it holds becomes the reference: its guess record goes (with the records of the
    other pieces of the same expanded reference), its fingerprint is measured from that element,
    the owner's warning is cleared and the owner touched. Raises ValueError for a reference
    without a record.
    """
    ...

def markReferenceBroken(obj: DocumentObject, property: str, index: int, /) -> None:
    """Mark the guess that reference `index` of `obj`'s link property `property` holds as wrong.

    The reference goes back to its original, missing (`?Edge5`), so the owner fails at its next
    recompute (the other pieces of the same expanded reference go). Its record becomes a
    rejection (`guess_kind` `rejected`, the rejected elements in `alternatives`): the solver never
    offers them for it again, and it snaps back if the original's name gives an element again.
    Raises ValueError for a reference without a record.
    """
    ...
