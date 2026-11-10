// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

namespace App
{

class Document;
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

/** Adds  doc's references into other documents to those resolveReregisteredReferences()
 * resolves: File > Revert of a document with an older naming revision, whose references take
 * the consumer pass then, those through an App::Link too (ops#124). Called by
 * Document::restore(); defined in PropertyLinks.cpp.
 */
void queueReferencesIntoOtherDocuments(const Document* doc);

/** Takes again the records that a refresh held back while their target was still to be
 * recomputed (ops#564), at the end of \a doc's recompute: those whose target the recompute made,
 * of every document but one whose own recompute is still running. With \a doc null, after the
 * recompute of \a recomputed alone, outside a document's (it leaves the feature touched), the
 * held records whose closure holds it. Called by Document::recompute() and
 * Document::recomputeFeature(); defined in PropertyLinks.cpp.
 */
void updateHeldElementFingerprints(const Document* doc,
                                   const DocumentObject* recomputed = nullptr);

/** Holds the records of the references into \a target, an object in error that a recompute left
 * unmade (it failed without running, or ran and failed with no rule claiming it): the next
 * updateHeldElementFingerprints() takes them as a setter's, with the marks of the model as it is
 * then (ops#579, decision 256). Its shape is its last one, so the element resolves by its name;
 * the marks are what changes: a line drawn while the target was down reads as there before, and
 * one slid onto a vacated place later breaks, as without the failure (ops#585). Defined in
 * PropertyLinks.cpp.
 */
void holdElementReferencesInto(DocumentObject* target);

/** Takes the records of the references into  target now, as the end of its recompute would:
 *  target, an object the recompute stopped, has its last shape only until the rule's
 * afterStop() (F37 writes a stopped Body empty), and a record taken from an empty shape keeps its
 * old marks (ops#652). Its closure is made, since it sorts before it. A reference that also links
 * an object still to be recomputed waits for the end, as before. Called by Document::recompute();
 * defined in PropertyLinks.cpp.
 */
void takeElementReferencesInto(DocumentObject* target);

}  // namespace App
