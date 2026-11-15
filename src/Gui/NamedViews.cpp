// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 Crawlspace Habitats LLC                            *
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

#include <algorithm>
#include <map>
#include <utility>

#include <Base/Persistence.h>
#include <Base/Reader.h>
#include <Base/Tools.h>
#include <Base/Writer.h>

#include "NamedViews.h"
#include "Document.h"
#include "MDIViewWithCamera.h"

using namespace Gui;

namespace
{
using Views = std::vector<std::pair<std::string, std::string>>;  // name, camera settings

std::map<const Gui::Document*, Views>& allViews()
{
    static std::map<const Gui::Document*, Views> views;
    return views;
}

Views::iterator find(Views& views, const std::string& name)
{
    return std::find_if(views.begin(), views.end(), [&name](const auto& view) {
        return view.first == name;
    });
}

MDIViewWithCamera* cameraView(Gui::Document* doc)
{
    if (auto* active = freecad_cast<MDIViewWithCamera*>(doc->getActiveView())) {
        return active;
    }
    for (auto* view : doc->getMDIViews()) {
        if (auto* withCamera = freecad_cast<MDIViewWithCamera*>(view)) {
            return withCamera;
        }
    }
    return nullptr;
}
}  // namespace

std::vector<std::string> NamedViews::names(const Document* doc)
{
    std::vector<std::string> result;
    auto it = allViews().find(doc);
    if (it != allViews().end()) {
        for (const auto& view : it->second) {
            result.push_back(view.first);
        }
    }
    return result;
}

bool NamedViews::has(const Document* doc, const std::string& name)
{
    auto it = allViews().find(doc);
    return it != allViews().end() && find(it->second, name) != it->second.end();
}

std::string NamedViews::settings(const Document* doc, const std::string& name)
{
    auto it = allViews().find(doc);
    if (it != allViews().end()) {
        auto view = find(it->second, name);
        if (view != it->second.end()) {
            return view->second;
        }
    }
    return {};
}

bool NamedViews::save(Document* doc, const std::string& name, const std::string& settings)
{
    if (!doc || name.empty()) {
        return false;
    }
    Views& views = allViews()[doc];
    auto view = find(views, name);
    if (view != views.end()) {
        view->second = settings;
    }
    else {
        views.emplace_back(name, settings);
    }
    doc->setModified(true);
    return true;
}

bool NamedViews::saveCurrent(Document* doc, const std::string& name)
{
    if (!doc || name.empty()) {
        return false;
    }
    MDIViewWithCamera* view = cameraView(doc);
    if (!view) {
        return false;
    }
    return save(doc, name, view->getCamera());
}

bool NamedViews::restore(Document* doc, const std::string& name)
{
    if (!doc || !has(doc, name)) {
        return false;
    }
    MDIViewWithCamera* view = cameraView(doc);
    if (!view) {
        return false;
    }
    return view->setCamera(settings(doc, name).c_str());
}

bool NamedViews::remove(Document* doc, const std::string& name)
{
    auto it = allViews().find(doc);
    if (it == allViews().end()) {
        return false;
    }
    auto view = find(it->second, name);
    if (view == it->second.end()) {
        return false;
    }
    it->second.erase(view);
    if (it->second.empty()) {
        allViews().erase(it);
    }
    doc->setModified(true);
    return true;
}

bool NamedViews::rename(Document* doc, const std::string& oldName, const std::string& newName)
{
    auto it = allViews().find(doc);
    if (it == allViews().end() || newName.empty()) {
        return false;
    }
    auto view = find(it->second, oldName);
    if (view == it->second.end()) {
        return false;
    }
    if (oldName != newName) {
        if (find(it->second, newName) != it->second.end()) {
            return false;
        }
        view->first = newName;
        doc->setModified(true);
    }
    return true;
}

void NamedViews::forget(const Document* doc)
{
    allViews().erase(doc);
}

void NamedViews::write(const Document* doc, Base::Writer& writer)
{
    auto it = allViews().find(doc);
    if (it == allViews().end() || it->second.empty()) {
        return;
    }
    writer.incInd();  // indentation for the views
    writer.Stream() << writer.ind() << "<NamedViews Count=\"" << it->second.size() << "\">\n";
    writer.incInd();
    for (const auto& view : it->second) {
        writer.Stream() << writer.ind() << "<View name=\""
                        << Base::Persistence::encodeAttribute(view.first) << "\" settings=\""
                        << Base::Persistence::encodeAttribute(view.second) << "\"/>\n";
    }
    writer.decInd();
    writer.Stream() << writer.ind() << "</NamedViews>\n";
    writer.decInd();
}

void NamedViews::read(Document* doc, Base::XMLReader& reader)
{
    Views views;
    const int count = reader.getAttribute<int>("Count");
    for (int i = 0; i < count; ++i) {
        reader.readElement("View");
        std::string name = reader.getAttribute<const char*>("name");
        std::string settings = reader.getAttribute<const char*>("settings");
        if (!name.empty()) {
            views.emplace_back(std::move(name), std::move(settings));
        }
    }
    reader.readEndElement("NamedViews");
    if (views.empty()) {
        allViews().erase(doc);
    }
    else {
        allViews()[doc] = std::move(views);
    }
}
