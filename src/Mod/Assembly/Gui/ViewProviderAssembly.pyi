# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from typing import Any, List, Tuple, TypeAlias

from Base.Metadata import export
from App.DocumentObject import DocumentObject
from Gui.ViewProvider import ViewProvider

SoTransformDragger: TypeAlias = Any

@export(Include="Mod/Assembly/Gui/ViewProviderAssembly.h", Namespace="AssemblyGui")
class ViewProviderAssembly(ViewProvider):
    """
    This is the ViewProviderAssembly class

    Author: Ondsel (development@ondsel.com)
    License: LGPL-2.1-or-later
    """

    def isInEditMode(self) -> Any:
        """
        Return true if the assembly object is currently in edit mode.
        """
        ...

    def getDragger(self) -> SoTransformDragger:
        """Return the assembly dragger coin object."""
        ...

    def isolateComponents(
        self, components: List[DocumentObject] | Tuple[DocumentObject, ...], mode: int, /
    ) -> None:
        """
        Temporarily isolates a given set of components in the 3D view.
        Other components are faded or hidden based on the specified mode.

        Args:
            components (List[DocumentObject] | Tuple[DocumentObject, ...]):
                A list or tuple of DocumentObjects to isolate.
            mode (int): An integer specifying the isolation mode:
                - 0: Transparent
                - 1: Wireframe
                - 2: Hidden
        """
        ...

    def clearIsolate(self) -> None:
        """
        Restores the visual state of all components, clearing any active isolation.
        """
        ...

    # FreeCAD-CH (ops#640, C8): the triad's typed moves
    def getTriadHandle(self) -> str:
        """
        The triad handle of the last drag: "None", "TranslateX", "TranslateY", "TranslateZ",
        "RotateX", "RotateY", "RotateZ" or "Plane".
        """
        ...

    def getTriadValue(self) -> float:
        """The distance (mm) or angle (degrees) the last arrow or ring drag moved from its start."""
        ...

    def getTriadPlacement(self) -> Any:
        """The triad's exact placement (global)."""
        ...

    def applyTriadValue(self, text: str, /) -> bool:
        """
        Type a value into the triad's box: the last drag becomes exactly that distance or angle
        from where it started, in one undo step. False if the text doesn't evaluate.
        """
        ...

    def isTriadBoxOpen(self) -> bool:
        """Whether the triad's value box is open."""
        ...

    def closeTriadBox(self) -> None:
        """Close the triad's value box, keeping the move."""
        ...

    def dragTriad(self, handle: str, placement: Any, /) -> None:
        """
        A drag of the triad's @handle (as getTriadHandle names it) that ends with the triad at
        @placement (global): the dragger's start, motion and finish steps, without the mouse.
        """
        ...

    def moveTriadOriginTo(self, point: Any, subName: str = "", /) -> None:
        """
        Moves the triad alone to @point (global), on the assembly's axes, as Alt+click on a point
        does: the parts stay, and a ring then turns them about the point. With @subName (under the
        assembly, the element included, e.g. "Box.Edge3") the point snaps to that edge's end when
        close to one, as the Transform dialog's pick does.
        """
        ...
    EnableMovement: bool
    """Enable moving the parts by clicking and dragging."""

    MoveOnlyPreselected: bool
    """If enabled, only the preselected object will move."""

    MoveInCommand: bool
    """If enabled, each move will be wrapped in a command."""

    DraggerVisibility: bool
    """Show or hide the assembly dragger."""

    DraggerPlacement: Any
    """Placement of the assembly dragger object."""
