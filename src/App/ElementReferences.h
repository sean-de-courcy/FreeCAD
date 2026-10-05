// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

namespace App
{

class DocumentObject;

/** Drops \a feature from the element reference registry (ops#119, ops#120).
 *
 * Link properties register their element references under the feature that holds the
 * referenced element, which can be an object of another document reached through an App::Link.
 * When that feature is destroyed (its document closes, or it is deleted outside the undo
 * history), the properties still referencing it stop being registered under it, so no key of
 * the registry outlives its object. Called by ~DocumentObject(); defined in PropertyLinks.cpp.
 */
void forgetElementReferencesTo(const DocumentObject* feature);

/** Resolves the references that an attach registered again while a document was restored
 * outside an open (File > Revert): an open resolves them at its end, a revert has no such step
 * (ops#120). Called by Document::restore(); defined in PropertyLinks.cpp.
 */
void resolveReregisteredReferences();

}  // namespace App
