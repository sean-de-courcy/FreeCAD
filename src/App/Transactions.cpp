// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Jürgen Riegel <juergen.riegel@web.de>              *
 *   Copyright (c) 2011 Werner Mayer <wmayer[at]users.sourceforge.net>     *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include <cassert>

#include <atomic>
#include <Base/Console.h>
#include <Base/Reader.h>
#include <Base/Writer.h>

#include "Transactions.h"
#include "Document.h"
#include "DocumentObject.h"
#include "Property.h"


FC_LOG_LEVEL_INIT("App", true, true)

using namespace App;
using namespace std;

TYPESYSTEM_SOURCE(App::Transaction, Base::Persistence)

//**************************************************************************
// Construction/Destruction

// FreeCAD-CH (ops#152, ops#181): Transaction::openPendingTransaction is in Document.cpp.

Transaction::Transaction(int id)
{
    if (!id) {
        id = getNewID();
    }
    transID = id;
}

Transaction::~Transaction()
{
    auto& index = _Objects.get<0>();
    for (const auto& It : index) {
        if (It.second->status == TransactionObject::New) {
            // If an object has been removed from the document the transaction
            // status is 'New'. The 'pcNameInDocument' member serves as criterion
            // to check whether the object is part of the document or not.
            // Note, it's possible that the transaction status is 'New' while the
            // object is (again) part of the document. This usually happens when
            // a previous removal is undone.
            // Thus, if the object has been removed, i.e. the status is 'New' and
            // is still not part of the document the object must be destroyed not
            // to cause a memory leak. This usually is the case when the removal
            // of an object is not undone or when an addition is undone.

            if (!It.first->isAttachedToDocument()) {
                if (It.first->isDerivedFrom<DocumentObject>()) {
                    // #0003323: Crash when clearing transaction list
                    // It can happen that when clearing the transaction list several objects
                    // are destroyed with dependencies which can lead to dangling pointers.
                    // When setting the 'Destroy' flag of an object the destructors of link
                    // properties don't ry to remove backlinks, i.e. they don't try to access
                    // possible dangling pointers.
                    // An alternative solution is to call breakDependency inside
                    // Document::_removeObject. Make this change in v0.18.
                    const DocumentObject* obj = static_cast<const DocumentObject*>(It.first);
                    const_cast<DocumentObject*>(obj)->setStatus(ObjectStatus::Destroy, true);
                }
                delete It.first;
            }
        }
        delete It.second;
    }
}

static std::atomic<int> _TransactionID;

int Transaction::getNewID()
{
    int id = ++_TransactionID;
    if (id) {
        return id;
    }
    // wrap around? really?
    return ++_TransactionID;
}

int Transaction::getLastID()
{
    return _TransactionID;
}

unsigned int Transaction::getMemSize() const
{
    return 0;
}

void Transaction::Save(Base::Writer& /*writer*/) const
{
    assert(0);
}

void Transaction::Restore(Base::XMLReader& /*reader*/)
{
    assert(0);
}

int Transaction::getID() const
{
    return transID;
}

bool Transaction::isEmpty() const
{
    return _Objects.empty();
}

bool Transaction::hasObject(const TransactionalObject* Obj) const
{
#if BOOST_VERSION < 107500
    return !!_Objects.get<1>().count(Obj);
#else
    return !!_Objects.get<1>().contains(Obj);
#endif
}

void Transaction::changeProperty(TransactionalObject* Obj,
                                 std::function<void(TransactionObject* to)> changeFunc)
{
    auto& index = _Objects.get<1>();
    auto pos = index.find(Obj);

    if (pos != index.end()) {
        auto To = pos->second;
        changeFunc(To);
    }
    else if (auto To = TransactionFactory::instance().createTransaction(Obj->getTypeId())) {
        To->status = TransactionObject::Chn;
        index.emplace(Obj, To);
        changeFunc(To);
    }
}

std::pair<TransactionObject*, int64_t> Transaction::movedHere(const Property* prop)
{
    auto it = _MoveTargets.find(prop);
    if (it == _MoveTargets.end()) {
        return {nullptr, 0};
    }
    auto [to, key] = it->second;
    auto entry = to->_PropChangeMap.find(key);
    if (entry == to->_PropChangeMap.end() || entry->second.propertyTarget != prop) {
        _MoveTargets.erase(it);
        return {nullptr, 0};
    }
    return {to, key};
}

void Transaction::renameProperty(TransactionalObject* Obj, const Property* pcProp, const char* oldName)
{
    // FreeCAD-CH (ops#235): a moved property's rename: its move takes it back
    if (movedHere(pcProp).first) {
        return;
    }
    changeProperty(Obj, [pcProp, oldName](TransactionObject* to) {
        to->renameProperty(pcProp, oldName);
    });
}

