// SPDX-License-Identifier: LGPL-2.1-or-later

// FreeCAD-CH ops#671: see ConfigurationHooks.h

#include "ConfigurationHooks.h"

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

}  // namespace App
