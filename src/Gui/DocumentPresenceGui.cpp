// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 6, design A's B5).

#include <QLabel>
#include <QMessageBox>
#include <QPointer>
#include <QPushButton>
#include <QStatusBar>
#include <QTimer>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentPresence.h>

#include "Application.h"
#include "Document.h"
#include "DocumentPresenceGui.h"
#include "MainWindow.h"

namespace Gui::DocumentPresenceGui
{

namespace
{

QPointer<QLabel>& label()
{
    static QPointer<QLabel> widget;
    return widget;
}

void updateLabel()
{
    QLabel* widget = label();
    if (!widget) {
        return;
    }
    const QString text = QString::fromStdString(statusText());
    widget->setText(text);
    widget->setToolTip(
        text.isEmpty() ? QString()
                       : QObject::tr("Saving here while they work can make two versions; "
                                     "the save guard will ask which to keep.")
    );
}

}  // namespace

std::string statusText()
{
    App::Document* document = App::GetApplication().getActiveDocument();
    if (!document) {
        return {};
    }
    const std::string file = document->FileName.getValue();
    if (file.empty()) {
        return {};
    }
    return App::DocumentPresence::describe(App::DocumentPresence::others(file));
}

void refreshNow()
{
    App::DocumentPresence::refresh();
    updateLabel();
}

bool confirmOpen(const std::string& fileName, QWidget* parent)
{
    const auto markers = App::DocumentPresence::others(fileName);
    if (markers.empty()) {
        return true;
    }
    QMessageBox box(parent);
    box.setObjectName(QStringLiteral("PresenceQuestion"));
    box.setIcon(QMessageBox::Information);
    box.setWindowTitle(QObject::tr("Document open elsewhere"));
    box.setText(QString::fromStdString(App::DocumentPresence::describe(markers)) + QStringLiteral("."));
    box.setInformativeText(
        QObject::tr("If you both save, the second save will ask which version to keep.")
    );
    QPushButton* open = box.addButton(QObject::tr("Open anyway"), QMessageBox::AcceptRole);
    open->setObjectName(QStringLiteral("PresenceOpenAnyway"));
    QPushButton* cancel = box.addButton(QMessageBox::Cancel);
    cancel->setObjectName(QStringLiteral("PresenceCancel"));
    box.setDefaultButton(open);
    box.exec();
    return box.clickedButton() == open;
}

void start(MainWindow* mainWindow)
{
    auto* widget = new QLabel(mainWindow->statusBar());
    label() = widget;
    mainWindow->addStatusBarItem(
        widget,
        {.id = "presenceLabel",
         .title = QObject::tr("Who else has the document open"),
         .slot = StatusBarSlot::Right,
         .order = 10,
         .persistentVisibility = true}
    );

    auto* timer = new QTimer(mainWindow);
    timer->setObjectName(QStringLiteral("PresenceHeartbeat"));
    timer->setInterval(App::DocumentPresence::heartbeatSeconds * 1000);
    QObject::connect(timer, &QTimer::timeout, [] { refreshNow(); });
    timer->start();

    // The line follows the active document, and a newly opened or saved one at once
    Gui::Application::Instance->signalActiveDocument.connect([](const Gui::Document&) {
        QTimer::singleShot(0, [] { updateLabel(); });
    });
    App::GetApplication().signalDeleteDocument.connect([](const App::Document&) {
        QTimer::singleShot(0, [] { updateLabel(); });
    });
}

}  // namespace Gui::DocumentPresenceGui