void Transaction::arrangeMoveProperty(TransactionalObject* Obj, const Property* pcProp,
                                      TransactionalObject* target, Property* newProp)
{
    // (a move to another document is recorded in the target's document as well, with Obj the
    // target)
    if (Obj != target) {
        // FreeCAD-CH (ops#235): a moved property moved on: its first move's entry follows it
        if (auto [to, key] = movedHere(pcProp); to) {
            auto& data = to->_PropChangeMap[key];
            data.target = target;
            data.propertyTarget = newProp;
            _MoveTargets.erase(pcProp);
            _MoveTargets[newProp] = {to, key};
            return;
        }
    }
    changeProperty(Obj, [this, Obj, pcProp, target, newProp](TransactionObject* to) {
        to->arrangeMoveProperty(pcProp, target, newProp);
        if (Obj != target) {
            _MoveTargets[newProp] = {to, pcProp->getID()};
        }
    });
}

void Transaction::addOrRemoveProperty(TransactionalObject* Obj, const Property* pcProp, bool add)
{
    // FreeCAD-CH (ops#235): a moved property removed: its move entry becomes the removal
    if (!add) {
        if (auto [to, key] = movedHere(pcProp); to) {
            _MoveTargets.erase(pcProp);
            to->movedPropertyRemoved(key);
            return;
        }
    }
    changeProperty(Obj, [pcProp, add](TransactionObject* to) {
        to->addOrRemoveProperty(pcProp, add);
    });
}

//**************************************************************************
// separator for other implementation aspects


namespace
{
// FreeCAD-CH (ops#235): one entry's failure is logged and the next entry is still applied; one
// exception used to end Transaction::apply for every remaining entry of every object.
template<typename Func>
void applyEntry(const TransactionalObject* pcObj, const std::string& name, Func&& func)
{
    try {
        func();
    }
    catch (Base::Exception& e) {
        FC_ERR("exception while restoring " << pcObj->getFullName() << '.' << name << ": "
                                            << e.what());
    }
    catch (std::exception& e) {
        FC_ERR("exception while restoring " << pcObj->getFullName() << '.' << name << ": "
                                            << e.what());
    }
    catch (...) {
        FC_ERR("exception while restoring " << pcObj->getFullName() << '.' << name);
    }
}
}  // namespace

void Transaction::apply(Document& Doc, bool forward)
{
    std::string errMsg;
    try {
        auto& index = _Objects.get<0>();
        // FreeCAD-CH (ops#238): first the moves into and out of the objects created in the
        // transaction, which applyDel removes (and on abort destroys, moved properties included)
        auto removed = [this](const TransactionalObject* obj) {
            auto& byObject = _Objects.get<1>();
            auto pos = byObject.find(obj);
            return pos != byObject.end() && pos->second->status == TransactionObject::Del;
        };
        // in this document, found without reading through the pointer (a target can be freed)
        auto local = [this, &Doc](const TransactionalObject* obj) {
            return _Objects.get<1>().count(obj) != 0
                || Doc.isIn(static_cast<const DocumentObject*>(obj));
        };
        for (auto& info : index) {
            info.second->applyMovesOfRemoved(const_cast<TransactionalObject*>(info.first),
                                             removed,
                                             local);
        }
        for (auto& info : index) {
            info.second->applyDel(Doc, const_cast<TransactionalObject*>(info.first));
        }
        for (auto& info : index) {
            info.second->applyNew(Doc, const_cast<TransactionalObject*>(info.first));
        }
        // FreeCAD-CH (ops#238): a property moved out of a created object into an object the
        // transaction removed: that object is back now, and the property leaves it with its source
        for (auto& info : index) {
            if (info.second->status != TransactionObject::Del) {
                continue;
            }
            for (auto& [key, data] : info.second->_PropChangeMap) {
                if (data.movedEarly || !data.propertyTarget || !data.target
                    || data.target == info.first || !local(data.target)
                    || !data.target->isAttachedToDocument()) {
                    continue;
                }
                data.movedEarly = true;
                auto* target = data.target;
                applyEntry(target, data.name, [&]() {
                    if (const char* name = target->getPropertyName(data.propertyTarget)) {
                        target->removeDynamicProperty(std::string(name).c_str());
                    }
                });
            }
        }
        // FreeCAD-CH (ops#235): each pass for all objects, since a move or a name passes between
        // objects (TransactionObject::ChnPass)
        (void)forward;
        for (auto pass : {TransactionObject::ChnPass::Removals,
                          TransactionObject::ChnPass::Moves,
                          TransactionObject::ChnPass::Renames,
                          TransactionObject::ChnPass::Values}) {
            for (auto& info : index) {
                info.second->applyChnPass(const_cast<TransactionalObject*>(info.first), pass);
            }
            if (pass != TransactionObject::ChnPass::Renames) {
                continue;
            }
            // FreeCAD-CH (ops#238): the moves back from another document left by the Moves pass,
            // their names now freed by the renames
            for (auto& info : index) {
                auto* to = info.second;
                if (to->status != TransactionObject::New && to->status != TransactionObject::Chn) {
                    continue;
                }
                for (auto& [key, data] : to->_PropChangeMap) {
                    if (data.movedEarly || !data.propertyTarget || !data.target) {
                        continue;
                    }
                    data.movedEarly = true;
                    auto* pcObj = const_cast<TransactionalObject*>(info.first);
                    applyEntry(pcObj, data.name, [&]() {
                        to->applyMove(pcObj, data);
                    });
                }
            }
        }
    }
    catch (Base::Exception& e) {
        e.reportException();
        errMsg = e.what();
    }
    catch (std::exception& e) {
        errMsg = e.what();
    }
    catch (...) {
        errMsg = "Unknown exception";
    }
    if (!errMsg.empty()) {
        FC_ERR("Exception on " << (forward ? "redo" : "undo") << " '" << Name << "':" << errMsg);
    }
}

