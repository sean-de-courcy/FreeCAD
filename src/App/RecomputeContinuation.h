// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <memory>
#include <string>

namespace App
{

class DocumentObject;

/// What Document::recompute does with an object about to run whose input is in error (ops#126)
enum class AfterInputFailure
{
    Run,   ///< recompute it as usual
    Fail,  ///< fail it without running it, with the text the rule gives
    Skip   ///< leave it and its in-list out of this recompute, as upstream does after a failure
};

/** A module's rule for objects that fail without stopping the recompute (ops#126).
 *
 * Without a rule, a failed object filters its whole in-list out of the recompute (upstream). With
 * one, an object the rule claims (continuesAfter()) keeps its error, is purged like a success, and
 * its dependants run and are judged by decide(). PartDesign sets the rule for the members of a
 * Body: a failed solid feature passes its base shape through and the features after it compute.
 */
class AppExport RecomputeContinuation
{
public:
    virtual ~RecomputeContinuation() = default;

    /// 'failed' is in error (from this recompute or an earlier one): do its dependants run
    /// (true), or is its in-list skipped as upstream does (false)?
    virtual bool continuesAfter(const DocumentObject* failed) const = 0;

    /// 'dependant' is about to recompute and links to 'failed', for which continuesAfter() is
    /// true: Run it, Fail it (with 'why' as its error text), or Skip it with its in-list
    virtual AfterInputFailure decide(const DocumentObject* failed,
                                     const DocumentObject* dependant,
                                     std::string& why) const = 0;

    /// 'failed' has just failed, for whatever reason (its own error, an exception, an expression,
    /// a Fail from decide()), and continuesAfter() is true: write the output its dependants are
    /// to see (PartDesign: the pass-through). Called once per failure, before the dependants run.
    /// Must not throw.
    virtual void afterFailure(DocumentObject* failed) const = 0;
};

/// Set once at module load (PartDesign's init); null means upstream's behaviour everywhere.
/// A second call replaces the rule and warns.
AppExport void setRecomputeContinuation(std::shared_ptr<const RecomputeContinuation> rule);
AppExport std::shared_ptr<const RecomputeContinuation> recomputeContinuation();

}  // namespace App
