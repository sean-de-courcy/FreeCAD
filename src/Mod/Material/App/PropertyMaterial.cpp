// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2023 David Carter <dcarter@david.carter.ca>             *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#include <algorithm>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QStringList>
#include <QMetaType>
#include <QUuid>



#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <Base/Console.h>
#include <Base/Persistence.h>
#include <Base/Quantity.h>
#include <Base/Writer.h>
#include <Gui/MetaTypes.h>

#include "Exceptions.h"
#include "MaterialLibrary.h"
#include "MaterialManager.h"
#include "Model.h"
#include "ModelManager.h"
#include "MaterialPy.h"
#include "PropertyMaterial.h"

using namespace Materials;

/* TRANSLATOR Material::PropertyMaterial */

TYPESYSTEM_SOURCE(Materials::PropertyMaterial, App::Property)

PropertyMaterial::PropertyMaterial() = default;

PropertyMaterial::~PropertyMaterial() = default;

void PropertyMaterial::setValue(const Material& mat)
{
    aboutToSetValue();
    _material = mat;
    hasSetValue();
}

void PropertyMaterial::setValue(const App::Material& mat)
{
    aboutToSetValue();
    _material = mat;
    hasSetValue();
}

const Material& PropertyMaterial::getValue() const
{
    return _material;
}

PyObject* PropertyMaterial::getPyObject()
{
    return new MaterialPy(new Material(_material));
}

void PropertyMaterial::setPyObject(PyObject* value)
{
    if (PyObject_TypeCheck(value, &(MaterialPy::Type))) {
        setValue(*static_cast<MaterialPy*>(value)->getMaterialPtr());
    }
    else {
        std::string error = std::string("type must be 'Material' not ");
        error += value->ob_type->tp_name;
        throw Base::TypeError(error);
    }
}

// The file carries the material (ops#696, design E1 in the ops repo's part-properties-design note):
//
//   <PropertyMaterial uuid="..." name="..." models="1" values="1">
//       <Model uuid="454661e5-..."/>
//       <Value name="Density" value="1.99e-06" unit="kg/mm^3"/>
//   </PropertyMaterial>
//
// Models are the material's physical models; values are its non-empty physical values of a scalar
// type, at full precision: a quantity in internal units with its unit, a float, an integer, a
// boolean or a string. Appearance models stay in the library card (a part's colour is its own).
// A non-empty value of another type (a list, an image...) is named by a <Dropped name="..."/>
// child, so that a computer without the card knows the material it restores is incomplete.
// A file from before this change has the uuid only (no "models" attribute).

