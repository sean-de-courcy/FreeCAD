// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2019 Abdullah Tahiri <abdullah.tahiri.yo@gmail.com>     *
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

#pragma once

#include <array>
#include <bitset>

#include <Mod/Part/App/Geometry.h>
#include <Mod/Part/App/GeometryMigrationExtension.h>
#include <Mod/Sketcher/SketcherGlobal.h>


namespace Sketcher
{

class ISketchExternalGeometryExtension
{
public:
    // Identification information
    // START_CREDIT_BLOCK: Credit under LGPL for this block to Zheng, Lei (realthunder)
    // <realthunder.dev@gmail.com>
    virtual bool testFlag(int flag) const = 0;

    virtual void setFlag(int flag, bool v = true) = 0;

    virtual unsigned long getFlags() const = 0;

    virtual void setFlags(unsigned long flags) = 0;
    // END_CREDIT_BLOCK: Credit under LGPL for this block to Zheng, Lei (realthunder)
    // <realthunder.dev@gmail.com>

    virtual bool isClear() const = 0;

    virtual size_t flagSize() const = 0;

    virtual const std::string& getRef() const = 0;

    virtual void setRef(const std::string& ref) = 0;

    virtual int getRefIndex() const = 0;

    virtual void setRefIndex(int index) = 0;

    // FreeCAD-CH (ops#264 e2): the mapped name of the source edge a face link's geometry was
    // projected from, empty where it has none (an edge or vertex link, an intersection, a face
    // projected through hidden lines, geometry saved before)
    virtual const std::string& getSource() const = 0;

    virtual void setSource(const std::string& source) = 0;
};

class SketcherExport ExternalGeometryExtension: public Part::GeometryMigrationPersistenceExtension,
                                                private ISketchExternalGeometryExtension
{
    TYPESYSTEM_HEADER_WITH_OVERRIDE();

public:
    // START_CREDIT_BLOCK: Credit under LGPL for this block to Zheng, Lei (realthunder)
    // <realthunder.dev@gmail.com>
    enum Flag
    {
        Defining = 0,  // allow an external geometry to build shape
        Frozen = 1,    // freeze an external geometry
        Detached = 2,  // signal the intentions of detaching the geometry from external reference
        Missing = 3,   // geometry with missing external reference
        Sync = 4,      // signal the intention to synchronize a frozen geometry
        // FreeCAD-CH (ops#264): the kind of the link's geometry this is, which the rebuild hands
        // the Ids out by; neither in a file saved before
        Projection = 5,
        Intersection = 6,
        // FreeCAD-CH (ops#287): built while the link's type was undecided (a repair an open left
        // pending), with the type at its index: the geometry doesn't tell the link's type. A
        // build before reads the flags without it
        TypeGuessed = 7,
        // FreeCAD-CH (ops#287, PR 277 round 7): saved geometry of a link whose type an open
        // couldn't tell: the link waits for its type, and the geometry is still evidence of it (a
        // later open, or the rebuild that finds its element again, matches it). A freeze, a park
        // or a drop keeps it; only a decision of the type clears it
        TypeUndecided = 8,
        NumFlags       // Must be the last type
    };
    // END_CREDIT_BLOCK: Credit under LGPL for this block to Zheng, Lei (realthunder)
    // <realthunder.dev@gmail.com>

    constexpr static std::array<const char*, NumFlags> flag2str {
        {"Defining", "Frozen", "Detached", "Missing", "Sync", "Projection", "Intersection",
         "TypeGuessed", "TypeUndecided"}
    };

public:
    ExternalGeometryExtension() = default;

    ~ExternalGeometryExtension() override = default;

    std::unique_ptr<Part::GeometryExtension> copy() const override;

    PyObject* getPyObject() override;

    // START_CREDIT_BLOCK: Credit under LGPL for this block to Zheng, Lei (realthunder)
    // <realthunder.dev@gmail.com>
    bool testFlag(int flag) const override
    {
        return Flags.test((size_t)(flag));
    }

    void setFlag(int flag, bool v = true) override
    {
        Flags.set((size_t)(flag), v);
    }

    unsigned long getFlags() const override
    {
        return Flags.to_ulong();
    }

    void setFlags(unsigned long flags) override
    {
        Flags = flags;
    }
    // END_CREDIT_BLOCK: Credit under LGPL for this block to Zheng, Lei (realthunder)
    // <realthunder.dev@gmail.com>

    bool isClear() const override
    {
        return Flags.none();
    }

    size_t flagSize() const override
    {
        return Flags.size();
    }

    const std::string& getRef() const override
    {
        return Ref;
    }

    void setRef(const std::string& ref) override
    {
        Ref = ref;
    }

    int getRefIndex() const override
    {
        return RefIndex;
    }

    void setRefIndex(int index) override
    {
        RefIndex = index;
    }

    const std::string& getSource() const override
    {
        return Source;
    }

    void setSource(const std::string& source) override
    {
        Source = source;
    }

    static bool getFlagsFromName(std::string str, ExternalGeometryExtension::Flag& flag);

protected:
    void copyAttributes(Part::GeometryExtension* cpy) const override;

    void restoreAttributes(Base::XMLReader& reader) override;

    void saveAttributes(Base::Writer& writer) const override;

    void preSave(Base::Writer& writer) const override;

private:
    ExternalGeometryExtension(const ExternalGeometryExtension&) = default;

private:
    using FlagType = std::bitset<32>;
    // START_CREDIT_BLOCK: Credit under LGPL for this block to Zheng, Lei (realthunder)
    // <realthunder.dev@gmail.com>
    std::string Ref;
    int RefIndex = -1;
    FlagType Flags;
    // END_CREDIT_BLOCK: Credit under LGPL for this block to Zheng, Lei (realthunder)
    // <realthunder.dev@gmail.com>
    std::string Source;
};

}  // namespace Sketcher