void Transaction::addObjectNew(TransactionalObject* Obj)
{
    auto& index = _Objects.get<1>();
    auto pos = index.find(Obj);
    if (pos != index.end()) {
        if (pos->second->status == TransactionObject::Del) {
            // first remove the item from the container before deleting it
            auto second = pos->second;
            auto first = pos->first;
            index.erase(pos);
            // FreeCAD-CH (ops#235, ops#238): its move entries go with it
            dropMovesOfFreed(first, second);
            delete second;
            delete first;
        }
        else {
            pos->second->status = TransactionObject::New;
            pos->second->_NameInDocument = Obj->detachFromDocument();
            // move item at the end to make sure the order of removal is kept
            auto& seq = _Objects.get<0>();
            seq.relocate(seq.end(), _Objects.project<0>(pos));
        }
    }
    else if (auto To = TransactionFactory::instance().createTransaction(Obj->getTypeId())) {
        To->status = TransactionObject::New;
        To->_NameInDocument = Obj->detachFromDocument();
        index.emplace(Obj, To);
    }
}

void Transaction::dropMovesOfFreed(const TransactionalObject* obj, TransactionObject* to)
{
    // moved into it: the move becomes the removal of the property, found by the object's
    // properties (a key of _MoveTargets is never dereferenced: it can be a freed property)
    std::vector<Property*> props;
    obj->getPropertyList(props);
    for (auto* prop : props) {
        if (auto [moveTo, key] = movedHere(prop); moveTo && moveTo != to) {
            _MoveTargets.erase(prop);
            moveTo->movedPropertyRemoved(key);
        }
    }

    // moved out of it: the property, still at its target, was added there in this transaction.
    // Not when it went back to the object itself (no entry for an object being freed), and not
    // between documents (the target's document records that move as well). The target is found
    // in the document and the property on the target before either pointer is read through.
    auto* docObj = freecad_cast<const DocumentObject*>(obj);
    const Document* doc = docObj ? docObj->getDocument() : nullptr;
    auto local = [&](const TransactionalObject* target) {
        return _Objects.get<1>().count(target) != 0
            || (doc && doc->isIn(static_cast<const DocumentObject*>(target)));
    };
    std::vector<std::pair<Property*, TransactionalObject*>> added;
    std::erase_if(_MoveTargets, [&](const auto& entry) {
        if (entry.second.to != to) {
            return false;
        }
        auto it = to->_PropChangeMap.find(entry.second.key);
        if (it != to->_PropChangeMap.end() && it->second.propertyTarget == entry.first) {
            auto* target = it->second.target;
            if (target && target != obj && local(target) && target->getPropertyName(entry.first)) {
                added.emplace_back(const_cast<Property*>(entry.first), target);
            }
        }
        return true;
    });
    for (auto [prop, target] : added) {
        changeProperty(target, [prop](TransactionObject* targetTo) {
            targetTo->addOrRemoveProperty(prop, true);
        });
    }
}

void Transaction::addObjectDel(const TransactionalObject* Obj)
{
    auto& index = _Objects.get<1>();
    auto pos = index.find(Obj);

    // is it created in this transaction ?
    if (pos != index.end() && pos->second->status == TransactionObject::New) {
        // remove completely from transaction
        // FreeCAD-CH (ops#235): its move entries go with it
        std::erase_if(_MoveTargets, [to = pos->second](const auto& entry) {
            return entry.second.to == to;
        });
        delete pos->second;
        index.erase(pos);
    }
    else if (pos != index.end() && pos->second->status == TransactionObject::Chn) {
        pos->second->status = TransactionObject::Del;
    }
    else if (auto To = TransactionFactory::instance().createTransaction(Obj->getTypeId())) {
        To->status = TransactionObject::Del;
        index.emplace(Obj, To);
    }
}

