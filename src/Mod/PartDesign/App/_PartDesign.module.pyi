# SPDX-License-Identifier: LGPL-2.1-or-later

"""Typed public signatures for the private ``_PartDesign`` helper module.

This source-adjacent stub file carries the geometric helper that is exposed by
the low-level PartDesign extension module.
"""

from __future__ import annotations

from typing import TypeAlias

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
