# SPDX-License-Identifier: LGPL-2.1-or-later

"""Typed public signatures for the private ``_PartDesign`` helper module.

This source-adjacent stub file carries the geometric helper that is exposed by
the low-level PartDesign extension module.
"""

from __future__ import annotations

from typing import Sequence, TypeAlias

from App.Document import Document
from App.DocumentObject import DocumentObject
from FreeCAD.Base import Vector

_FilletArcConstruction: TypeAlias = tuple[Vector, Vector, Vector]

def makeFilletArc(
    m1: Vector,
    p: Vector,
    q: Vector,
    n: Vector,
    radius: float,
    ccw: bool | int,
    /,
) -> _FilletArcConstruction:
    """Return the tangent points and arc center for one fillet-arc construction."""
    ...

def studioOf(obj: DocumentObject, /) -> DocumentObject | Document | None:
    """Return the studio of obj's Body: its App::Part, the document at the top level, or None."""
    ...

def isStudioPick(owner: DocumentObject, obj: DocumentObject, subname: str = "", /) -> bool:
    """Return whether owner may link the pick obj/subname directly, across Bodies of one studio."""
    ...

def isStudioProfile(owner: DocumentObject, obj: DocumentObject, subname: str = "", /) -> bool:
    """Return whether the pick may be the Profile of owner, a profile feature or a Body."""
    ...

def studioOriginFeature(owner: DocumentObject, feature: DocumentObject, /) -> DocumentObject | None:
    """Return owner's own origin feature standing for another Body's in the studio, or None."""
    ...

def makeSiblings(
    feature: DocumentObject, bodies: Sequence[DocumentObject], /
) -> list[DocumentObject]:
    """Make the subtractive feature's siblings the ones in bodies, other parts of its studio.

    One feature of its type per Body, on its profile: its parameters bound to it by expression,
    its links copied. Adds the missing ones, deletes the others, copies the links again. No
    recompute; returns the siblings in the order of bodies.
    """
    ...

def siblingsOf(feature: DocumentObject, /) -> list[DocumentObject]:
    """Return the siblings that follow feature."""
    ...

def unlinkSibling(sibling: DocumentObject, /) -> None:
    """Make the sibling independent: its expressions on its primary and SiblingOf are cleared."""
    ...

def makeMerge(at: DocumentObject, bodies: Sequence[DocumentObject], /) -> DocumentObject:
    """Merge bodies, other parts of the studio, into the part of at.

    at is a solid feature (the Merge goes right after it) or a Body (the Merge goes at its Tip).
    The Merge is a Fuse of the bodies' last solid features; each merged Body gets MergedInto and
    is hidden. No recompute; returns the Merge.
    """
    ...

def split(body: DocumentObject, tool: object, side: str = "Front", /) -> DocumentObject:
    """Split the part body by the plane tool, in two parts.

    tool is an origin plane, a datum plane, or (feature, "FaceN") for a planar face. A Split at
    body's end keeps side ("Front": where the plane's normal points, or "Back"); a new part placed
    as body gets the other side, from a Split that reads the first one's base, plane and side. No
    recompute; returns the new Body.
    """
    ...

def newPartFrom(feature: DocumentObject, /) -> DocumentObject:
    """Move feature, its Body's Tip that nothing else uses, into a new Body in the same container.

    Its Profile sketch moves along when nothing else uses it. No recompute; returns the new Body.
    """
    ...

def studioSequence(studio: Document | DocumentObject, /) -> list[DocumentObject]:
    """Return the features of every Body of the studio in history order (ops#602).

    studio is a document (its top level) or an App::Part. A feature comes after what it reads in
    other Bodies and after its Body's earlier members; the oldest comes first where that leaves a
    choice.
    """
    ...

def rollStudioTo(studio: Document | DocumentObject, feature: DocumentObject | None, /) -> None:
    """Move every Body's bar after its last solid feature at or above feature (None: the top).

    No transaction, no recompute.
    """
    ...

def rollStudioToEnd(studio: Document | DocumentObject, /) -> None:
    """Move every Body's bar of the studio to its end."""
    ...

def isStudioRolledBack(studio: Document | DocumentObject, /) -> bool:
    """Return whether some Body of the studio is rolled back."""
    ...

def studioBarAfter(studio: Document | DocumentObject, *hint: DocumentObject | None) -> DocumentObject | None:
    """Return the feature of studioSequence the studio's bar follows (None: the top).

    hint, the feature (None: the top) the bar was last moved after, is kept when only sketches and
    datums lie between it and the first held feature.
    """
    ...

# FreeCAD-CH (ops#640 round 6): Onshape's Derived inside one document (Derived.h)

def derivedStudios(doc: Document, /) -> list[Document | DocumentObject]:
    """Return the studios of doc that hold a part to derive: doc (its top level) first."""
    ...

def studioLabel(studio: Document | DocumentObject, /) -> str:
    """Return a studio's name: an App::Part's Label, the implicit studio's label for a document
    ("Part Studio 1" by default)."""
    ...

def derivableParts(studio: Document | DocumentObject, /) -> list[DocumentObject]:
    """Return the studio's Bodies with a shape that no Delete part deleted."""
    ...

def makeDerived(studio: Document | DocumentObject, bodies: list[DocumentObject], /) -> DocumentObject:
    """Make a Derived feature of bodies (parts of one other studio) in studio; return its lead.

    No transaction, no recompute.
    """
    ...

def editDerived(lead: DocumentObject, bodies: list[DocumentObject], /) -> DocumentObject:
    """Make the Derived feature bring in bodies instead; return its lead after the edit."""
    ...

def deleteDerivedParts(lead: DocumentObject, /) -> None:
    """Remove what the Derived feature made besides lead (lead is left for the caller)."""
    ...

def derivedLead(obj: DocumentObject, /) -> DocumentObject | None:
    """Return the lead of obj's Derived feature, or None."""
    ...

def derivedMembers(lead: DocumentObject, /) -> list[DocumentObject]:
    """Return the members of the Derived feature, lead last."""
    ...

def derivedSource(member: DocumentObject, /) -> DocumentObject | None:
    """Return the part a Derived member copies, or None when it is missing."""
    ...