namespace
{

bool isCarriedType(MaterialValue::ValueType type)
{
    switch (type) {
        case MaterialValue::Quantity:
        case MaterialValue::Float:
        case MaterialValue::Integer:
        case MaterialValue::Boolean:
        case MaterialValue::String:
        case MaterialValue::URL:
            return true;
        default:
            return false;
    }
}

std::string exactDouble(double value)
{
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::setprecision(std::numeric_limits<double>::max_digits10) << value;
    return stream.str();
}

// An attribute's text: a control character, which XML 1.0 refuses, would make the whole document
// unreadable, so it goes through validateXMLString as PropertyString's does.
std::string encode(const std::string& text)
{
    return Base::Persistence::encodeAttribute(Base::Persistence::validateXMLString(text));
}

std::string encode(const QString& text)
{
    return encode(text.toStdString());
}

// The attributes of one value, or empty when the value is not carried.
std::string valueAttributes(const MaterialProperty& prop)
{
    if (prop.isNull() || !isCarriedType(prop.getType())) {
        return {};
    }
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    switch (prop.getType()) {
        case MaterialValue::Quantity: {
            auto value = prop.getValue();
            if (value.userType() != qMetaTypeId<Base::Quantity>()) {
                // a text that did not parse as a quantity is kept as text, as the card has it
                stream << " value=\"" << encode(value.toString()) << "\"";
                break;
            }
            auto quantity = value.value<Base::Quantity>();
            stream << " value=\"" << exactDouble(quantity.getValue()) << "\" unit=\""
                   << encode(quantity.getUnit().getString()) << "\"";
            break;
        }
        case MaterialValue::Float:
            stream << " value=\"" << exactDouble(prop.getValue().toDouble()) << "\"";
            break;
        case MaterialValue::Integer:
            stream << " value=\"" << prop.getValue().toLongLong() << "\"";
            break;
        case MaterialValue::Boolean:
            stream << " value=\"" << (prop.getValue().toBool() ? "true" : "false") << "\"";
            break;
        default:
            stream << " value=\"" << encode(prop.getValue().toString()) << "\"";
            break;
    }
    return stream.str();
}

void restoreValue(Material& material,
                  const QString& name,
                  Base::XMLReader& reader)
{
    auto prop = material.getPhysicalProperty(name);
    auto text = reader.getAttribute<const char*>("value");
    switch (prop->getType()) {
        case MaterialValue::Quantity:
            if (reader.hasAttribute("unit")) {
                Base::Quantity quantity(reader.getAttribute<double>("value"),
                                        std::string(reader.getAttribute<const char*>("unit")));
                material.setPhysicalValue(name, quantity);
            }
            else {
                material.setPhysicalValue(name, QString::fromUtf8(text));
            }
            break;
        case MaterialValue::Float:
            material.setPhysicalValue(name, reader.getAttribute<double>("value"));
            break;
        case MaterialValue::Integer: {
            // written as 64 bits (toLongLong), so read as 64 bits: setInt(QString) has 32
            std::size_t used = 0;
            long long number = std::stoll(text, &used);
            if (text[used] != '\0') {
                throw Base::ValueError("not an integer");
            }
            if (number >= std::numeric_limits<int>::min()
                && number <= std::numeric_limits<int>::max()) {
                material.setPhysicalValue(name, static_cast<int>(number));
            }
            else {
                material.setPhysicalValue(name, QVariant(static_cast<qlonglong>(number)));
            }
            break;
        }
        default:
            material.setPhysicalValue(name, QString::fromUtf8(text));
            break;
    }
}

// Whether the property is being restored by opening a document (not by a paste or an import)
bool openingDocument(const App::Property& prop)
{
    auto obj = freecad_cast<App::DocumentObject*>(prop.getContainer());
    auto doc = obj ? obj->getDocument() : nullptr;
    return doc && doc->testStatus(App::Document::Restoring)
        && !doc->testStatus(App::Document::Importing);
}

std::string ownerName(const App::Property& prop)
{
    auto obj = freecad_cast<App::DocumentObject*>(prop.getContainer());
    if (obj && obj->isAttachedToDocument()) {
        return obj->getFullName() + " (" + obj->Label.getStrValue() + ")";
    }
    return prop.getFullName();
}

// Whether a file name is one Windows reserves for a device (CON, NUL, COM1...), whatever its case
// and extension
bool reservedOnWindows(const QString& file)
{
    QString base = file.section(QLatin1Char('.'), 0, 0).trimmed().toUpper();
    static const QStringList devices = {QStringLiteral("CON"),
                                        QStringLiteral("PRN"),
                                        QStringLiteral("AUX"),
                                        QStringLiteral("NUL"),
                                        QStringLiteral("CONIN$"),
                                        QStringLiteral("CONOUT$")};
    if (devices.contains(base)) {
        return true;
    }
    if (base.size() == 4 && (base.startsWith(QStringLiteral("COM")) || base.startsWith(QStringLiteral("LPT")))) {
        // COM0-9, LPT0-9 and the superscript digits Windows also reserves
        QChar digit = base.at(3);
        return (digit >= QLatin1Char('0') && digit <= QLatin1Char('9')) || digit == QChar(0x00B9)
            || digit == QChar(0x00B2) || digit == QChar(0x00B3);
    }
    return false;
}

// Whether the folder holds a file of this name, compared without case (Windows and macOS do)
bool existsIgnoringCase(const QString& folder, const QString& file)
{
    QDir dir(folder);
    for (auto& entry : dir.entryList(QDir::Files | QDir::Dirs | QDir::NoDotAndDotDot | QDir::Hidden)) {
        if (entry.compare(file, Qt::CaseInsensitive) == 0) {
            return true;
        }
    }
    return false;
}

constexpr int maxLearnedName = 200;

// A file name for a material learned on open: its name, without characters a file system refuses.
QString learnedFileName(const QString& name)
{
    QString file = name.trimmed();
    static const QString refused = QStringLiteral("<>:\"/\\|?*");
    for (auto& c : file) {
        if (refused.contains(c) || c.unicode() < 32) {
            c = QLatin1Char('_');
        }
    }
    if (file.isEmpty() || file.startsWith(QLatin1Char('.'))) {
        file.prepend(QStringLiteral("Material"));
    }
    return file + QStringLiteral(".FCMat");
}

// Adds a material found in a document being opened to the user's library when the library lacks
// it, so that it is offered for new documents. Never throws: a document opens whether or not this works.
void learnMaterial(const Material& material, const std::string& owner)
{
    try {
        auto& manager = MaterialManager::getManager();
        if (QUuid::fromString(material.getUUID()).isNull()) {
            Base::Console().warning("Material '%s' of %s has no valid UUID ('%s'): "
                                    "not added to the user material library\n",
                                    material.getName().toStdString().c_str(),
                                    owner.c_str(),
                                    material.getUUID().toStdString().c_str());
            return;
        }
        if (manager.exists(material.getUUID())) {
            return;
        }
        std::shared_ptr<MaterialLibrary> library;
        try {
            library = manager.getLibrary(QStringLiteral("User"));
        }
        catch (const LibraryNotFound&) {
            Base::Console().log("Material '%s' of %s not added: no user material library\n",
                                material.getName().toStdString().c_str(),
                                owner.c_str());
            return;
        }
        auto local = std::dynamic_pointer_cast<MaterialLibraryLocal>(library);
        if (!local || local->isReadOnly()) {
            return;
        }
        QString path = learnedFileName(material.getName());
        if (path.size() > maxLearnedName || reservedOnWindows(path)) {
            Base::Console().log("Material '%s' of %s not added: '%s' can't be a file name on "
                                "every computer\n",
                                material.getName().toStdString().c_str(),
                                owner.c_str(),
                                path.toStdString().c_str());
            return;
        }
        QString filePath = local->getLocalPath(path);
        if (existsIgnoringCase(QFileInfo(filePath).path(), QFileInfo(filePath).fileName())) {
            Base::Console().log("Material '%s' of %s not added: '%s' exists in the user library\n",
                                material.getName().toStdString().c_str(),
                                owner.c_str(),
                                path.toStdString().c_str());
            return;
        }
        {
            // saveMaterial registers the material even when its file can't be written, in two maps
            // (the manager's and the library's paths): try the file first
            QDir().mkpath(QFileInfo(filePath).path());
            QFile probe(filePath);
            if (!probe.open(QIODevice::WriteOnly)) {
                Base::Console().log("Material '%s' of %s not added: '%s' can't be written\n",
                                    material.getName().toStdString().c_str(),
                                    owner.c_str(),
                                    filePath.toStdString().c_str());
                return;
            }
            probe.close();
            probe.remove();
        }
        auto card = std::make_shared<Material>(material);
        // saveAsCopy keeps the UUID, so the card resolves this document's reference
        manager.saveMaterial(library, card, path, false, true, false);
        if (!QFileInfo::exists(filePath)) {
            // written a moment ago, so this is rare: undo the manager's registration at least
            manager.remove(material.getUUID());
            Base::Console().log("Material '%s' of %s not added: '%s' could not be written\n",
                                material.getName().toStdString().c_str(),
                                owner.c_str(),
                                filePath.toStdString().c_str());
            return;
        }
        Base::Console().log("Material '%s' added to the user library from %s\n",
                            material.getName().toStdString().c_str(),
                            owner.c_str());
    }
    catch (const Base::Exception& e) {
        Base::Console().log("Material '%s' of %s not added: %s\n",
                            material.getName().toStdString().c_str(),
                            owner.c_str(),
                            e.what());
    }
    catch (const std::exception& e) {
        Base::Console().log("Material '%s' of %s not added: %s\n",
                            material.getName().toStdString().c_str(),
                            owner.c_str(),
                            e.what());
    }
}

// One stored <Model>: added when it is a physical model known here, else reported
void restoreModel(Material& material, Base::XMLReader& reader, std::vector<std::string>& lost)
{
    auto model = QString::fromLatin1(reader.getAttribute<const char*>("uuid", ""));
    if (material.hasPhysicalModel(model)) {
        return;
    }
    try {
        // addPhysical neither reports a model unknown here nor checks its kind
        auto known = ModelManager::getManager().getModel(model);
        if (known->getType() == Model::ModelType_Physical) {
            material.addPhysical(model);
        }
    }
    catch (const Base::Exception&) {
    }
    if (!material.hasPhysicalModel(model)) {
        lost.push_back("model " + model.toStdString());
    }
}

// One stored <Value>: set when its property is there and takes it, else reported
void restoreNamedValue(Material& material, Base::XMLReader& reader, std::vector<std::string>& lost)
{
    auto valueName = QString::fromUtf8(reader.getAttribute<const char*>("name", ""));
    if (valueName.isEmpty() || !material.hasPhysicalProperty(valueName)) {
        lost.push_back(valueName.isEmpty() ? std::string("a value without a name")
                                           : valueName.toStdString());
        return;
    }
    try {
        restoreValue(material, valueName, reader);
    }
    catch (const Base::Exception&) {
        lost.push_back(valueName.toStdString());
    }
    catch (const std::exception&) {
        lost.push_back(valueName.toStdString());
    }
}

}  // namespace