void Transaction::addObjectChange(const TransactionalObject* Obj, const Property* Prop)
{
    // FreeCAD-CH (ops#235): a moved property's change: its move entry restores the value from
    // before the transaction
    if (movedHere(Prop).first) {
        return;
    }
    auto& index = _Objects.get<1>();
    auto pos = index.find(Obj);

    if (pos != index.end()) {
        auto To = pos->second;
        To->setProperty(Prop);
    }
    else if (auto To = TransactionFactory::instance().createTransaction(Obj->getTypeId())) {
        To->status = TransactionObject::Chn;
        index.emplace(Obj, To);
        To->setProperty(Prop);
    }
}


//**************************************************************************
//**************************************************************************
// TransactionObject
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE_ABSTRACT(App::TransactionObject, Base::Persistence)

//**************************************************************************
// Construction/Destruction

TransactionObject::TransactionObject() = default;

TransactionObject::~TransactionObject()
{
    // FreeCAD-CH (ops#229): data.property is always a copy or null; a rename entry no longer keeps
    // the live property there, and one with a value change owns its copy.
    for (auto& v : _PropChangeMap) {
        delete v.second.property;
    }
}

void TransactionObject::applyDel(Document& /*Doc*/, TransactionalObject* /*pcObj*/)
{}

void TransactionObject::applyNew(Document& /*Doc*/, TransactionalObject* /*pcObj*/)
{}

void TransactionObject::takeDynamicData(PropData& data, const Property* prop)
{
    static_cast<DynamicProperty::PropData&>(data) =
        prop->getContainer()->getDynamicPropertyData(prop);
    data.property = nullptr;  // the live property: never kept in an entry
    if (data.pName) {
        data.name = data.pName;
        data.pName = nullptr;
    }
}


void TransactionObject::applyChn(Document& /*Doc*/, TransactionalObject* pcObj, bool /* Forward */)
{
    applyMovesOfRemoved(
        pcObj,
        [](const TransactionalObject*) {
            return false;
        },
        [](const TransactionalObject*) {
            return true;
        });
    for (auto pass : {ChnPass::Removals, ChnPass::Moves, ChnPass::Renames, ChnPass::Values}) {
        applyChnPass(pcObj, pass);
    }
}

