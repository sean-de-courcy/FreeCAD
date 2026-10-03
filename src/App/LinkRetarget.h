// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

namespace App
{

class DocumentObject;

/** Lets the element references through \a link follow its new target (ops#42).
 *
 * Called when a Link's LinkedObject is set to another object: not on restore or undo, nor when
 * the target's document is opened or closed, since the shadows still name the target's elements
 * then (the refresh after opening resolves them, ops#40).
 *
 * A reference whose path passes through \a link keeps only its index, and is registered under
 * the new target, whose shape resolves it: at once if the target has an element map, or at its
 * first recompute (a copy-on-change copy has none until then). Its shadow then names an element
 * of the new target, so the saved file reopens as the session shows it, and the old target's
 * names are not looked up in the new one.
 *
 * \a oldTarget is the link's target before the change, if known. A reference's first resolution
 * on the new target is then checked against the element it named there: the index is kept only
 * if the new element has the same type, kind and direction, else the reference is marked
 * missing, never moved to another element (ops#106).
 *
 * Defined in PropertyLinks.cpp.
 */
void followLinkRetarget(DocumentObject* link, DocumentObject* oldTarget);

}  // namespace App
