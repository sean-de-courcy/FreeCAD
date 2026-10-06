# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from Base.Metadata import export
from Part.BodyBase import BodyBase
from typing import Final

@export(
    Include="Mod/PartDesign/App/Body.h",
    FatherInclude="Mod/Part/App/BodyBasePy.h",
)
class Body(BodyBase):
    """
    PartDesign body class

    Author: Juergen Riegel (FreeCAD@juergen-riegel.net)
    Licence: LGPL
    """

    VisibleFeature: Final[object] = ...
    """Return the visible feature of this body"""

    def insertObject(self, feature: object, target: object, after: bool = False, /) -> None:
        """
        Insert the feature into the body after the given feature.

        @param feature  The feature to insert into the body
        @param target   The feature relative which one should be inserted the given.
          If target is NULL than insert into the end if where is InsertBefore
          and into the begin if where is InsertAfter.
        @param after    if true insert the feature after the target. Default is false.

        @note the method doesn't modify the Tip unlike addObject()
        """
        ...

    def rollTo(self, feature: object, /) -> None:
        """
        Move the roll-back bar (the Tip) after the given solid feature of this body, or to the
        top with None (FreeCAD-CH ops#127). The features after the bar are held: not
        recomputed until the bar passes them again. Opens no transaction.
        """
        ...

    def rollToEnd(self) -> None:
        """Move the roll-back bar (the Tip) to the last solid feature (ops#127)."""
        ...

    def isRolledBack(self) -> bool:
        """True if the roll-back bar is not at the last solid feature (ops#127)."""
        ...

    def holds(self, obj: object, /) -> bool:
        """
        True if the roll-back bar holds the object (ops#127): a solid feature after the bar, a
        member after it that no feature above the bar uses, or the body while rolled back.
        """
        ...

    def setEditRollPoint(self, feature: object, /) -> None:
        """
        Set the transient edit roll-back point (None clears it), which the bar follows while it
        is set (ops#127). Not saved and not undone; touches nothing.
        """
        ...

    def reorderObject(self, objects: object, target: object, after: bool = True, /) -> None:
        """
        Move one or several members before or after target (a member, or None for the start)
        in one step (ops#127): the BaseFeature chain is rewired, the references that follow a
        feature's base are rerouted, references from a feature's own inputs into a solid that
        now comes after it are re-targeted or set aside (and restored when the order allows),
        and the Tip keeps its place in the list. Raises ValueError with nothing changed when the
        order is refused. Opens no transaction and doesn't recompute.
        """
        ...