// FreeCAD-CH (ops#235): the entries are applied in passes, since their order in the map is
// arbitrary and they can pass names and properties between properties and objects; each pass runs
// for every object before the next one (Transaction::apply):
// - the properties added in the transaction are removed, so a removed property of the same name
//   can come back;
// - moved properties are moved back to their sources, under a temporary name (a name free on both
//   objects, so neither a name the target had before the move nor one the source took after it
//   collides), or removed if they were added in the transaction;
// - renames are taken back, through temporary names, so names can be swapped, shifted or rotated;
//   the properties moved back get their names here;
// - values are restored and removed properties re-created.
// A change made to a moved property at its target is its move entry's (Transaction::movedHere()).
void TransactionObject::applyChnPass(TransactionalObject* pcObj, ChnPass pass)
{
    if (status != New && status != Chn) {
        return;
    }
    auto isMove = [](const PropData& data) {
        return data.propertyTarget && data.target;
    };
    auto nameBefore = [](const PropData& data) -> const std::string& {
        // the name from before the transaction (ops#229)
        return data.nameOrig.empty() ? data.name : data.nameOrig;
    };

    switch (pass) {
        case ChnPass::Removals:
            // Properties added in the transaction: removed, found by identity
            for (auto& v : _PropChangeMap) {
                auto& data = v.second;
                if (isMove(data) || data.property || !data.propertyOrig) {
                    continue;
                }
                applyEntry(pcObj, data.name, [&]() {
                    // getPropertyName() is safe with a property that no longer exists
                    if (const char* name = pcObj->getPropertyName(data.propertyOrig)) {
                        pcObj->removeDynamicProperty(std::string(name).c_str());
                    }
                });
            }
            break;

        case ChnPass::Moves:
            for (auto& v : _PropChangeMap) {
                auto& data = v.second;
                if (!isMove(data) || data.movedEarly) {
                    continue;
                }
                // FreeCAD-CH (ops#238): a move back from another document goes under its own name
                // (no temporary one); while that name is still taken at its source (to be freed by
                // the Renames pass), the move is left for Transaction::apply, after the renames
                if (data.target->isAttachedToDocument()) {
                    auto* obj = freecad_cast<DocumentObject*>(data.target);
                    auto* source = freecad_cast<DocumentObject*>(data.source);
                    const char* current = obj ? obj->getPropertyName(data.propertyTarget) : nullptr;
                    if (current && source && source != obj
                        && source->getDocument() != obj->getDocument()
                        && source->getPropertyByName(
                            data.nameOrig.empty() ? current : data.nameOrig.c_str())) {
                        continue;
                    }
                }
                // (marked as moved: whatever is left is applied after the renames)
                data.movedEarly = true;
                // This means we are undoing/redoing a move operation
                applyEntry(pcObj, data.name, [&]() {
                    applyMove(pcObj, data);
                });
            }
            break;

        case ChnPass::Renames: {
            // Renames, taken back: with more than one, each first gets a temporary name, so a name
            // another of them had before the transaction is free when it is given back. A rename
            // that fails gives the property back the name it had (no temporary name left).
            struct Rename
            {
                Property* prop;
                const PropData* data;
            };
            std::vector<Rename> renames;
            for (auto& v : _PropChangeMap) {
                auto& data = v.second;
                // a property that has its name from before already isn't renamed (moved there and
                // back: renaming to its own name throws)
                auto hasNameBefore = [&](const Property* prop) {
                    const char* now = pcObj->getPropertyName(prop);
                    return now && nameBefore(data) == now;
                };
                if (isMove(data)) {
                    if (data.restored && !hasNameBefore(data.restored)) {
                        renames.push_back({data.restored, &data});
                    }
                    continue;
                }
                if (data.nameOrig.empty()) {
                    continue;
                }
                // the current names are all distinct here, so the name finds the property; one
                // that isn't the entry's own (its own was removed) is someone else's
                Property* prop = pcObj->getDynamicPropertyByName(data.name.c_str());
                if (!prop || (data.propertyOrig && prop != data.propertyOrig)) {
                    continue;
                }
                data.restored = prop;
                if (!hasNameBefore(prop)) {
                    renames.push_back({prop, &data});
                }
            }
            if (renames.size() > 1) {
                int counter = 0;
                for (auto& [prop, data] : renames) {
                    applyEntry(pcObj, data->name, [&]() {
                        std::string tmp;
                        do {
                            tmp = "FreeCADRenameUndo" + std::to_string(++counter);
                        } while (pcObj->getPropertyByName(tmp.c_str()));
                        pcObj->renameDynamicProperty(prop, tmp.c_str());
                    });
                }
            }
            for (auto& [prop, data] : renames) {
                const std::string& name = nameBefore(*data);
                applyEntry(pcObj, name, [&]() {
                    try {
                        pcObj->renameDynamicProperty(prop, name.c_str());
                    }
                    catch (...) {
                        // renamed, and a handler threw: the rename stands
                        const char* now = pcObj->getPropertyName(prop);
                        if (now && name != now && data->name != now) {
                            try {
                                pcObj->renameDynamicProperty(prop, data->name.c_str());
                            }
                            catch (...) {
                            }
                        }
                        throw;
                    }
                });
            }
            break;
        }

        case ChnPass::Values:
            // Values restored, removed properties re-created
            for (auto& v : _PropChangeMap) {
                auto& data = v.second;
                if (!data.property) {
                    continue;
                }
                if (data.restored) {
                    // a property a move or a rename restored, whatever its name now
                    applyEntry(pcObj, nameBefore(data), [&]() {
                        data.restored->Paste(*data.property);
                    });
                    continue;
                }
                if (isMove(data)) {
                    continue;
                }
                const std::string& before = nameBefore(data);
                applyEntry(pcObj, before, [&]() {
                    auto prop = const_cast<Property*>(data.propertyOrig);

                    // getPropertyName() is specially coded to be safe even if prop has
                    // been destroyed. We must prepare for the case where user removed
                    // a dynamic property but does not recordered as transaction.
                    auto name = pcObj->getPropertyName(prop);
                    if (!name || (!before.empty() && before != name)
                        || data.propertyType != prop->getTypeId()) {
                        // Here means the original property is not found, probably removed
                        if (before.empty()) {
                            // not a dynamic property, nothing to do
                            return;
                        }

                        // It is possible for the dynamic property to be removed and
                        // restored. But since restoring property is actually creating
                        // a new property, the property key inside redo stack will not
                        // match. So we search by name first.
                        prop = pcObj->getDynamicPropertyByName(before.c_str());
                        if (!prop) {
                            // Still not found, re-create the property
                            prop = pcObj->addDynamicProperty(data.propertyType.getName(),
                                                             before.c_str(),
                                                             data.group.c_str(),
                                                             data.doc.c_str(),
                                                             data.attr,
                                                             data.readonly,
                                                             data.hidden);
                            if (!prop) {
                                return;
                            }
                            prop->setStatusValue(data.property->getStatus());
                        }
                    }

                    // Many properties do not bother implement Copy() and accepts
                    // derived types just fine in Paste(). So we do not enforce type
                    // matching here. But instead, strengthen type checking in all
                    // Paste() implementation.
                    prop->Paste(*data.property);
                });
            }
            break;
    }
}

