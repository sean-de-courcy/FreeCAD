// SPDX-License-Identifier: LGPL-2.1-or-later

#ifndef APP_ELEMENTSOLVEREDITS_H
#define APP_ELEMENTSOLVEREDITS_H

// The edits since a document was opened (ops#475, PLAN decision 217): a naming migration keeps a
// reference by its saved place only where nothing in its feature's chain changed before the
// migration recompute. FreeCADApp's own: not exported.

#include <string>

namespace Data
{
struct ElementFingerprint;
}

namespace App
{

class Document;
class DocumentObject;
class GeoFeature;
class Property;
class PropertyContainer;

/// A document starts restoring, or is made or deleted: it has no edits.
void forgetEditsSinceOpen(const Document* doc);
/// \a obj was saved touched: an edit the file brings.
void noteEditSinceOpen(const DocumentObject* obj);
/// \a prop of \a obj changed: an edit unless restored, recomputed, written by the reference
/// solver, an output or transient (a placement counts, though it needs no recompute).
void noteChangeSinceOpen(const DocumentObject* obj, const Property* prop);
/// Whether \a feature or anything it depends on was edited since its document was opened, or
/// depends on another document's object (whose edits no record here shows).
bool editedSinceOpen(const DocumentObject* feature);

/** The digests of one recompute (perf profile 1, `notes\recompute-cost.md`, ops#640).
 *
 * placementSources() folds every object of a target's chain into a digest, and runs about three
 * times per re-executed feature: without a cache, an edit of an early feature costs O(N^2) in the
 * feature count. While a scope is open on this thread (a document's recompute; nested scopes
 * share the outermost one), each object's digest is made once and kept until a property of the
 * object changes (forgetPlacementDigest()), so the values are the ones a fresh digest gives.
 * A scope opened on another thread meanwhile keeps nothing. `FREECAD_CH_DIGEST_CACHE=off` turns
 * the cache off, `=verify` makes each digest again and reports a kept one that differs.
 */
class PlacementDigestScope
{
public:
    PlacementDigestScope();
    ~PlacementDigestScope();
    PlacementDigestScope(const PlacementDigestScope&) = delete;
    PlacementDigestScope& operator=(const PlacementDigestScope&) = delete;

private:
    bool active = false;
};
/// \a obj's properties changed (a value, a status, the list) or \a obj is going: its kept
/// digests are dropped.
void forgetPlacementDigest(const void* obj);
/// The same for a property's container (a document object's, else nothing), at the cost of an
/// atomic read while no scope is open: Property's setters call it.
void forgetPlacementDigestOf(const PropertyContainer* container);

/** The fingerprints of its target's elements that the running solveElementReferences() measured
 * (perf profile 2, `notes\recompute-cost.md`, ops#640): its write-back's records take the same
 * measurement of the same shape, which on a face with many holes costs milliseconds. Kept for that
 * call only, by element name, and not used once a property of the target has changed
 * (forgetPlacementDigestOf()). Whether one is kept for \a element of \a geo; \a measured then says
 * whether getElementFingerprint() gave one, and \a fingerprint holds it.
 */
bool batchElementFingerprint(const GeoFeature* geo,
                             const std::string& element,
                             bool& measured,
                             Data::ElementFingerprint& fingerprint);
/// Keeps getElementFingerprint()'s result for \a element of \a geo, if it is the running
/// solveElementReferences()'s target.
void keepBatchElementFingerprint(const GeoFeature* geo,
                                 const std::string& element,
                                 bool measured,
                                 const Data::ElementFingerprint& fingerprint);

/// The solver's sites timed by SolverSiteTimer (perf profile 2, ops#640).
enum class SolverSite
{
    UpdateReferences,  // PropertyLinkBase::updateElementReferences(), whole
    Solve,             // solveElementReferences(), whole
    Pass1,             // its exact lookup, per property
    Pass2Frames,       // its loop over the entries: frames and sources
    Pool,              // poolOf()
    Measure,           // the batch's getElementFingerprint() of the target's elements
    SolveOwner,        // Data::solveOwner()
    WriteBack,         // applyResolutions() and the reports
    Update,            // _updateElementFingerprints(), whole
    UpdateCompare,     // its fromString() and comparisons
    Fingerprint,       // elementFingerprint(), whole
    FpResolve,         // its resolveElement()
    FpGet,             // its getElementFingerprint()
    FpTwin,            // elementTwinCentroid()
    FpUpTo,            // elementUpToFaces()
    FpClosure,         // the closure and its marks
    FpSources,         // placementSources()
    FpString,          // toString()
    Held,              // updateHeldElementFingerprints()
    Count
};
/** Adds the seconds from its making to its end, and a call, to \a site, while
 * `FREECAD_CH_SOLVER_PROFILE` was set when the outermost PlacementDigestScope on this thread
 * opened; that scope's end logs every site (`solver profile:`, PropertyLinks log level). Times are
 * inclusive (a site inside another counts in both).
 */
class SolverSiteTimer
{
public:
    explicit SolverSiteTimer(SolverSite site);
    ~SolverSiteTimer();
    SolverSiteTimer(const SolverSiteTimer&) = delete;
    SolverSiteTimer& operator=(const SolverSiteTimer&) = delete;

private:
    int site = -1;
    long long start = 0;
};

}  // namespace App

#endif  // APP_ELEMENTSOLVEREDITS_H
