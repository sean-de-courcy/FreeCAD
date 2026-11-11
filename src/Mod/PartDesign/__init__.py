# SPDX-License-Identifier: LGPL-2.1-or-later

import _PartDesign

makeFilletArc = _PartDesign.makeFilletArc
studioOf = _PartDesign.studioOf
isStudioPick = _PartDesign.isStudioPick
isStudioProfile = _PartDesign.isStudioProfile
studioOriginFeature = _PartDesign.studioOriginFeature
newPartFrom = _PartDesign.newPartFrom
newPartRefusal = _PartDesign.newPartRefusal  # FreeCAD-CH, ops#640 round 5
addToPart = _PartDesign.addToPart
addToPartRefusal = _PartDesign.addToPartRefusal
deletePart = _PartDesign.deletePart
removeEmptyPart = _PartDesign.removeEmptyPart  # FreeCAD-CH, ops#640 rank 30 (F50)
makeSiblings = _PartDesign.makeSiblings
siblingsOf = _PartDesign.siblingsOf
unlinkSibling = _PartDesign.unlinkSibling
makeMerge = _PartDesign.makeMerge
setMergeScope = _PartDesign.setMergeScope
mergeAfter = _PartDesign.mergeAfter
consumerOf = _PartDesign.consumerOf
split = _PartDesign.split
studioSequence = _PartDesign.studioSequence
rollStudioTo = _PartDesign.rollStudioTo
rollStudioToEnd = _PartDesign.rollStudioToEnd
isStudioRolledBack = _PartDesign.isStudioRolledBack
studioBarAfter = _PartDesign.studioBarAfter
moveInStudio = _PartDesign.moveInStudio
# FreeCAD-CH, ops#640 round 6: Derived
derivedStudios = _PartDesign.derivedStudios
studioLabel = _PartDesign.studioLabel
derivableParts = _PartDesign.derivableParts
makeDerived = _PartDesign.makeDerived
editDerived = _PartDesign.editDerived
deleteDerivedParts = _PartDesign.deleteDerivedParts
derivedLead = _PartDesign.derivedLead
derivedMembers = _PartDesign.derivedMembers
derivedSource = _PartDesign.derivedSource
# FreeCAD-CH, ops#654: the studio's list, its projection and reconcile
studioList = _PartDesign.studioList
studioInsert = _PartDesign.studioInsert
studioRemove = _PartDesign.studioRemove
studioMove = _PartDesign.studioMove
studioSetBar = _PartDesign.studioSetBar
studioSetScope = _PartDesign.studioSetScope
studioSetScopeIds = _PartDesign.studioSetScopeIds
studioScopeIds = _PartDesign.studioScopeIds
studioScopeOf = _PartDesign.studioScopeOf
studioPartId = _PartDesign.studioPartId
studioSuppress = _PartDesign.studioSuppress
studioReconcile = _PartDesign.studioReconcile
studioProject = _PartDesign.studioProject
studioStepOf = _PartDesign.studioStepOf
studioNewPart = _PartDesign.studioNewPart  # ops#654 S2
# FreeCAD-CH (notes/derived-design.md, slice 1): Derived from another document
isDerivedCopy = _PartDesign.isDerivedCopy
makeDerivedCopies = _PartDesign.makeDerivedCopies
editDerivedCopies = _PartDesign.editDerivedCopies
studioLiveParts = _PartDesign.studioLiveParts  # ops#654 P5, P6a
studioSetToolIds = _PartDesign.studioSetToolIds
studioBooleanParts = _PartDesign.studioBooleanParts
studioConsumerOf = _PartDesign.studioConsumerOf
studioMakePieces = _PartDesign.studioMakePieces  # ops#654 P6p
studioPieceName = _PartDesign.studioPieceName
studioSetMergeAll = _PartDesign.studioSetMergeAll  # ops#654 10.13