void TransactionObject::applyMove(TransactionalObject* /*pcObj*/, PropData& data)
{
    if (!data.target->isAttachedToDocument()) {
        return;
    }

    auto* obj = freecad_cast<DocumentObject*>(data.target);
    if (obj == nullptr) {
        return;
    }
    auto* newTarget = freecad_cast<DocumentObject*>(data.source);

    // FreeCAD-CH (ops#235): the moved property itself, before anything uses the pointer;
    // getPropertyName() is safe with a property that no longer exists
    const char* current = obj->getPropertyName(data.propertyTarget);
    if (!current) {
        FC_WARN("moved property " << obj->getFullName() << '.' << data.name << " not found");
        return;
    }

    if (data.propertyTarget->getFullName() == "?") {
        // This is an entry we should ignore because it was
        // created to register a change in another document.
        // The move is handled by the other document.
        return;
    }

    std::string name = current;
    if (data.added) {
        obj->removeDynamicProperty(name.c_str());
        return;
    }
    if (obj == newTarget) {
        // moved back to its source in the transaction already
        data.restored = data.propertyTarget;
        return;
    }
    if (!newTarget) {
        return;
    }
    if (obj->getDocument() != newTarget->getDocument()) {
        // Between documents the target's renames are recorded in the target's document: restored
        // on the target and moved, as before ops#235, so that this document's redo transaction
        // records the move under its name
        if (data.property) {
            data.propertyTarget->Paste(*data.property);
        }
        if (!data.nameOrig.empty()) {
            obj->renameDynamicProperty(data.propertyTarget, data.nameOrig.c_str());
        }
        obj->moveDynamicProperty(data.propertyTarget, newTarget);
        return;
    }
    std::string tmp;
    int counter = 0;
    do {
        tmp = "FreeCADMoveUndo" + std::to_string(++counter);
    } while (obj->getPropertyByName(tmp.c_str()) || newTarget->getPropertyByName(tmp.c_str()));
    obj->renameDynamicProperty(data.propertyTarget, tmp.c_str());
    try {
        data.restored = obj->moveDynamicProperty(data.propertyTarget, newTarget);
    }
    catch (...) {
        // FreeCAD-CH (ops#238): a move whose handler threw is completed: the property is on
        // newTarget under the temporary name, to be named and restored by the next passes. One
        // that couldn't leave its object (removal failed) is named back, and its copy on newTarget
        // removed (after the rename, which a move entry would ignore)
        if (obj->getPropertyName(data.propertyTarget)) {
            try {
                obj->renameDynamicProperty(data.propertyTarget, name.c_str());
            }
            catch (...) {
            }
            if (newTarget->getDynamicPropertyByName(tmp.c_str())) {
                try {
                    newTarget->removeDynamicProperty(tmp.c_str());
                }
                catch (...) {
                }
            }
        }
        else {
            data.restored = newTarget->getDynamicPropertyByName(tmp.c_str());
        }
        throw;
    }
}

void TransactionObject::applyMovesOfRemoved(
    TransactionalObject* pcObj,
    const std::function<bool(const TransactionalObject*)>& removed,
    const std::function<bool(const TransactionalObject*)>& local)
{
    for (auto& v : _PropChangeMap) {
        v.second.restored = nullptr;
        v.second.movedEarly = false;
    }
    // an object created in the transaction: its passes don't run, it is removed
    const bool ownerRemoved = status == Del;
    for (auto& v : _PropChangeMap) {
        auto& data = v.second;
        // (an entry with the object itself as target: a move from another document, recorded
        // there too)
        if (!data.propertyTarget || !data.target || data.target == pcObj || !local(data.target)) {
            continue;
        }
        if (ownerRemoved) {
            if (!data.target->isAttachedToDocument()) {
                // removed in the transaction too: Transaction::apply() takes the property from it
                // once applyNew() brought it back
                continue;
            }
        }
        else if (!removed(data.target)) {
            continue;
        }
        else if (!pcObj->isAttachedToDocument()) {
            // the source was removed in the transaction too: nothing can be moved into it before
            // applyNew(), so the move becomes the removal of the source's property, re-created by
            // the Values pass (nothing, if it was added in the transaction)
            data.movedEarly = true;
            if (!data.added) {
                data.target = nullptr;
                data.propertyTarget = nullptr;
                data.source = nullptr;
                if (!data.nameOrig.empty()) {
                    data.name = data.nameOrig;
                    data.nameOrig.clear();
                }
            }
            continue;
        }
        data.movedEarly = true;
        applyEntry(pcObj, data.name, [&]() {
            applyMove(pcObj, data);
            // moved back into the removed object: named here, the Renames pass doesn't run; a name
            // the object took later keeps the temporary one (it is removed anyway)
            const std::string& before = data.nameOrig.empty() ? data.name : data.nameOrig;
            const char* now = data.restored ? pcObj->getPropertyName(data.restored) : nullptr;
            if (ownerRemoved && now && before != now && !pcObj->getPropertyByName(before.c_str())) {
                pcObj->renameDynamicProperty(data.restored, before.c_str());
            }
        });
    }
}

