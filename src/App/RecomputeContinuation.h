// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <memory>
#include <string>
#include <vector>

namespace App
{

class DocumentObject;

/// What Document::recompute does with an object about to run whose input is in error (ops#126)
enum class AfterInputFailure
{
    Run,  ///< recompute it as usual
    Fail  ///< fail it without running it, with the text the rule gives
};

/** A module's rule for objects that fail without stopping the recompute (ops#126).
 *
 * A failed object that no rule claims stays touched, and its dependants fail without running,
 * naming it (ops#579; upstream left them out of the recompute, Valid on its old output). An
 * object the rule claims (continuesAfter()) keeps its error, is purged like a success, and its
 * dependants run and are judged by decide(). PartDesign sets the rule for the members of a Body:
 * a failed solid feature passes its base shape through and the features after it compute.
 */
class AppExport RecomputeContinuation
{
public:
    virtual ~RecomputeContinuation() = default;

    /// 'failed' is in error (from this recompute or an earlier one): do its dependants run and
    /// get judged by decide() (true), or do they fail, naming it (false)?
    virtual bool continuesAfter(const DocumentObject* failed) const = 0;

    /// 'dependant' is about to recompute and links to 'failed', for which continuesAfter() is
    /// true: Run it, or Fail it (with 'why' as its error text)
    virtual AfterInputFailure decide(const DocumentObject* failed,
                                     const DocumentObject* dependant,
                                     std::string& why) const = 0;

    /// 'failed' has just failed, for whatever reason (its own error, an exception, an expression,
    /// a Fail from decide()), and continuesAfter() is true: write the output its dependants are
    /// to see (PartDesign: the pass-through). Called once per failure, before the dependants run.
    /// Must not throw.
    virtual void afterFailure(DocumentObject* failed) const = 0;

    /// FreeCAD-CH (ops#640, F37): 'stopped' failed without running (a Fail verdict on an input in
    /// error, or blocked()) and continuesAfter() is false for it: no rule claims it, so its
    /// dependants fail naming it. The rule may write what the view shows of it (PartDesign: a
    /// Body stopped on an unclaimed failure of its Tip writes an empty Shape, as Onshape shows no
    /// part when its base feature fails); its error stays. Called once per stop, before its
    /// dependants are judged. Must not throw.
    virtual void afterStop(DocumentObject* stopped) const
    {
        (void)stopped;
    }

    /// 'obj' is held: Document::recompute doesn't run it, leaves it touched, and doesn't count it
    /// as touched in Document::mustExecute() (ops#127; PartDesign: what a Body's roll-back bar
    /// holds, and the Body itself while rolled back)
    virtual bool holds(const DocumentObject* obj) const
    {
        (void)obj;
        return false;
    }

    /// 'obj' can't run (ops#127; PartDesign: a reference of it is parked by a reorder): it fails
    /// before running, with 'why' as its error text, and the recompute continues as after any
    /// failure
    virtual bool blocked(const DocumentObject* obj, std::string& why) const
    {
        (void)obj;
        (void)why;
        return false;
    }

    /// A feature of a target's shape-input chain that can pass its base through (ops#549)
    struct ChainFeature
    {
        const DocumentObject* object = nullptr;
        /// In error and claimed (continuesAfter()): its output is its base, until it computes
        bool failed = false;
        /// Suppressed: its output is its base, as if it were removed
        bool suppressed = false;
    };

    /// The features whose output 'target''s shape is built on and that can pass their base
    /// through, nearest first, from their current state (ops#549; PartDesign: the Body solid
    /// features of the BaseFeature chain and of the solid features' links, through a Body's Tip,
    /// binders and links). Empty without a rule.
    virtual void shapeInputChain(const DocumentObject* target, std::vector<ChainFeature>& out) const
    {
        (void)target;
        out.clear();
    }
};

/// Set once at module load (PartDesign's init); null means upstream's behaviour everywhere.
/// A second call replaces the rule and warns.
AppExport void setRecomputeContinuation(std::shared_ptr<const RecomputeContinuation> rule);
AppExport std::shared_ptr<const RecomputeContinuation> recomputeContinuation();

}  // namespace App
