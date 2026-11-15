// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// The generic step of a tool-making studio feature in one part (FreeCAD-CH ops#654,
// notes/parts-design.md 3.1 and 10.8): it applies its owner's tool (StudioOwner) to its base by
// Operation (Union, Subtraction or Common; Union with no base is a New result), then refines.
// One class for the extrude family, Hole, Revolution, Loft, Sweep, Helix, patterns and Booleans.
// Its names come from its owner's tool, so a step made again in the same place makes the same
// names (requirement 1, decision 335). A result of several solids is an error until pieces
// become parts (P6p): a Body never goes on with two solids.

#include "FeatureAddSub.h"

namespace PartDesign
{

class PartDesignExport FeatureApply: public FeatureAddSub
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::FeatureApply);

public:
    FeatureApply();

    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;
    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProvider";
    }

    /// The owner's tool in the document's frame: an owner's AddSubShape placed by its Placement,
    /// or a shape object's Shape; null when the owner has none (an error)
    static Part::TopoShape toolOf(const App::DocumentObject* owner, std::string* why = nullptr);
};

}  // namespace PartDesign
