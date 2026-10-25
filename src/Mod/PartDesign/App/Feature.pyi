# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from Base.Metadata import export
from Part.PartFeature import PartFeature
from typing import Optional, overload

@export(
    Include="Mod/PartDesign/App/Feature.h",
    FatherInclude="Mod/Part/App/PartFeaturePy.h",
)
class Feature(PartFeature):
    """
    This is the father of all PartDesign object classes

    Author: Juergen Riegel (FreeCAD@juergen-riegel.net)
    Licence: LGPL
    """

    @overload
    def getBaseObject(self) -> Optional[object]:
        """
        getBaseObject: returns feature this one fuses itself to, or None. Normally, this should be the same as BaseFeature property, except for legacy workflow. In legacy workflow, it will look up the support of referenced sketch.
        """
        ...

    def getBaseObject(self) -> Optional[object]:
        """
        getBaseObject: returns feature this one fuses itself to, or None. Normally, this should be the same as BaseFeature property, except for legacy workflow. In legacy workflow, it will look up the support of referenced sketch.
        """
        ...

    def checksBase(self) -> bool:
        """
        checksBase(): whether this feature's next boolean checks its base, and repairs it if invalid. False when the base feature's own boolean, in its last recompute, ran with every input valid and nothing rebuilt its result unchecked since (FreeCAD-CH ops#310, ops#474).
        """
        ...
