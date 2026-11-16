// SPDX-License-Identifier: LGPL-2.1-or-later

// FreeCAD-CH ops#671: see ConfigurationHooks.h

#include "ConfigurationHooks.h"

#include <Base/Exception.h>
#include <Base/Interpreter.h>

#include "Document.h"
#include "DocumentObject.h"

namespace App
{

namespace
{
ExpressionWriteHook& writeHook()
{
    static ExpressionWriteHook hook;
    return hook;
}

ConfigReaderCheck& readerCheck()
{
    static ConfigReaderCheck check;
    return check;
}
}  // namespace

void setExpressionWriteHook(ExpressionWriteHook hook)
{
    writeHook() = std::move(hook);
}

bool callExpressionWriteHook(DocumentObject* owner,
                             const ObjectIdentifier& path,
                             const std::shared_ptr<Expression>& expr)
{
    const auto& hook = writeHook();
    return hook && hook(owner, path, expr);
}

void setConfigReaderCheck(ConfigReaderCheck check)
{
    readerCheck() = std::move(check);
}

std::string callConfigReaderCheck(const DocumentObject* reader, const DocumentObject* source)
{
    const auto& check = readerCheck();
    return check ? check(reader, source) : std::string();
}

namespace
{
ConfiguredQuery& configuredQuery()
{
    static ConfiguredQuery query;
    return query;
}
}  // namespace

void setConfiguredQuery(ConfiguredQuery query)
{
    configuredQuery() = std::move(query);
}

std::string callConfiguredQuery(const DocumentObject* obj, const ObjectIdentifier& path)
{
    const auto& query = configuredQuery();
    return query && obj ? query(obj, path) : std::string();
}

namespace
{
ConfigMenuQuery& menuQuery()
{
    static ConfigMenuQuery query;
    return query;
}
}  // namespace

void setConfigMenuQuery(ConfigMenuQuery query)
{
    menuQuery() = std::move(query);
}

std::vector<ConfigMenuItem> callConfigMenuQuery(const DocumentObject* obj, const ObjectIdentifier& path)
{
    const auto& query = menuQuery();
    return query && obj ? query(obj, path) : std::vector<ConfigMenuItem>();
}

namespace
{
/// text as a Python string literal
std::string pyString(const std::string& text)
{
    std::string out = "'";
    for (char c : text) {
        if (c == '\\' || c == '\'') {
            out += '\\';
        }
        if (c == '\n') {
            out += "\\n";
            continue;
        }
        out += c;
    }
    return out + "'";
}
}  // namespace

void runConfigMenuItem(const DocumentObject* obj, const std::string& path, const ConfigMenuItem& item)
{
    if (!obj || !obj->isAttachedToDocument()) {
        return;
    }
    const std::string code = "import FreeCAD\nfrom PartDesign import ConfigurationsGui\n"
                             "ConfigurationsGui.fieldAction(FreeCAD.getDocument("
        + pyString(obj->getDocument()->getName()) + ").getObject(" + pyString(obj->getNameInDocument())
        + "), " + pyString(path) + ", " + pyString(item.action) + ", " + pyString(item.input) + ")\n";
    try {
        Base::Interpreter().runString(code.c_str());
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

}  // namespace App