void PropertyMaterial::Save(Base::Writer& writer) const
{
    std::vector<QString> models;
    for (auto& uuid : *_material.getPhysicalModels()) {
        models.push_back(uuid);
    }
    std::sort(models.begin(), models.end());
    std::vector<std::pair<QString, std::string>> values;
    std::vector<QString> droppedNames;
    std::string dropped;
    for (auto& [name, prop] : _material.getPhysicalProperties()) {
        auto attributes = valueAttributes(*prop);
        if (!attributes.empty()) {
            values.emplace_back(name, attributes);
        }
        else if (!prop->isNull()) {
            droppedNames.push_back(name);
            dropped += (dropped.empty() ? "" : ", ") + name.toStdString();
        }
    }
    if (!dropped.empty() && !MaterialManager::getManager().exists(_material.getUUID())) {
        // lists, arrays, colours, images and long texts are not carried: only a card holds them
        Base::Console().warning("Material '%s' of %s is in no material library here: "
                                "these values are not saved with the document: %s\n",
                                _material.getName().toStdString().c_str(),
                                ownerName(*this).c_str(),
                                dropped.c_str());
    }

    writer.Stream() << writer.ind() << "<PropertyMaterial uuid=\"" << encode(_material.getUUID())
                    << "\" name=\""
                    << encode(_material.getName()) << "\" models=\"" << models.size()
                    << "\" values=\"" << values.size() << "\"";
    if (models.empty() && values.empty() && droppedNames.empty()) {
        writer.Stream() << "/>" << std::endl;
        return;
    }
    writer.Stream() << ">" << std::endl;
    writer.incInd();
    for (auto& uuid : models) {
        writer.Stream() << writer.ind() << "<Model uuid=\"" << encode(uuid) << "\"/>" << std::endl;
    }
    for (auto& [name, attributes] : values) {
        writer.Stream() << writer.ind() << "<Value name=\"" << encode(name) << "\"" << attributes
                        << "/>" << std::endl;
    }
    for (auto& name : droppedNames) {
        writer.Stream() << writer.ind() << "<Dropped name=\"" << encode(name) << "\"/>" << std::endl;
    }
    writer.decInd();
    writer.Stream() << writer.ind() << "</PropertyMaterial>" << std::endl;
}

