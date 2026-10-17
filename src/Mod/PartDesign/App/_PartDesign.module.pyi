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
