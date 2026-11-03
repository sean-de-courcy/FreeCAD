// SPDX-License-Identifier: LGPL-2.1-or-later

#ifndef APP_ELEMENTSOLVEREDITS_H
#define APP_ELEMENTSOLVEREDITS_H

// The edits since a document was opened (ops#475, PLAN decision 217): a naming migration keeps a
// reference by its saved place only where nothing in its feature's chain changed before the
// migration recompute. FreeCADApp's own: not exported.

namespace App
{

class Document;
class DocumentObject;
class Property;

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

}  // namespace App

#endif  // APP_ELEMENTSOLVEREDITS_H