void TransactionObject::setProperty(const Property* pcProp)
{
    auto& data = _PropChangeMap[pcProp->getID()];
    // FreeCAD-CH (ops#229): also after a rename in this transaction (an entry with a name but no
    // propertyOrig); not after an add (propertyOrig without a copy) or an earlier change.
    if (!data.property && !data.propertyOrig && !data.target) {
        takeDynamicData(data, pcProp);
        data.propertyOrig = pcProp;
        data.property = pcProp->Copy();
        data.propertyType = pcProp->getTypeId();
        data.property->setStatusValue(pcProp->getStatus());
    }
}

void TransactionObject::renameProperty(const Property* pcProp, const char* oldName)
{
    if (!pcProp || !pcProp->getContainer()) {
        return;
    }

    auto& data = _PropChangeMap[pcProp->getID()];

    // FreeCAD-CH (ops#229): the entry may already hold a value change or an add of this property.
    // It keeps the current name and the name from before the transaction (the first rename's old
    // name); a property added in this transaction needs no rename back, only its removal.
    // FreeCAD-CH (ops#235): a fresh entry by what it holds; its name can be empty with dynamic
    // data named by pName
    if (!data.propertyOrig && !data.property && data.nameOrig.empty() && !data.target) {
        takeDynamicData(data, pcProp);
    }
    if (data.target) {
        return;  // a move: left as it was
    }
    bool added = data.propertyOrig && !data.property;
    if (!added && data.nameOrig.empty()) {
        data.nameOrig = oldName;
        data.statusOrig = pcProp->getStatus();
    }
    data.name = pcProp->getName();
    if (data.name == data.nameOrig) {
        // renamed back: no rename to take back
        data.nameOrig.clear();
        if (!data.property && !data.propertyOrig) {
            _PropChangeMap.erase(pcProp->getID());
        }
    }
}

void TransactionObject::arrangeMoveProperty(const Property* pcProp,
                                            TransactionalObject* target,
                                            Property* newProp)
{
    if (!pcProp || !pcProp->getContainer() || !target) {
        return;
    }

    auto& data = _PropChangeMap[pcProp->getID()];
    if (data.name.empty()) {
        takeDynamicData(data, pcProp);
    }

    // the source information
    // FreeCAD-CH (ops#235): a property added in this transaction is removed on undo, not moved back
    // (the add entry became a plain move, and the property was left on the source)
    data.added = data.propertyOrig && !data.property && !data.target;
    // FreeCAD-CH (ops#235): an earlier change's copy holds the value from before the transaction;
    // it was overwritten (and leaked)
    if (!data.property) {
        data.property = pcProp->Copy();
        data.propertyType = pcProp->getTypeId();
        data.property->setStatusValue(pcProp->getStatus());
    }
    data.source = pcProp->getContainer();

    // the target information
    data.target = target;
    data.propertyTarget = newProp;
}

void TransactionObject::movedPropertyRemoved(int64_t key)
{
    auto it = _PropChangeMap.find(key);
    if (it == _PropChangeMap.end()) {
        return;
    }
    auto& data = it->second;
    if (data.added) {
        // added, moved and removed: nothing to undo
        delete data.property;
        _PropChangeMap.erase(it);
        return;
    }
    data.target = nullptr;
    data.propertyTarget = nullptr;
    data.source = nullptr;
    if (!data.nameOrig.empty()) {
        data.name = data.nameOrig;
        data.nameOrig.clear();
    }
}