void PropertyMaterial::Restore(Base::XMLReader& reader)
{
    reader.readElement("PropertyMaterial");
    bool hasUuid = reader.hasAttribute("uuid");
    auto uuid = QString::fromLatin1(reader.getAttribute<const char*>("uuid", ""));
    auto& manager = MaterialManager::getManager();
    std::shared_ptr<Material> card;
    if (manager.exists(uuid)) {
        try {
            card = manager.getMaterial(uuid);
        }
        catch (const MaterialNotFound&) {
        }
    }

    if (!reader.hasAttribute("models")) {
        // A file from before the file carried its materials: only the library can resolve it.
        if (card) {
            setValue(*card);
            return;
        }
        Base::Console().warning("Material %s of %s is in no material library here: "
                                "the part gets the material Default\n",
                                uuid.toStdString().c_str(),
                                ownerName(*this).c_str());
        setValue(*MaterialManager::defaultMaterial());
        return;
    }

    auto name = QString::fromUtf8(reader.getAttribute<const char*>("name", ""));
    // The counts are only compared with the children found, so they are kept as text: a number
    // parsed from a hand-edited file could throw.
    std::string modelCount = reader.getAttribute<const char*>("models", "0");
    std::string valueCount = reader.getAttribute<const char*>("values", "0");
    if (!hasUuid) {
        Base::Console().warning("Material '%s' of %s has no valid UUID (''): "
                                "not added to the user material library\n",
                                name.toStdString().c_str(),
                                ownerName(*this).c_str());
    }

    // The file wins: the library card, when there is one, gives only what the file does not carry.
    Material material = card ? Material(*card) : Material();
    material.setUUID(uuid);
    material.setName(name);
    std::vector<std::string> lost;

    // The children are read one by one up to the element's end, whatever the counts say: a count
    // above the real children must not read on into the document (readElement would).
    long models = 0;
    long values = 0;
    while (reader.readNextElement()) {
        std::string tag = reader.localName();
        if (tag == "Model") {
            ++models;
            restoreModel(material, reader, lost);
        }
        else if (tag == "Value") {
            ++values;
            restoreNamedValue(material, reader, lost);
        }
        else if (tag == "Dropped") {
            // a value the file doesn't carry: the card has it, else the material is incomplete
            if (!card) {
                lost.push_back(
                    QString::fromUtf8(reader.getAttribute<const char*>("name", "")).toStdString()
                    + " (not saved with the document)");
            }
        }
        else {
            lost.push_back("element <" + tag + ">");
        }
    }
    // at the end of this element, or at its parent's end when it was self-closing
    if (std::string(reader.localName()) == "PropertyMaterial") {
        reader.readEndElement("PropertyMaterial");  // returns at once: it is the current element
    }
    if (std::to_string(models) != modelCount || std::to_string(values) != valueCount) {
        lost.push_back(std::to_string(models) + " of " + modelCount + " models and "
                       + std::to_string(values) + " of " + valueCount + " values found");
    }
    if (!lost.empty()) {
        std::string list;
        for (auto& item : lost) {
            list += (list.empty() ? "" : ", ") + item;
        }
        Base::Console().warning("Material '%s' of %s: not known here, not restored: %s\n",
                                name.toStdString().c_str(),
                                ownerName(*this).c_str(),
                                list.c_str());
    }
    setValue(material);
    // only a material restored whole becomes a card
    if (!card && hasUuid && lost.empty() && !material.getPhysicalModels()->isEmpty()
        && openingDocument(*this)) {
        learnMaterial(material, ownerName(*this));
    }
}

const char* PropertyMaterial::getEditorName() const
{
    if (testStatus(MaterialEdit)) {
        return "";  //"Gui::PropertyEditor::PropertyMaterialItem";
    }
    return "";
}

App::Property* PropertyMaterial::Copy() const
{
    PropertyMaterial* p = new PropertyMaterial();
    p->_material = _material;
    return p;
}

void PropertyMaterial::Paste(const App::Property& from)
{
    aboutToSetValue();
    _material = dynamic_cast<const PropertyMaterial&>(from)._material;
    hasSetValue();
}
