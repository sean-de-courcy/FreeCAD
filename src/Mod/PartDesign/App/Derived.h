// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Onshape's Derived feature inside one document (FreeCAD-CH ops#640 round 6,
// notes/onshape-tabs-design.md 2.5, slice 3). A Derived feature brings parts of another studio
// (Part::BodyBase::studioOf(): an App::Part, or the document's top level, "Part Studio 1") into
// this one: one new Body per part, built on a SubShapeBinder of the source part as its
// BaseFeature, so it follows the source on every recompute. Each new Body's FeatureBase is a
// member of the feature (its DerivedFrom names the source); the last one made is the lead, whose
// row in the Features list stands for the whole feature, and its DerivedParts lists the others.
// Other documents and versions as a source are not in this slice.

#include <string>
#include <vector>

#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class Document;
class DocumentObject;
class Part;
}  // namespace App

namespace PartDesign
{

class Body;
class FeatureBase;

/// The studios of doc that hold a part to derive: null (the document's top level) when it has
/// one, then the App::Parts that are studios, in the document's order
PartDesignExport std::vector<App::Part*> derivedStudios(App::Document* doc);

/// The studio's name: its Label, "Part Studio 1" for the document's top level
PartDesignExport std::string studioLabel(const App::Part* studio);

/// The parts of studio a Derived feature can bring in: its Bodies with a shape that no Delete part
/// deleted, in the document's order
PartDesignExport std::vector<Body*> derivableParts(App::Document* doc, App::Part* studio);

/// How a Derived feature names its source in a message: "Body (Part Studio 1)"
PartDesignExport std::string derivedDescription(const App::DocumentObject* source);

/// Whether obj is a member of a Derived feature (a FeatureBase with DerivedFrom set)
PartDesignExport bool isDerived(const App::DocumentObject* obj);

/// The lead of obj's Derived feature (the member whose row stands for it), or null when obj is no
/// member
PartDesignExport FeatureBase* derivedLead(const App::DocumentObject* obj);

/// The members of lead's Derived feature: the others in their order, then lead
PartDesignExport std::vector<FeatureBase*> derivedMembers(FeatureBase* lead);

/// The part a member copies (its binder's support), or null when the source is missing
PartDesignExport App::DocumentObject* derivedSource(const FeatureBase* member);

/** Makes a Derived feature in studio (null: the document's top level) of sources, parts of one
 * other studio of doc: per source a binder and a Body in studio, the Body labelled as its source.
 * The lead's label is "Derived N", the lowest N free in the document. A studio rolled back gets
 * the members at its bar (Body::addObject). Throws Base::ValueError, before anything is written,
 * for no source, a source that isn't a part of another studio, or sources of several studios.
 * Opens no transaction and doesn't recompute the document. Returns the lead.
 */
PartDesignExport FeatureBase* makeDerived(App::Document* doc, App::Part* studio, const std::vector<Body*>& sources);

/** Makes lead's Derived feature bring in sources instead (of any other studio): members whose
 * source stays are kept, the others removed as deleteDerivedParts() removes them, new ones made
 * for the new sources. When lead goes, the last member left becomes the lead with its label.
 * Same refusals as makeDerived(). Returns the lead after the edit.
 */
PartDesignExport FeatureBase* editDerived(FeatureBase* lead, const std::vector<Body*>& sources);

/** What deleting lead's Derived feature removes besides lead itself: its other members, every
 * member's binder, and each member's Body left with nothing else. Lead's Body, when lead is all
 * it holds, goes too: lead is then in no Body, for the caller to remove (Std_Delete does).
 * Opens no transaction and doesn't recompute.
 */
PartDesignExport void deleteDerivedParts(FeatureBase* lead);

}  // namespace PartDesign