void TransactionObject::addOrRemoveProperty(const Property* pcProp, bool add)
{
    (void)add;
    if (!pcProp || !pcProp->getContainer()) {
        return;
    }

    auto& data = _PropChangeMap[pcProp->getID()];
    // FreeCAD-CH (ops#229): an entry holding only a rename (no propertyOrig) is not an add; its
    // removal is recorded under the name from before the transaction.
    if (!add && !data.property && !data.propertyOrig && !data.nameOrig.empty()) {
        data.propertyOrig = pcProp;
        data.property = pcProp->Copy();
        data.propertyType = pcProp->getTypeId();
        // FreeCAD-CH (ops#235): the status from before the transaction, not from the removal
        data.property->setStatusValue(data.statusOrig);
        data.name = data.nameOrig;
        data.nameOrig.clear();
        return;
    }
    // FreeCAD-CH (ops#235): an existing entry by what it holds, not by its name
    if (data.propertyOrig || data.property || !data.nameOrig.empty() || data.target) {
        if (!add && !data.property) {
            // this means add and remove the same property inside a single
            // transaction, so they cancel each other out.
            _PropChangeMap.erase(pcProp->getID());
        }
        else if (!add && !data.nameOrig.empty() && !data.target) {
            // FreeCAD-CH (ops#235): a changed and renamed property removed: re-created under its
            // name from before the transaction, and no rename left to take back (it found
            // another property that took the name later)
            data.name = data.nameOrig;
            data.nameOrig.clear();
        }
        return;
    }
    takeDynamicData(data, pcProp);
    data.propertyOrig = pcProp;
    if (add) {
        data.property = nullptr;
    }
    else {
        data.property = pcProp->Copy();
        data.propertyType = pcProp->getTypeId();
        data.property->setStatusValue(pcProp->getStatus());
    }
}

unsigned int TransactionObject::getMemSize() const
{
    return 0;
}

void TransactionObject::Save(Base::Writer& /*writer*/) const
{
    assert(0);
}

void TransactionObject::Restore(Base::XMLReader& /*reader*/)
{
    assert(0);
}

//**************************************************************************
//**************************************************************************
// TransactionDocumentObject
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE_ABSTRACT(App::TransactionDocumentObject, App::TransactionObject)

//**************************************************************************
// Construction/Destruction

/**
 * A constructor.
 * A more elaborate description of the constructor.
 */
TransactionDocumentObject::TransactionDocumentObject() = default;

/**
 * A destructor.
 * A more elaborate description of the destructor.
 */
TransactionDocumentObject::~TransactionDocumentObject() = default;

void TransactionDocumentObject::applyDel(Document& Doc, TransactionalObject* pcObj)
{
    if (status == Del) {
        DocumentObject* obj = static_cast<DocumentObject*>(pcObj);

        // Make sure the backlinks of all linked objects are updated. As the links of the removed
        // object are never set to [] they also do not remove the backlink. But as they are
        // not in the document anymore we need to remove them anyway to ensure a correct graph
        {
            auto list = obj->getOutList();
            for (auto link : list) {
                link->_removeBackLink(obj);
            }
        }

        {
            auto list = obj->getOutListProp();
            for (const auto& [fromObj, fromProp, toObj, toProp] : list) {
                toObj->_removeBackLinkProp(fromProp.c_str(), fromObj, toProp.c_str());
            }
        }

        // simply filling in the saved object
        Doc._removeObject(obj);
    }
}

void TransactionDocumentObject::applyNew(Document& Doc, TransactionalObject* pcObj)
{
    if (status == New) {
        DocumentObject* obj = static_cast<DocumentObject*>(pcObj);
        Doc._addObject(obj, _NameInDocument.c_str());

        // make sure the backlinks of all linked objects are updated
        {
            auto list = obj->getOutList();
            for (auto link : list) {
                link->_addBackLink(obj);
            }
        }

        {
            auto list = obj->getOutListProp();
            for (const auto& [fromObj, fromProp, toObj, toProp] : list) {
                toObj->_addBackLinkProp(fromProp.c_str(), fromObj, toProp.c_str());
            }
        }
    }
}

//**************************************************************************
//**************************************************************************
// TransactionFactory
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

App::TransactionFactory* App::TransactionFactory::self = nullptr;

TransactionFactory& TransactionFactory::instance()
{
    if (!self) {
        self = new TransactionFactory;
    }
    return *self;
}

void TransactionFactory::destruct()
{
    delete self;
    self = nullptr;
}

void TransactionFactory::addProducer(const Base::Type& type, Base::AbstractProducer* producer)
{
    producers[type] = producer;
}

/**
 * Creates a transaction object for the given type id.
 */
TransactionObject* TransactionFactory::createTransaction(const Base::Type& type) const
{
    for (const auto& it : producers) {
        if (type.isDerivedFrom(it.first)) {
            return static_cast<TransactionObject*>(it.second->Produce());
        }
    }

    Base::Console().log("Cannot create transaction object from %s\n", type.getName());
    return nullptr;
}