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

void Transaction::renameProperty(TransactionalObject* Obj, const Property* pcProp, const char* oldName)
{
    changeProperty(Obj, [pcProp, oldName](TransactionObject* to) {
        to->renameProperty(pcProp, oldName);
    });
}

void Transaction::arrangeMoveProperty(TransactionalObject* Obj, const Property* pcProp,
                                      TransactionalObject* target, Property* newProp)
{
    changeProperty(Obj, [pcProp, target, newProp](TransactionObject* to) {
        to->arrangeMoveProperty(pcProp, target, newProp);
    });
}

void Transaction::addOrRemoveProperty(TransactionalObject* Obj, const Property* pcProp, bool add)
{
    changeProperty(Obj, [pcProp, add](TransactionObject* to) {
        to->addOrRemoveProperty(pcProp, add);
    });
}

//**************************************************************************
// separator for other implementation aspects


void Transaction::apply(Document& Doc, bool forward)
{
    std::string errMsg;
    try {
        auto& index = _Objects.get<0>();
        for (auto& info : index) {
            info.second->applyDel(Doc, const_cast<TransactionalObject*>(info.first));
        }
        for (auto& info : index) {
            info.second->applyNew(Doc, const_cast<TransactionalObject*>(info.first));
        }
        for (auto& info : index) {
            info.second->applyChn(Doc, const_cast<TransactionalObject*>(info.first), forward);
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

void Transaction::addObjectDel(const TransactionalObject* Obj)
{
    auto& index = _Objects.get<1>();
    auto pos = index.find(Obj);

    // is it created in this transaction ?
    if (pos != index.end() && pos->second->status == TransactionObject::New) {
        // remove completely from transaction
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
        e.reportException();
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

void TransactionObject::applyChn(Document& /*Doc*/, TransactionalObject* pcObj, bool /* Forward */)
{
    if (status != New && status != Chn) {
        return;
    }
    auto isMove = [](const PropData& data) {
        return data.propertyTarget && data.target;
    };
    // FreeCAD-CH (ops#235): the entries are applied in passes, since their order in the map is
    // arbitrary and they can pass names between properties: moves; then the properties added in
    // the transaction are removed, so a removed property of the same name can come back; then the
    // renames are taken back, through temporary names, so names can be swapped or shifted; then
    // values are restored and removed properties re-created.

    // Moves
    for (auto& v : _PropChangeMap) {
        auto& data = v.second;
        if (!isMove(data)) {
            continue;
        }
        // This means we are undoing/redoing a move operation
        applyEntry(pcObj, data.name, [&]() {
            if (!data.target->isAttachedToDocument()) {
                return;
            }

            auto* obj = freecad_cast<DocumentObject*>(data.target);
            if (obj == nullptr) {
                return;
            }
            auto* newTarget = freecad_cast<DocumentObject*>(data.source);

            if (data.propertyTarget->getFullName() == "?") {
                // This is an entry we should ignore because it was
                // created to register a change in another document.
                // The move is handled by the other document.
                return;
            }

            // FreeCAD-CH (ops#235): a value change and a rename before the move are taken back
            // too, on the moved property before it moves back, so that the redo transaction
            // records them with the move (in the target's entry)
            if (data.property) {
                data.propertyTarget->Paste(*data.property);
            }
            if (!data.nameOrig.empty()) {
                obj->renameDynamicProperty(data.propertyTarget, data.nameOrig.c_str());
            }
            obj->moveDynamicProperty(data.propertyTarget, newTarget);
        });
    }

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

    // Renames, taken back: with more than one, each first gets a temporary name, so a name another
    // of them had before the transaction is free when it is given back
    std::vector<std::pair<Property*, const PropData*>> renames;
    for (auto& v : _PropChangeMap) {
        auto& data = v.second;
        if (isMove(data) || data.nameOrig.empty()) {
            continue;
        }
        // the current names are all distinct here, so the name finds the property
        if (Property* prop = pcObj->getDynamicPropertyByName(data.name.c_str())) {
            renames.emplace_back(prop, &data);
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
        applyEntry(pcObj, data->nameOrig, [&]() {
            pcObj->renameDynamicProperty(prop, data->nameOrig.c_str());
        });
    }

    // Values restored, removed properties re-created
    for (auto& v : _PropChangeMap) {
        auto& data = v.second;
        if (isMove(data) || !data.property) {
            continue;
        }
        // The name to restore: the one from before the transaction (ops#229)
        const std::string& nameBefore = data.nameOrig.empty() ? data.name : data.nameOrig;
        applyEntry(pcObj, nameBefore, [&]() {
            auto prop = const_cast<Property*>(data.propertyOrig);

            // getPropertyName() is specially coded to be safe even if prop has
            // been destroyed. We must prepare for the case where user removed
            // a dynamic property but does not recordered as transaction.
            auto name = pcObj->getPropertyName(prop);
            if (!name || (!nameBefore.empty() && nameBefore != name)
                || data.propertyType != prop->getTypeId()) {
                // Here means the original property is not found, probably removed
                if (nameBefore.empty()) {
                    // not a dynamic property, nothing to do
                    return;
                }

                // It is possible for the dynamic property to be removed and
                // restored. But since restoring property is actually creating
                // a new property, the property key inside redo stack will not
                // match. So we search by name first.
                prop = pcObj->getDynamicPropertyByName(nameBefore.c_str());
                if (!prop) {
                    // Still not found, re-create the property
                    prop = pcObj->addDynamicProperty(data.propertyType.getName(),
                                                     nameBefore.c_str(),
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
        return;
    }
    if (data.property) {
        delete data.property;
        data.property = nullptr;
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