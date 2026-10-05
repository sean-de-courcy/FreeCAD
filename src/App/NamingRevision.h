// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

namespace App
{

class Document;

/** The naming revision of a document's references (ops#116).
 *
 * A file saves `NamingRevision` on its `Document` element: the fork's naming revision
 * (ForkNamingRevision) of the names its references hold. Files saved before ops#116 have none
 * and count as 0, i.e. older than any build. When a document opened with an older revision
 * references a producer in another document whose names are already current, the end of
 * Application::openDocuments() re-derives those references from their geometry instead of
 * following their names (PropertyLinkBase::updateAllElementReferences()).
 *
 * Defined in Document.cpp, except namingRevisionToSave() (PropertyLinks.cpp).
 */

/// This build's naming revision.
int forkNamingRevision();

/// The revision \a doc's references were last resolved under: the file's when it was opened, the
/// one its last save wrote, or this build's for a new document.
int namingRevisionOf(const Document* doc);

/// Whether \a doc was opened with an older revision than this build's and the references pass
/// at the end of the open hasn't run since.
bool openedWithOlderNaming(const Document* doc);

/// Whether any document is openedWithOlderNaming(): the pass's whole cost for current files.
bool anyOpenedWithOlderNaming();

/// Ends openedWithOlderNaming() for every document (the pass has run), whose revision becomes
/// namingRevisionToSave()'s.
void endOpenedWithOlderNaming();

/// The revision \a doc saves: this build's, lowered to the oldest revision among the producers
/// in other documents that its references hold names of (a producer not yet migrated), and to its
/// own revision while it holds references into a document that isn't open.
int namingRevisionToSave(const Document* doc);

}  // namespace App
