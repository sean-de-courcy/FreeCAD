// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Split (FreeCAD-CH ops#325, B+ Stage 1 session 4, notes/bplus-stage1-design.md 2.7)

#include <string>
#include <vector>

#include <gp_Pln.hxx>

#include <App/PropertyGeo.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>

#include "FeatureRefine.h"

namespace PartDesign
{

class Body;

/** One side of a plane: a part split in two.
 *
 * The original part's Split comes after its Tip and keeps one side of `Tool` (an origin plane, a
 * datum plane or a planar face). The new part's first feature is a Split with `NewHalf` set and
 * `Partner` linking the original's: at execute it reads its partner's current base, Tool and
 * Side, and keeps the other side. A feature inserted before the original's Split re-bases that
 * Split, and the new part follows on the next recompute. The link goes one way, new half to
 * original, so there is no cycle.
 */
class PartDesignExport Split: public PartDesign::FeatureRefine
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::Split);

public:
    Split();

    /// The plane: an origin plane, a datum plane or a planar face, of a part of the studio
    App::PropertyLinkSub Tool;
    /// Which side of the plane stays: Front (where its normal points) or Back
    App::PropertyEnumeration Side;
    /// The new half's: the original's Split, whose base, Tool and Side it reads
    App::PropertyLink Partner;
    /// Set on the new half's Split: its own Tool and Side are unused
    App::PropertyBool NewHalf;
    /// Where the partner's Body was, in this one's frame, at the last compute (new half only)
    App::PropertyPlacement PartnerFrame;
    /// Where the plane's object was, in this one's frame, at the last compute: a move of the
    /// Tool's own part is seen by no link (the partner's Tool, for the new half)
    App::PropertyPlacement ToolFrame;

    App::DocumentObjectExecReturn* recompute() override;
    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;
    void onChanged(const App::Property* prop) override;
    void onDocumentRestored() override;
    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderSplit";
    }

    /// The original's Split this one reads (new half), or null
    Split* partnerSplit() const;

    /// Splits @p body by @p tool (its @p subs, empty for a plane): a Split at its end keeping
    /// @p side, and a new Body, placed as @p body in its container, whose first feature is a
    /// Split keeping the other side. A Body as @p tool stands for its Tip. Refused, with the
    /// reason, before anything changes. Returns
    /// the new Body; no recompute.
    static Body* makeSplit(
        App::DocumentObject* body,
        App::DocumentObject* tool,
        const std::vector<std::string>& subs,
        const char* side
    );

    /// The plane of @p tool / @p sub in the coordinates of @p owner's Body (the document's when
    /// it is in none), its normal out of the face or along the plane's Z. Throws when it isn't
    /// an origin plane, a datum plane or a planar face.
    static gp_Pln toolPlane(
        const Feature* owner,
        const App::DocumentObject* tool,
        const std::string& sub
    );

private:
    /// Where the partner's Body is in this Body's frame
    Base::Placement partnerFrame() const;
    /// Where the Tool this Split cuts by (the partner's, for the new half) is in this Body's frame
    Base::Placement toolFrame() const;
    /// Whether this Split, or the new half's partner, is held by its rolled-back Body
    bool waits() const;

    static const char* SideEnums[];
};

}  // namespace PartDesign
