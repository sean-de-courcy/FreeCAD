// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Onshape's Derived feature inside one document (FreeCAD-CH ops#640 round 6,
// notes/onshape-tabs-design.md 2.5, slice 3). A Derived feature brings parts of another studio
// (Part::BodyBase::studioOf(): an App::Part, or the document's top level, "Part Studio 1") into
// this one: one new Body per part, built on a SubShapeBinder of the source part as its
// BaseFeature, so it follows the source on every recompute. Each new Body's FeatureBase is a
// member of the feature (its DerivedFrom names the source); the last one made is the lead, whose
// row in the Features list stands for the whole feature, and its DerivedParts lists the others.
// Another document's saved studio as a source (notes/derived-design.md 3): the part's shape is
// copied into a Part::Feature held by this studio (a derived copy, isDerivedCopy()), which the
// member takes as its BaseFeature instead of a binder; freecad.derived makes and refreshes the
// copies, as Onshape's reference to another document's version changes only on an update.

#include <string>
#include <vector>

#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class Document;
class DocumentObject;
class Part;
}  // namespace App

namespace Part
{
class Feature;
}  // namespace Part

namespace PartDesign
{

class Body;
class FeatureBase;

/// The studios of doc that hold a part to derive: null (the document's top level) when it has
/// one, then the App::Parts that are studios, in the document's order
PartDesignExport std::vector<App::Part*> derivedStudios(App::Document* doc);

/// The name of doc's studio: its Label, the implicit studio's label for the document's top level
/// (App::DocumentTabs::implicitLabel(), "Part Studio 1" by default)
PartDesignExport std::string studioLabel(const App::Document* doc, const App::Part* studio);

/** Why a Derived feature can't bring parts from studio from into studio to (null: the top level):
 * the two are placed differently (their Placement and their containers'), so the copy, which keeps
 * the source's place in the document, would not keep its place in its studio as Onshape's does
 * (review R6-2). Empty when they are placed alike.
 */
PartDesignExport std::string derivedPlacementProblem(const App::Document* doc,
                                                     const App::Part* from,
                                                     const App::Part* to);

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
 * for no source, a source that isn't a part of another studio, sources of several studios, a
 * source studio placed differently (derivedPlacementProblem()), or a source that depends on an
 * object of studio (a circular reference: the studios would read each other).
 * Opens no transaction and doesn't recompute the document. Returns the lead.
 */
PartDesignExport FeatureBase* makeDerived(App::Document* doc, App::Part* studio, const std::vector<Body*>& sources);

/** Makes lead's Derived feature bring in sources instead (of any other studio): members whose
 * source stays are kept, the others removed as deleteDerivedParts() removes them, new ones made
 * for the new sources. When lead goes, the last member kept (else the last one made) becomes the
 * lead with its label and its place in the studio's history (its HistoryRank).
 * Same refusals as makeDerived(). Returns the lead after the edit.
 */
PartDesignExport FeatureBase* editDerived(FeatureBase* lead, const std::vector<Body*>& sources);

/** What deleting lead's Derived feature removes besides lead itself: its other members, every
 * member's binder, and each member's Body left with nothing else. Lead's Body, when lead is all
 * it holds, goes too: lead is then in no Body, for the caller to remove (Std_Delete does).
 * Opens no transaction and doesn't recompute.
 */
PartDesignExport void deleteDerivedParts(FeatureBase* lead);

/// Whether obj is a derived copy: a Part::Feature (not a PartDesign feature) with a
/// DerivedSourcePart property, holding a part of another document's saved studio
PartDesignExport bool isDerivedCopy(const App::DocumentObject* obj);

/// The name of a derived copy's part: its DerivedSourceLabel, else its DerivedSourcePart
PartDesignExport std::string derivedCopyLabel(const App::DocumentObject* copy);

/** Makes a Derived feature in studio (null: the document's top level) on copies, derived copies
 * that studio holds, of one studio of one file: per copy a Body in studio labelled as its part,
 * whose base is the copy. Throws Base::ValueError, before anything is written, for no copy, an
 * object that is no derived copy of doc, a copy that studio doesn't hold, copies of several
 * studios or files, or a copy chosen twice. Opens no transaction, doesn't recompute. Returns the
 * lead.
 */
PartDesignExport FeatureBase* makeDerivedCopies(App::Document* doc,
                                                App::Part* studio,
                                                const std::vector<Part::Feature*>& copies);

/// As editDerived() for a Derived feature on derived copies: lead's feature brings in copies
/// instead, with makeDerivedCopies()'s refusals. Returns the lead after the edit
PartDesignExport FeatureBase* editDerivedCopies(FeatureBase* lead,
                                                const std::vector<Part::Feature*>& copies);

}  // namespace PartDesign
