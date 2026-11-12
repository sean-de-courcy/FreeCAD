/***************************************************************************
 *   Copyright (c) 2002 Jürgen Riegel <juergen.riegel@web.de>              *
 *   Copyright (c) 2014 Luke Parry <l.parry@warwick.ac.uk>                 *
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

#include <QApplication>
#include <QFileInfo>
#include <QMessageBox>
#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QGraphicsRectItem>
#include <QGraphicsScene>
#include <QGraphicsSimpleTextItem>
#include <QKeyEvent>
#include <QLabel>
#include <QListWidget>
#include <QMouseEvent>
#include <QPen>
#include <QPushButton>
#include <QVBoxLayout>
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <numbers>
#include <optional>
#include <set>
#include <vector>

#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>
#include <TopExp_Explorer.hxx>


#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/DocumentObserver.h>
#include <App/DocumentTabs.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/Link.h>

#include <Base/Console.h>
#include <Base/Tools.h>

#include <Gui/Action.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/FileDialog.h>
#include <Gui/MainWindow.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Selection/SelectionObject.h>
#include <Gui/ViewProvider.h>
#include <Gui/WaitCursor.h>

#include <Mod/Part/App/PartFeature.h>
#include <Mod/Spreadsheet/App/Sheet.h>

#include <Mod/TechDraw/App/DrawComplexSection.h>
#include <Mod/TechDraw/App/DrawPage.h>
#include <Mod/TechDraw/App/DrawProjGroup.h>
#include <Mod/TechDraw/App/DrawProjGroupItem.h>
#include <Mod/TechDraw/App/ShapeExtractor.h>
#include <Mod/TechDraw/App/DrawUtil.h>
#include <Mod/TechDraw/App/DrawSVGTemplate.h>
#include <Mod/TechDraw/App/DrawViewArch.h>
#include <Mod/TechDraw/App/DrawViewClip.h>
#include <Mod/TechDraw/App/DrawViewDetail.h>
#include <Mod/TechDraw/App/DrawViewDraft.h>
#include <Mod/TechDraw/App/DrawViewPart.h>
#include <Mod/TechDraw/App/DrawViewSymbol.h>
#include <Mod/TechDraw/App/Preferences.h>
#include <Mod/TechDraw/App/DrawBrokenView.h>

#include "DrawGuiUtil.h"
#include "MDIViewPage.h"
#include "QGIView.h"
#include "QGIViewPart.h"
#include "QGSPage.h"
#include "QGVPage.h"
#include "Rez.h"
#include "TaskActiveView.h"
#include "TaskComplexSection.h"
#include "TaskDetail.h"
#include "TaskProjGroup.h"
#include "TaskProjection.h"
#include "TaskSectionView.h"
#include "TechDrawHandler.h"
#include "ViewProviderPage.h"
#include "ViewProviderDrawingView.h"
#include "CommandHelpers.h"

void execSimpleSection(Gui::Command* cmd);
void execComplexSection(Gui::Command* cmd);
void getSelectedShapes(Gui::Command* cmd,
                      std::vector<App::DocumentObject*>& shapes,
                      std::vector<App::DocumentObject*>& xShapes,
                      App::DocumentObject* faceObj,
                      std::string& faceName);

std::pair<App::DocumentObject*, std::string> faceFromSelection();
std::pair<Base::Vector3d, Base::Vector3d> viewDirection();
Base::Vector3d checkDirectionVsBasis(Base::Vector3d dir);

class Vertex;
using namespace TechDrawGui;
using namespace TechDraw;
using DU = DrawUtil;

//===========================================================================
// TechDraw_PageDefault
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawPageDefault)

CmdTechDrawPageDefault::CmdTechDrawPageDefault() : Command("TechDraw_PageDefault")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("New Page");
    sToolTipText = QT_TR_NOOP("Creates a new page with the default template");
    sWhatsThis = "TechDraw_PageDefault";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_PageDefault";
}

void CmdTechDrawPageDefault::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    QString templateFileName = Preferences::defaultTemplate();
    QFileInfo tfi(templateFileName);
    if (tfi.isReadable()) {
        Gui::WaitCursor wc;
        openCommand(QT_TRANSLATE_NOOP("Command", "Drawing create page"));

        auto page = getDocument()->addObject<TechDraw::DrawPage>("Page");
        if (!page) {
            throw Base::TypeError("CmdTechDrawPageDefault - page not created");
        }
        page->translateLabel("DrawPage", "Page", page->getNameInDocument());

        auto svgTemplate = getDocument()->addObject<TechDraw::DrawSVGTemplate>("Template");
        if (!svgTemplate) {
            throw Base::TypeError("CmdTechDrawPageDefault - template not created");
        }
        svgTemplate->translateLabel("DrawSVGTemplate", "Template", svgTemplate->getNameInDocument());

        page->Template.setValue(svgTemplate);
        auto filespec = DU::cleanFilespecBackslash(templateFileName.toStdString());
        svgTemplate->Template.setValue(filespec);

        updateActive();
        commitCommand();

        TechDrawGui::ViewProviderPage *dvp = dynamic_cast<TechDrawGui::ViewProviderPage *>
                                                 (Gui::Application::Instance->getViewProvider(page));
        if (dvp) {
            dvp->show();
        }
    }
    else {
        QMessageBox::critical(Gui::getMainWindow(), QLatin1String("No template"),
                              QLatin1String("No default template found"));
    }
}

bool CmdTechDrawPageDefault::isActive() { return hasActiveDocument(); }

//===========================================================================
// TechDraw_PageTemplate
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawPageTemplate)

CmdTechDrawPageTemplate::CmdTechDrawPageTemplate() : Command("TechDraw_PageTemplate")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("New Page From Template");
    sToolTipText = QT_TR_NOOP("Creates a new page from a custom template");
    sWhatsThis = "TechDraw_PageTemplate";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_PageTemplate";
}

void CmdTechDrawPageTemplate::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    QString work_dir = Gui::FileDialog::getWorkingDirectory();
    QString templateDir = Preferences::defaultTemplateDir();
    QString templateFileName = Gui::FileDialog::getOpenFileName(
        Gui::getMainWindow(), QObject::tr("Select a template file"), templateDir,
        Gui::FileDialog::FilterList{{QObject::tr("Template"), {"*.svg"}}});
    Gui::FileDialog::setWorkingDirectory(work_dir);// Don't overwrite WD with templateDir

    if (templateFileName.isEmpty()) {
        return;
    }

    QFileInfo tfi(templateFileName);
    if (tfi.isReadable()) {
        Gui::WaitCursor wc;
        openCommand(QT_TRANSLATE_NOOP("Command", "Drawing create page"));

        auto page = getDocument()->addObject<TechDraw::DrawPage>("Page");
        if (!page) {
            throw Base::TypeError("CmdTechDrawPageTemplate - page not created");
        }
        page->translateLabel("DrawPage", "Page", page->getNameInDocument());

        auto svgTemplate = getDocument()->addObject<TechDraw::DrawSVGTemplate>("Template");
        if (!svgTemplate) {
            throw Base::TypeError("CmdTechDrawPageTemplate - template not created");
        }
        svgTemplate->translateLabel("DrawSVGTemplate", "Template", svgTemplate->getNameInDocument());

        page->Template.setValue(svgTemplate);
        auto filespec = DU::cleanFilespecBackslash(templateFileName.toStdString());
        svgTemplate->Template.setValue(filespec);

        updateActive();
        commitCommand();

        TechDrawGui::ViewProviderPage *dvp = dynamic_cast<TechDrawGui::ViewProviderPage *>
                                                 (Gui::Application::Instance->getViewProvider(page));
        if (dvp) {
            dvp->show();
        }
    }
    else {
        QMessageBox::critical(Gui::getMainWindow(), QLatin1String("No template"),
                              QLatin1String("Template file is invalid"));
    }
}

bool CmdTechDrawPageTemplate::isActive() { return hasActiveDocument(); }

//===========================================================================
// TechDraw_RedrawPage
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawRedrawPage)

CmdTechDrawRedrawPage::CmdTechDrawRedrawPage() : Command("TechDraw_RedrawPage")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Redraw Page");
    sToolTipText = QT_TR_NOOP("Redraws the current page");
    sWhatsThis = "TechDraw_RedrawPage";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_RedrawPage";
}

void CmdTechDrawRedrawPage::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    Gui::WaitCursor wc;

    page->redrawCommand();
}

bool CmdTechDrawRedrawPage::isActive()
{
    bool havePage = DrawGuiUtil::needPage(this);
    bool haveView = DrawGuiUtil::needView(this, false);
    return (havePage && haveView);
}

//===========================================================================
// TechDraw_PrintAll
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawPrintAll)

CmdTechDrawPrintAll::CmdTechDrawPrintAll() : Command("TechDraw_PrintAll")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Print All Pages");
    sToolTipText = QT_TR_NOOP("Prints all pages with the print dialog");
    sWhatsThis = "TechDraw_PrintAll";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_PrintAll";
}

void CmdTechDrawPrintAll::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    MDIViewPage::printAllPages();
}

bool CmdTechDrawPrintAll::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// FreeCAD-CH (design D, slice V1, ops#640): Insert View and Project View, as Onshape's
// (oracle 11, GD-B2): Insert view asks what to draw (the document's parts, studios and
// assemblies, never a file browser), the orientation and the scale; one click places the view;
// a projection then follows the cursor (right of it a right view, a diagonal an isometric) and a
// click places it, until Esc. From a group's front view the projection joins the group, aligned;
// from any other view it is a free view in the projected direction.
//===========================================================================

namespace
{

/// What Insert View can draw: a part, a studio (its parts) or an assembly
struct ViewSource
{
    QString text;
    std::vector<App::DocumentObject*> objects;
    std::vector<App::DocumentObject*> xObjects;
};

/// Onshape's view orientations: the direction the view looks from, and its page right
struct ViewOrientation
{
    const char* name;
    Base::Vector3d direction;
    Base::Vector3d xDirection;
};

const std::array<ViewOrientation, 7>& viewOrientations()
{
    static const double r3 = 1.0 / std::sqrt(3.0);
    static const double r2 = 1.0 / std::sqrt(2.0);
    static const std::array<ViewOrientation, 7> list {{
        {QT_TRANSLATE_NOOP("TechDraw_InsertView", "Front"), Base::Vector3d(0, -1, 0), Base::Vector3d(1, 0, 0)},
        {QT_TRANSLATE_NOOP("TechDraw_InsertView", "Back"), Base::Vector3d(0, 1, 0), Base::Vector3d(-1, 0, 0)},
        {QT_TRANSLATE_NOOP("TechDraw_InsertView", "Top"), Base::Vector3d(0, 0, 1), Base::Vector3d(1, 0, 0)},
        {QT_TRANSLATE_NOOP("TechDraw_InsertView", "Bottom"), Base::Vector3d(0, 0, -1), Base::Vector3d(1, 0, 0)},
        {QT_TRANSLATE_NOOP("TechDraw_InsertView", "Left"), Base::Vector3d(-1, 0, 0), Base::Vector3d(0, -1, 0)},
        {QT_TRANSLATE_NOOP("TechDraw_InsertView", "Right"), Base::Vector3d(1, 0, 0), Base::Vector3d(0, 1, 0)},
        {QT_TRANSLATE_NOOP("TechDraw_InsertView", "Isometric"), Base::Vector3d(r3, -r3, r3), Base::Vector3d(r2, r2, 0)},
    }};
    return list;
}

const std::array<double, 9>& standardScales()
{
    static const std::array<double, 9> list {0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 4.0, 5.0, 10.0};
    return list;
}

Gui::Document* guiDocument(App::Document* doc)
{
    return Gui::Application::Instance->getDocument(doc);
}

bool hasSolid(const App::DocumentObject* obj)
{
    try {
        const TopoDS_Shape shape = Part::Feature::getShape(
            obj, Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform);
        return !shape.IsNull() && TopExp_Explorer(shape, TopAbs_SOLID).More();
    }
    catch (...) {
        return false;
    }
}

/// A studio's parts, as its Parts list shows them: its Bodies with a solid, and the other solids
/// that no shape of the studio reads (a Part workbench feature, an import)
std::vector<App::DocumentObject*> partsOf(const std::vector<App::DocumentObject*>& members)
{
    static const Base::Type bodyType = Base::Type::fromName("PartDesign::Body");
    const std::set<App::DocumentObject*> inStudio(members.begin(), members.end());
    std::vector<App::DocumentObject*> parts;
    for (auto* obj : members) {
        if (!obj || obj->isDerivedFrom<TechDraw::DrawView>() || !hasSolid(obj)) {
            continue;
        }
        if (!bodyType.isBad() && obj->isDerivedFrom(bodyType)) {
            parts.push_back(obj);
            continue;
        }
        if (!obj->isDerivedFrom<Part::Feature>()) {
            continue;
        }
        auto* group = App::GeoFeatureGroupExtension::getGroupOfObject(obj);
        if (group && !bodyType.isBad() && group->isDerivedFrom(bodyType)) {
            continue;  // a Body's feature: the Body is the part
        }
        bool read = false;
        for (auto* user : obj->getInList()) {
            if (inStudio.count(user) && user->isDerivedFrom<Part::Feature>()
                && !user->isDerivedFrom<TechDraw::DrawView>()) {
                read = true;
                break;
            }
        }
        if (!read) {
            parts.push_back(obj);
        }
    }
    return parts;
}

QString labelOf(const App::DocumentObject* obj)
{
    return QString::fromUtf8(obj->Label.getValue());
}

/// The document's parts, then each studio (all its parts) and each assembly, by its tabs
std::vector<ViewSource> drawableSources(App::Document* doc)
{
    namespace Tabs = App::DocumentTabs;
    std::vector<ViewSource> parts;
    std::vector<ViewSource> wholes;
    std::vector<Tabs::Tab> tabs = Tabs::tabs(doc);
    if (tabs.empty()) {
        for (auto* part : partsOf(doc->getObjects())) {
            parts.push_back({labelOf(part), {part}, {}});
        }
        return parts;
    }
    for (const auto& tab : tabs) {
        const QString tabLabel = QString::fromUtf8(Tabs::label(doc, tab).c_str());
        if (tab.kind == Tabs::Kind::PartStudio) {
            std::vector<App::DocumentObject*> studioParts = partsOf(Tabs::members(doc, tab));
            for (auto* part : studioParts) {
                parts.push_back({labelOf(part), {part}, {}});
            }
            if (studioParts.size() > 1) {
                wholes.push_back({QCoreApplication::translate("TechDraw_InsertView", "%1 (Part Studio)")
                                      .arg(tabLabel),
                                  studioParts,
                                  {}});
            }
        }
        else if (tab.kind == Tabs::Kind::Assembly && tab.object) {
            wholes.push_back(
                {QCoreApplication::translate("TechDraw_InsertView", "%1 (Assembly)").arg(tabLabel),
                 {tab.object},
                 {}});
        }
    }
    parts.insert(parts.end(), wholes.begin(), wholes.end());
    return parts;
}

std::string pyObject(const App::DocumentObject* obj)
{
    return std::string("App.getDocument('") + obj->getDocument()->getName() + "').getObject('"
        + obj->getNameInDocument() + "')";
}

/// Python's text for a list of objects
std::string pyList(const std::vector<App::DocumentObject*>& objects)
{
    std::string text = "[";
    for (auto* obj : objects) {
        text += pyObject(obj) + ", ";
    }
    return text + "]";
}

std::string pyVector(const Base::Vector3d& v)
{
    char text[128];
    snprintf(text, sizeof(text), "FreeCAD.Vector(%.12f, %.12f, %.12f)", v.x, v.y, v.z);
    return text;
}

/// The page point (mm, +Y up) under a mouse event on the page's view
Base::Vector3d pagePoint(QGVPage* viewPage, QMouseEvent* event)
{
    const QPointF scene = viewPage->mapToScene(event->pos());
    return Base::Vector3d(Rez::appX(scene.x()), -Rez::appX(scene.y()), 0.0);
}

/// The size on the page (mm) of `sources` seen from `direction` with page right `xDirection`
QSizeF projectedSize(const std::vector<App::DocumentObject*>& sources,
                     const Base::Vector3d& direction,
                     const Base::Vector3d& xDirection,
                     double scale)
{
    Bnd_Box box;
    try {
        TopoDS_Shape shape = TechDraw::ShapeExtractor::getShapes(sources, false);
        if (!shape.IsNull()) {
            BRepBndLib::Add(shape, box);
        }
    }
    catch (...) {
    }
    if (box.IsVoid()) {
        return {20.0, 20.0};
    }
    double x0, y0, z0, x1, y1, z1;
    box.Get(x0, y0, z0, x1, y1, z1);
    const Base::Vector3d up = direction.Cross(xDirection);
    const double big = std::numeric_limits<double>::max();
    double minX = big, maxX = -big, minY = big, maxY = -big;
    for (int i = 0; i < 8; ++i) {
        const Base::Vector3d corner(i & 1 ? x1 : x0, i & 2 ? y1 : y0, i & 4 ? z1 : z0);
        minX = std::min(minX, corner * xDirection);
        maxX = std::max(maxX, corner * xDirection);
        minY = std::min(minY, corner * up);
        maxY = std::max(maxY, corner * up);
    }
    return {(maxX - minX) * scale, (maxY - minY) * scale};
}

/// A dashed frame with a name that follows the cursor: where the next view lands
class ViewPreview
{
public:
    void show(QGVPage* viewPage, const Base::Vector3d& at, const QSizeF& size, const QString& name)
    {
        if (!viewPage || !viewPage->scene()) {
            return;
        }
        if (!frame) {
            frame = new QGraphicsRectItem();
            QPen pen(QColor(0x30, 0x70, 0xd0));
            pen.setStyle(Qt::DashLine);
            pen.setCosmetic(true);
            frame->setPen(pen);
            frame->setZValue(1000.0);
            viewPage->scene()->addItem(frame);
            label = new QGraphicsSimpleTextItem();
            label->setBrush(QColor(0x30, 0x70, 0xd0));
            label->setZValue(1000.0);
            viewPage->scene()->addItem(label);
        }
        const double w = Rez::guiX(size.width());
        const double h = Rez::guiX(size.height());
        const QPointF centre(Rez::guiX(at.x), -Rez::guiX(at.y));
        frame->setRect(QRectF(centre.x() - w / 2.0, centre.y() - h / 2.0, w, h));
        label->setText(name);
        label->setPos(centre.x() - w / 2.0, centre.y() + h / 2.0);
        frame->show();
        label->show();
    }

    void hide()
    {
        if (frame) {
            frame->hide();
            label->hide();
        }
    }

    void remove()
    {
        delete frame;
        delete label;
        frame = nullptr;
        label = nullptr;
    }

private:
    QGraphicsRectItem* frame {nullptr};
    QGraphicsSimpleTextItem* label {nullptr};
};

bool activatePageHandler(TechDrawHandler* handler)
{
    std::unique_ptr<TechDrawHandler> owned(handler);
    auto* mdi = qobject_cast<MDIViewPage*>(Gui::getMainWindow()->activeWindow());
    ViewProviderPage* vp = mdi ? mdi->getViewProviderPage() : nullptr;
    QGVPage* viewPage = vp ? vp->getQGVPage() : nullptr;
    if (!viewPage) {
        return false;
    }
    viewPage->activateHandler(owned.release());
    return true;
}

/// The page position of a view's middle: a group's item is placed relative to its group
Base::Vector3d viewMiddle(const TechDraw::DrawViewPart* view)
{
    Base::Vector3d at(view->X.getValue(), view->Y.getValue(), 0.0);
    auto* item = dynamic_cast<const TechDraw::DrawProjGroupItem*>(view);
    if (auto* group = item ? item->getPGroup() : nullptr) {
        at += Base::Vector3d(group->X.getValue(), group->Y.getValue(), 0.0);
    }
    return at;
}

/// The projection a move from a view's middle asks for, by TechDraw's names in third angle
/// (Right is to the right): within 22.5 degrees of an axis an orthographic view, between them
/// an isometric. Nothing until the cursor is 5 mm away.
const char* projectionOfMove(double dx, double dy, bool firstAngle)
{
    if (std::hypot(dx, dy) < 5.0) {
        return nullptr;
    }
    static const std::array<const char*, 8> third {"Right", "FrontTopRight", "Top", "FrontTopLeft",
                                                  "Left", "FrontBottomLeft", "Bottom",
                                                  "FrontBottomRight"};
    const int sector = static_cast<int>(std::lround(std::atan2(dy, dx) / (std::numbers::pi / 4.0)));
    int index = (sector + 8) % 8;
    if (firstAngle) {
        // first angle puts each projection on the far side: the view of the left on the right
        index = (index + 4) % 8;
    }
    return third[index];
}

/// The direction and page right of the projection `type` (TechDraw's names) of a view looking
/// from `d` with page right `x`
std::pair<Base::Vector3d, Base::Vector3d>
projectedFrame(const std::string& type, const Base::Vector3d& d, const Base::Vector3d& x)
{
    const Base::Vector3d up = d.Cross(x);
    auto iso = [&](double sx, double sy) {
        Base::Vector3d dir = d + x * sx + up * sy;
        dir.Normalize();
        Base::Vector3d right = up.Cross(dir);
        right.Normalize();
        return std::make_pair(dir, right);
    };
    if (type == "Right") {
        return std::make_pair(x, -d);
    }
    if (type == "Left") {
        return std::make_pair(-x, d);
    }
    if (type == "Top") {
        return std::make_pair(up, x);
    }
    if (type == "Bottom") {
        return std::make_pair(-up, x);
    }
    if (type == "FrontTopRight") {
        return iso(1, 1);
    }
    if (type == "FrontTopLeft") {
        return iso(-1, 1);
    }
    if (type == "FrontBottomRight") {
        return iso(1, -1);
    }
    return iso(-1, -1);  // FrontBottomLeft
}

QString projectionName(const std::string& type)
{
    if (type.rfind("Front", 0) == 0 && type != "Front") {
        return QCoreApplication::translate("TechDraw_InsertView", "Isometric");
    }
    return QCoreApplication::translate("TechDraw_InsertView", type.c_str());
}

/// Project View's tool: click a view (or start on one), move, click; Esc ends
class ProjectViewHandler: public TechDrawHandler
{
public:
    explicit ProjectViewHandler(TechDraw::DrawViewPart* parent)
    {
        if (parent) {
            parentT = App::DocumentObjectT(parent);
        }
    }

    void deactivated() override
    {
        preview.remove();
    }

    void mouseMoveEvent(QMouseEvent* event) override
    {
        auto* parent = parentView();
        if (!parent) {
            preview.hide();
            return;
        }
        const Base::Vector3d at = pagePoint(viewPage, event);
        Projection next = projectionAt(parent, at);
        if (next.type.empty()) {
            preview.hide();
            return;
        }
        if (next.type != sizeType || parent != sizeParent) {
            // the shape is read once a projection, not at every move
            size = projectedSize(parent->getAllSources(), next.direction, next.xDirection,
                                 parent->getScale());
            sizeType = next.type;
            sizeParent = parent;
        }
        preview.show(viewPage, next.at, size, projectionName(next.type));
    }

    void mousePressEvent(QMouseEvent* event) override
    {
        if (event->button() != Qt::LeftButton) {
            return;
        }
        const Base::Vector3d at = pagePoint(viewPage, event);
        auto* parent = parentView();
        if (!parent) {
            // the view clicked is the parent; the next click places its projection
            if (auto* picked = viewUnder(at)) {
                parentT = App::DocumentObjectT(picked);
            }
            return;
        }
        Projection next = projectionAt(parent, at);
        if (next.type.empty()) {
            return;
        }
        place(parent, next);
        preview.hide();
    }

    void keyPressEvent(QKeyEvent* event) override
    {
        if (event->key() == Qt::Key_Escape) {
            event->accept();  // the release ends the tool
        }
    }

private:
    struct Projection
    {
        std::string type;  // TechDraw's name; empty for none
        Base::Vector3d at;
        Base::Vector3d direction;
        Base::Vector3d xDirection;
        bool joinsGroup {false};
    };

    TechDraw::DrawViewPart* parentView() const
    {
        return dynamic_cast<TechDraw::DrawViewPart*>(parentT.getObject());
    }

    /// The view whose box holds the point (the smallest, when boxes overlap): a click inside a
    /// view picks it, edge or not. The boxes are the views' own (page position and geometry),
    /// as the sheet draws them
    TechDraw::DrawViewPart* viewUnder(const Base::Vector3d& at)
    {
        auto* page = getPage();
        if (!page) {
            return nullptr;
        }
        TechDraw::DrawViewPart* best = nullptr;
        double bestArea = std::numeric_limits<double>::max();
        for (auto* obj : page->getAllViews()) {
            auto* view = dynamic_cast<TechDraw::DrawViewPart*>(obj);
            if (!view || !view->Visibility.getValue()) {
                continue;
            }
            const Base::BoundBox3d bb = view->getBoundingBox();  // scaled, about the middle, +Y down
            const Base::Vector3d middle = viewMiddle(view);
            const double margin = 2.0;  // mm: a click on the outline counts
            const bool inside = at.x >= middle.x + bb.MinX - margin && at.x <= middle.x + bb.MaxX + margin
                && at.y >= middle.y - bb.MaxY - margin && at.y <= middle.y - bb.MinY + margin;
            const double area = bb.LengthX() * bb.LengthY();
            if (inside && area < bestArea) {
                best = view;
                bestArea = area;
            }
        }
        return best;
    }

    static TechDraw::DrawProjGroup* anchorGroup(TechDraw::DrawViewPart* view)
    {
        auto* item = dynamic_cast<TechDraw::DrawProjGroupItem*>(view);
        auto* group = item ? item->getPGroup() : nullptr;
        return group && group->getAnchor() == item ? group : nullptr;
    }

    static bool firstAngle(TechDraw::DrawViewPart* view)
    {
        auto* item = dynamic_cast<TechDraw::DrawProjGroupItem*>(view);
        if (auto* group = item ? item->getPGroup() : nullptr) {
            return group->usedProjectionType().isValue("First angle");
        }
        auto* page = view->findParentPage();
        return page && page->ProjectionType.isValue("First angle");
    }

    Projection projectionAt(TechDraw::DrawViewPart* parent, const Base::Vector3d& at) const
    {
        Projection next;
        const Base::Vector3d middle = viewMiddle(parent);
        const char* type = projectionOfMove(at.x - middle.x, at.y - middle.y, firstAngle(parent));
        if (!type) {
            return next;
        }
        next.type = type;
        next.at = at;
        // an orthographic projection stays aligned with its parent
        if (next.type == "Right" || next.type == "Left") {
            next.at.y = middle.y;
        }
        else if (next.type == "Top" || next.type == "Bottom") {
            next.at.x = middle.x;
        }
        Base::Vector3d d = parent->Direction.getValue();
        d.Normalize();
        Base::Vector3d x = parent->getXDirection();
        x.Normalize();
        std::tie(next.direction, next.xDirection) = projectedFrame(next.type, d, x);
        next.joinsGroup = anchorGroup(parent) != nullptr;
        return next;
    }

    void place(TechDraw::DrawViewPart* parent, const Projection& next)
    {
        App::Document* doc = parent->getDocument();
        if (auto* group = anchorGroup(parent)) {
            if (group->hasProjection(next.type.c_str())) {
                Gui::getMainWindow()->showMessage(
                    QCoreApplication::translate("TechDraw_ProjectView", "The group has that view already"),
                    3000);
                return;
            }
            guiDocument(doc)->openCommand(QT_TRANSLATE_NOOP("Command", "Projected view"));
            Gui::Command::doCommand(Gui::Command::Doc, "%s.addProjection('%s')",
                                    pyObject(group).c_str(), next.type.c_str());
            Gui::Command::doCommand(Gui::Command::Doc, "%s.recompute()",
                                    pyObject(group).c_str());
            guiDocument(doc)->commitCommand();
            return;
        }
        // a free view: from a view that is not a group's front view
        auto* page = parent->findParentPage();
        if (!page) {
            return;
        }
        std::string scaleType = parent->ScaleType.getValueAsString();
        double scale = parent->getScale();
        auto* item = dynamic_cast<TechDraw::DrawProjGroupItem*>(parent);
        if (auto* group = item ? item->getPGroup() : nullptr) {
            scaleType = group->ScaleType.getValueAsString();
        }
        if (scaleType == "Automatic") {
            scaleType = "Custom";
        }
        const std::string name = doc->getUniqueObjectName("View");
        const std::string view = std::string("App.getDocument('") + doc->getName()
            + "').getObject('" + name + "')";
        guiDocument(doc)->openCommand(QT_TRANSLATE_NOOP("Command", "Projected view"));
        Gui::Command::doCommand(Gui::Command::Doc,
                                "App.getDocument('%s').addObject('TechDraw::DrawProjGroupItem', '%s')",
                                doc->getName(), name.c_str());
        Gui::Command::doCommand(Gui::Command::Doc, "%s.translateLabel('DrawProjGroupItem', 'View', '%s')",
                                view.c_str(), name.c_str());
        Gui::Command::doCommand(Gui::Command::Doc, "%s.addView(%s)", pyObject(page).c_str(), view.c_str());
        Gui::Command::doCommand(Gui::Command::Doc, "%s.Source = %s.Source", view.c_str(),
                                pyObject(parent).c_str());
        Gui::Command::doCommand(Gui::Command::Doc, "%s.XSource = %s.XSource", view.c_str(),
                                pyObject(parent).c_str());
        Gui::Command::doCommand(Gui::Command::Doc, "%s.Direction = %s", view.c_str(),
                                pyVector(next.direction).c_str());
        Gui::Command::doCommand(Gui::Command::Doc, "%s.XDirection = %s", view.c_str(),
                                pyVector(next.xDirection).c_str());
        Gui::Command::doCommand(Gui::Command::Doc, "%s.ScaleType = '%s'", view.c_str(), scaleType.c_str());
        Gui::Command::doCommand(Gui::Command::Doc, "%s.Scale = %.12g", view.c_str(), scale);
        Gui::Command::doCommand(Gui::Command::Doc, "%s.X = %.6f", view.c_str(), next.at.x);
        Gui::Command::doCommand(Gui::Command::Doc, "%s.Y = %.6f", view.c_str(), next.at.y);
        Gui::Command::doCommand(Gui::Command::Doc, "%s.recompute()", view.c_str());
        guiDocument(doc)->commitCommand();
    }

    App::DocumentObjectT parentT;
    ViewPreview preview;
    std::string sizeType;
    const TechDraw::DrawViewPart* sizeParent {nullptr};
    QSizeF size;
};

/// Insert View's choice: what, which way, what scale (0: the sheet's)
struct InsertChoice
{
    ViewSource source;
    int orientation {0};
    double scale {0.0};
};

/// Insert View's tool after the dialog: the view's frame follows the cursor, a click places it
/// and the projection tool takes over on it
class PlaceViewHandler: public TechDrawHandler
{
public:
    explicit PlaceViewHandler(InsertChoice choice)
        : choice(std::move(choice))
    {}

    void deactivated() override
    {
        preview.remove();
    }

    void mouseMoveEvent(QMouseEvent* event) override
    {
        const ViewOrientation& orient = viewOrientations()[choice.orientation];
        if (!size) {
            auto* page = getPage();
            const double scale =
                choice.scale > 0.0 ? choice.scale : (page ? page->Scale.getValue() : 1.0);
            std::vector<App::DocumentObject*> all = choice.source.objects;
            all.insert(all.end(), choice.source.xObjects.begin(), choice.source.xObjects.end());
            size = projectedSize(all, orient.direction, orient.xDirection, scale);
        }
        preview.show(viewPage, pagePoint(viewPage, event), *size,
                     QCoreApplication::translate("TechDraw_InsertView", orient.name));
    }

    void mousePressEvent(QMouseEvent* event) override
    {
        if (event->button() != Qt::LeftButton) {
            return;
        }
        auto* anchor = place(pagePoint(viewPage, event));
        QGVPage* page = viewPage;
        if (!anchor) {
            quit();
            return;  // no code after: quit() deleted this handler
        }
        // the projection follows the cursor from the new view (GD-B2)
        page->activateHandler(new ProjectViewHandler(anchor));
        // no code after: activateHandler() deleted this handler
    }

    void keyPressEvent(QKeyEvent* event) override
    {
        if (event->key() == Qt::Key_Escape) {
            event->accept();
        }
    }

private:
    TechDraw::DrawProjGroupItem* place(const Base::Vector3d& at)
    {
        auto* page = getPage();
        if (!page || (choice.source.objects.empty() && choice.source.xObjects.empty())) {
            return nullptr;
        }
        App::Document* doc = page->getDocument();
        const ViewOrientation& orient = viewOrientations()[choice.orientation];
        const std::string name = doc->getUniqueObjectName("ProjGroup");
        const std::string group = std::string("App.getDocument('") + doc->getName()
            + "').getObject('" + name + "')";
        guiDocument(doc)->openCommand(QT_TRANSLATE_NOOP("Command", "Insert view"));
        try {
            Gui::Command::doCommand(Gui::Command::Doc,
                                    "App.getDocument('%s').addObject('TechDraw::DrawProjGroup', '%s')",
                                    doc->getName(), name.c_str());
            Gui::Command::doCommand(Gui::Command::Doc, "%s.addView(%s)", pyObject(page).c_str(),
                                    group.c_str());
            Gui::Command::doCommand(Gui::Command::Doc, "%s.Source = %s", group.c_str(),
                                    pyList(choice.source.objects).c_str());
            Gui::Command::doCommand(Gui::Command::Doc, "%s.XSource = %s", group.c_str(),
                                    pyList(choice.source.xObjects).c_str());
            if (choice.scale > 0.0) {
                Gui::Command::doCommand(Gui::Command::Doc, "%s.ScaleType = 'Custom'", group.c_str());
                Gui::Command::doCommand(Gui::Command::Doc, "%s.Scale = %.12g", group.c_str(),
                                        choice.scale);
            }
            else {
                Gui::Command::doCommand(Gui::Command::Doc, "%s.ScaleType = 'Page'", group.c_str());
            }
            Gui::Command::doCommand(Gui::Command::Doc, "%s.addProjection('Front')", group.c_str());
            Gui::Command::doCommand(Gui::Command::Doc, "%s.Anchor.Direction = %s", group.c_str(),
                                    pyVector(orient.direction).c_str());
            Gui::Command::doCommand(Gui::Command::Doc, "%s.Anchor.XDirection = %s", group.c_str(),
                                    pyVector(orient.xDirection).c_str());
            Gui::Command::doCommand(Gui::Command::Doc, "%s.Anchor.RotationVector = %s", group.c_str(),
                                    pyVector(orient.xDirection).c_str());
            Gui::Command::doCommand(Gui::Command::Doc, "%s.X = %.6f", group.c_str(), at.x);
            Gui::Command::doCommand(Gui::Command::Doc, "%s.Y = %.6f", group.c_str(), at.y);
            Gui::Command::doCommand(Gui::Command::Doc, "%s.Anchor.recompute()", group.c_str());
            Gui::Command::doCommand(Gui::Command::Doc, "%s.recompute()", group.c_str());
            guiDocument(doc)->commitCommand();
        }
        catch (const Base::Exception& e) {
            guiDocument(doc)->abortCommand();
            Base::Console().error("Insert view: %s\n", e.what());
            return nullptr;
        }
        auto* made = dynamic_cast<TechDraw::DrawProjGroup*>(doc->getObject(name.c_str()));
        return made ? made->getAnchor() : nullptr;
    }

    InsertChoice choice;
    ViewPreview preview;
    std::optional<QSizeF> size;
};

/// Onshape's Insert view dialog (GD-B2): what to draw, the orientation, the scale
class InsertViewDialog: public QDialog
{
public:
    InsertViewDialog(std::vector<ViewSource> list, int current, double sheetScale, QWidget* parent)
        : QDialog(parent)
        , sources(std::move(list))
    {
        setObjectName(QStringLiteral("FreeCADCH_InsertView"));
        setWindowTitle(tr("Insert view"));
        auto* layout = new QVBoxLayout(this);
        layout->addWidget(new QLabel(tr("Insert"), this));
        sourceList = new QListWidget(this);
        sourceList->setObjectName(QStringLiteral("sources"));
        for (const auto& source : sources) {
            sourceList->addItem(source.text);
        }
        if (!sources.empty()) {
            sourceList->setCurrentRow(std::clamp(current, 0, int(sources.size()) - 1));
        }
        layout->addWidget(sourceList);
        if (sources.empty()) {
            layout->addWidget(new QLabel(tr("The document has no part to draw"), this));
        }
        layout->addWidget(new QLabel(tr("View orientation"), this));
        orientation = new QComboBox(this);
        orientation->setObjectName(QStringLiteral("orientation"));
        for (const auto& orient : viewOrientations()) {
            orientation->addItem(QCoreApplication::translate("TechDraw_InsertView", orient.name));
        }
        layout->addWidget(orientation);
        layout->addWidget(new QLabel(tr("View scale"), this));
        scale = new QComboBox(this);
        scale->setObjectName(QStringLiteral("scale"));
        scale->addItem(tr("%1 (Sheet)").arg(DrawGuiUtil::scaleText(sheetScale)), 0.0);
        for (double value : standardScales()) {
            scale->addItem(DrawGuiUtil::scaleText(value), value);
        }
        layout->addWidget(scale);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
        buttons->button(QDialogButtonBox::Ok)->setEnabled(!sources.empty());
        connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
        layout->addWidget(buttons);
    }

    InsertChoice choice() const
    {
        InsertChoice result;
        const int row = sourceList->currentRow();
        if (row >= 0 && row < int(sources.size())) {
            result.source = sources[row];
        }
        result.orientation = std::max(0, orientation->currentIndex());
        result.scale = scale->currentData().toDouble();
        return result;
    }

private:
    std::vector<ViewSource> sources;
    QListWidget* sourceList;
    QComboBox* orientation;
    QComboBox* scale;
};

/// Insert View with what is selected (none, or parts): the dialog, then the placing tool
void insertViewInteractively(TechDraw::DrawPage* page,
                             const std::vector<App::DocumentObject*>& shapes,
                             const std::vector<App::DocumentObject*>& xShapes)
{
    std::vector<ViewSource> sources = drawableSources(page->getDocument());
    int current = 0;
    if (!shapes.empty() || !xShapes.empty()) {
        auto same = std::ranges::find_if(sources, [&](const ViewSource& source) {
            return xShapes.empty() && source.objects == shapes;
        });
        if (same != sources.end()) {
            current = int(same - sources.begin());
        }
        else {
            // the selection as it is: what the view draws
            QStringList labels;
            for (auto* obj : shapes) {
                labels << labelOf(obj);
            }
            for (auto* obj : xShapes) {
                labels << labelOf(obj);
            }
            ViewSource selected {labels.join(QStringLiteral(", ")), shapes, xShapes};
            sources.insert(sources.begin(), selected);
        }
    }
    InsertViewDialog dialog(sources, current, page->Scale.getValue(), Gui::getMainWindow());
    if (dialog.exec() != QDialog::Accepted) {
        return;
    }
    activatePageHandler(new PlaceViewHandler(dialog.choice()));
}

}  // namespace

//===========================================================================
// TechDraw_View
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawView)

CmdTechDrawView::CmdTechDrawView() : Command("TechDraw_View")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    // FreeCAD-CH (design D, V1, ops#640): Onshape's Insert view
    sMenuText = QT_TR_NOOP("Insert View");
    sToolTipText = QT_TR_NOOP(
        "Inserts a view of a part, a Part Studio or an assembly of the document: choose it, the "
        "orientation and the scale, then click to place it. Its projections then follow the "
        "cursor, a click places each, until Esc.");
    sWhatsThis = "TechDraw_View";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_View";
}

void CmdTechDrawView::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    bool viewCreated = false;
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();

    // switch to the page if it's not current active window
    auto* vpp = freecad_cast<ViewProviderPage*>
        (Gui::Application::Instance->getViewProvider(page));
    if (vpp) {
        vpp->show();
    }

    // the selection: a spreadsheet or a BIM section makes its view at once; parts go to the dialog
    std::vector<App::DocumentObject*> shapes, xShapes;
    auto selection = getSelection().getSelectionEx(nullptr, App::DocumentObject::getClassTypeId());
    for (auto& sel : selection) {
        bool is_linked = false;
        auto obj = sel.getObject();
        if (obj->isDerivedFrom<TechDraw::DrawPage>() || obj->isDerivedFrom<TechDraw::DrawView>()) {
            continue;
        }

        if (obj->isDerivedFrom<Spreadsheet::Sheet>()) {
            std::string SpreadName = obj->getNameInDocument();

            openCommand(QT_TRANSLATE_NOOP("Command", "Create spreadsheet view"));
            std::string FeatName = getUniqueObjectName("Sheet");
            doCommand(Doc, "App.activeDocument().addObject('TechDraw::DrawViewSpreadsheet', '%s')",
                FeatName.c_str());
            doCommand(Doc, "App.activeDocument().%s.translateLabel('DrawViewSpreadsheet', 'Sheet', '%s')",
                FeatName.c_str(), FeatName.c_str());
            doCommand(Doc, "App.activeDocument().%s.Source = App.activeDocument().%s", FeatName.c_str(),
                SpreadName.c_str());
            doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", PageName.c_str(),
                FeatName.c_str());
            doCommand(Doc, "if App.activeDocument().%s.Scale: App.activeDocument().%s.Scale = App.activeDocument().%s.Scale",
                PageName.c_str(), FeatName.c_str(), PageName.c_str());
            updateActive();
            commitCommand();
            viewCreated = true;
            continue;
        }
        else if (DrawGuiUtil::isArchSection(obj)) {
            std::string FeatName = getUniqueObjectName("BIM view");
            std::string SourceName = obj->getNameInDocument();
            openCommand(QT_TRANSLATE_NOOP("Command", "Create BIM view"));
            doCommand(Doc, "App.activeDocument().addObject('TechDraw::DrawViewArch', '%s')",
                FeatName.c_str());
            doCommand(Doc, "App.activeDocument().%s.translateLabel('DrawViewArch', 'BIM view', '%s')",
                FeatName.c_str(), FeatName.c_str());
            doCommand(Doc, "App.activeDocument().%s.Source = App.activeDocument().%s", FeatName.c_str(),
                SourceName.c_str());
            doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", PageName.c_str(),
                FeatName.c_str());
            doCommand(Doc, "if App.activeDocument().%s.Scale: App.activeDocument().%s.Scale = App.activeDocument().%s.Scale",
                PageName.c_str(), FeatName.c_str(), PageName.c_str());
            updateActive();
            commitCommand();
            viewCreated = true;
            continue;
        }

        if (obj->isDerivedFrom<App::LinkElement>()
            || obj->isDerivedFrom<App::LinkGroup>()
            || obj->isDerivedFrom<App::Link>()) {
            is_linked = true;
        }
        // If parent of the obj is a link to another document, we possibly need to treat non-link obj as linked, too
        // 1st, is obj in another document?
        if (obj->getDocument() != this->getDocument()) {
            std::set<App::DocumentObject*> parents = obj->getInListEx(true);
            for (auto& parent : parents) {
                // Only consider parents in the current document, i.e. possible links in this View's document
                if (parent->getDocument() != this->getDocument()) {
                    continue;
                }
                // 2nd, do we really have a link to obj?
                if (parent->isDerivedFrom<App::LinkElement>()
                    || parent->isDerivedFrom<App::LinkGroup>()
                    || parent->isDerivedFrom<App::Link>()) {
                    // We have a link chain from this document to obj, and obj is in another document -> it is an XLink target
                    is_linked = true;
                }
            }
        }
        if (is_linked) {
            xShapes.push_back(obj);
            continue;
        }
        //not a Link and not null.  assume to be drawable.  Undrawables will be
        // skipped later.
        shapes.push_back(obj);
    }

    if (shapes.empty() && xShapes.empty() && viewCreated) {
        return;  // a spreadsheet or BIM view, made above
    }
    // FreeCAD-CH (design D, V1, ops#640): Onshape's Insert view. A dialog lists the document's
    // parts, studios and assemblies (the selection first, if it is none of them), never a file
    // browser; then one click places the view and its projections follow the cursor. No task
    // panel stays open and no lone second front view is made (H1's stumble 3). An image or SVG
    // goes on the sheet with TechDraw_Image and TechDraw_Symbol.
    insertViewInteractively(page, shapes, xShapes);
}

bool CmdTechDrawView::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// TechDraw_ProjectView (FreeCAD-CH, design D, V1, ops#640): Onshape's Projected view
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawProjectView)

CmdTechDrawProjectView::CmdTechDrawProjectView() : Command("TechDraw_ProjectView")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Projected View");
    sToolTipText = QT_TR_NOOP(
        "Click a view, move, click: a projection of it where the cursor went (a diagonal gives an "
        "isometric). From a projection group's front view it joins the group, aligned; from any "
        "other view it is a view of its own. Esc ends.");
    sWhatsThis = "TechDraw_ProjectView";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ProjectionGroup";
}

void CmdTechDrawProjectView::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    if (auto* vpp = freecad_cast<ViewProviderPage*>(Gui::Application::Instance->getViewProvider(page))) {
        vpp->show();
    }
    // a view selected is the parent; otherwise the first click picks it
    TechDraw::DrawViewPart* parent = nullptr;
    auto views = getSelection().getObjectsOfType(TechDraw::DrawViewPart::getClassTypeId());
    if (views.size() == 1) {
        parent = static_cast<TechDraw::DrawViewPart*>(views.front());
    }
    activatePageHandler(new ProjectViewHandler(parent));
}

bool CmdTechDrawProjectView::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// TechDraw_BrokenView
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawBrokenView)

CmdTechDrawBrokenView::CmdTechDrawBrokenView()
  : Command("TechDraw_BrokenView")
{
    sAppModule      = "TechDraw";
    sGroup          = QT_TR_NOOP("TechDraw");
    sMenuText       = QT_TR_NOOP("Broken View");
    sToolTipText    = QT_TR_NOOP("Inserts a new broken view for the selected objects or base view and break definition objects");
    sWhatsThis      = "TechDraw_BrokenView";
    sStatusTip      = sToolTipText;
    sPixmap         = "actions/TechDraw_BrokenView";
}

void CmdTechDrawBrokenView::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();

    // get shape objects from a base view
    std::vector<App::DocumentObject*> shapesFromBase;
    std::vector<App::DocumentObject*> xShapesFromBase;
    std::vector<App::DocumentObject*> baseViews =
        getSelection().getObjectsOfType(TechDraw::DrawViewPart::getClassTypeId());
    TechDraw::DrawViewPart* dvp{nullptr};
    if (!baseViews.empty()) {
        dvp = static_cast<TechDraw::DrawViewPart*>(*baseViews.begin());
        shapesFromBase = dvp->Source.getValues();
        xShapesFromBase = dvp->XSource.getValues();
    }

    auto doc = getDocument();
    if (dvp) {
        doc = dvp->getDocument();
    }

    // get the shape objects from the selection
    std::vector<App::DocumentObject*> shapes;
    std::vector<App::DocumentObject*> xShapes;
    App::DocumentObject* faceObj = nullptr;
    std::string faceName;
    getSelectedShapes(this, shapes, xShapes, faceObj, faceName);

    // we need either a base view (dvp) or some shape objects in the selection
    if (!dvp && (shapes.empty() && xShapes.empty())) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Empty Selection"),
            QObject::tr("Select objects to break or a base view and break definition objects"));
        return;
    }

    shapes.insert(shapes.end(), shapesFromBase.begin(), shapesFromBase.end());
    shapes.insert(xShapes.end(), xShapesFromBase.begin(), xShapesFromBase.end());


    // pick the Break objects out of the selected pile
    std::vector<Gui::SelectionObject> selection = getSelection().getSelectionEx(
        nullptr, App::DocumentObject::getClassTypeId(), Gui::ResolveMode::NoResolve);

    std::vector<App::DocumentObject*> breakObjects;
    for (auto& selObj : selection) {
        auto temp = selObj.getObject();
        // a sketch outside a body is returned as an independent object in the selection
        if (selObj.getSubNames().empty()) {
            if (DrawBrokenView::isBreakObject(*temp)) {
                breakObjects.push_back(selObj.getObject());
            }
            continue;
        }
        // a sketch inside a body is returned as body + subelement, so we have to search through
        // subnames to find it.  This may(?) apply to App::Part and Group also?
        auto subname = selObj.getSubNames().front();
        if (subname.back() == '.') {
            subname = subname.substr(0, subname.length() - 1);
            auto objects = doc->getObjects();
            for (auto& obj : objects) {
                std::string objname{obj->getNameInDocument()};
                if (subname == objname  &&
                    DrawBrokenView::isBreakObject(*obj)) {
                    breakObjects.push_back(obj);
                }
            }
        }
    }
    if (breakObjects.empty()) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
            QObject::tr("No break objects found in this selection"));
        return;
    }

    // remove Break objects from shape pile
    shapes = DrawBrokenView::removeBreakObjects(breakObjects, shapes);
    xShapes = DrawBrokenView::removeBreakObjects(breakObjects, xShapes);
    if (shapes.empty() &&
        xShapes.empty()) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
            QObject::tr("No shapes, groups, or links in this selection"));
        return;
    }

    Gui::WaitCursor wc;
    openCommand(QT_TRANSLATE_NOOP("Command", "Create broken view"));
    getDocument()->setStatus(App::Document::Status::SkipRecompute, true);
    std::string FeatName = getUniqueObjectName("BrokenView");
    doCommand(Doc, "App.activeDocument().addObject('TechDraw::DrawBrokenView','%s')", FeatName.c_str());
    doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", PageName.c_str(), FeatName.c_str());

    App::DocumentObject* docObj = getDocument()->getObject(FeatName.c_str());
    TechDraw::DrawBrokenView* dbv = dynamic_cast<TechDraw::DrawBrokenView*>(docObj);
    if (!dbv) {
        throw Base::TypeError("CmdTechDrawBrokenView DBV not found\n");
    }
    dbv->Source.setValues(shapes);
    dbv->XSource.setValues(xShapes);
    dbv->Breaks.setValues(breakObjects);

    //set projection direction from selected Face
    std::pair<Base::Vector3d, Base::Vector3d> dirs;
    if (faceName.size()) {
        dirs = DrawGuiUtil::getProjDirFromFace(faceObj, faceName);
    }
    else {
        dirs = DrawGuiUtil::get3DDirAndRot();
    }

    Base::Vector3d projDir = checkDirectionVsBasis(dirs.first);
    doCommand(Doc, "App.activeDocument().%s.Direction = FreeCAD.Vector(%.6f,%.6f,%.6f)",
              FeatName.c_str(), projDir.x, projDir.y, projDir.z);
    doCommand(Doc, "App.activeDocument().%s.XDirection = FreeCAD.Vector(%.6f,%.6f,%.6f)",
                  FeatName.c_str(), dirs.second.x, dirs.second.y, dirs.second.z);
    getDocument()->setStatus(App::Document::Status::SkipRecompute, true);

    commitCommand();

    dbv->recomputeFeature();
}

bool CmdTechDrawBrokenView::isActive(void)
{
    return DrawGuiUtil::needPage(this);
}


//===========================================================================
// TechDraw_ActiveView
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawActiveView)

CmdTechDrawActiveView::CmdTechDrawActiveView() : Command("TechDraw_ActiveView")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Active View");
    sToolTipText = "Inserts an image of the open 3D view in the current page.\n"
               "If multiple 3D views are open, a selection dialog will be shown.";
    sWhatsThis = "TechDraw_ActiveView";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ActiveView";
}

void CmdTechDrawActiveView::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this, true);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();
    Gui::Control().showDialog(new TaskDlgActiveView(page));
}

bool CmdTechDrawActiveView::isActive() { return DrawGuiUtil::needPage(this, true); }

//===========================================================================
// TechDraw_SectionGroup
//===========================================================================

DEF_STD_CMD_ACL(CmdTechDrawSectionGroup)

CmdTechDrawSectionGroup::CmdTechDrawSectionGroup() : Command("TechDraw_SectionGroup")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Section View (Simple or Complex)");
    sToolTipText = QT_TR_NOOP("Inserts a simple or complex section view in the current page");
    sWhatsThis = "TechDraw_SectionGroup";
    sStatusTip = sToolTipText;
}

void CmdTechDrawSectionGroup::activated(int iMsg)
{
    //    Base::Console().message("CMD::SectionGrp - activated(%d)\n", iMsg);
    Gui::TaskView::TaskDialog* dlg = Gui::Control().activeDialog();
    if (dlg) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Task in progress"),
                             QObject::tr("Close active task dialog and try again"));
        return;
    }

    Gui::ActionGroup* pcAction = qobject_cast<Gui::ActionGroup*>(_pcAction);
    pcAction->setIcon(pcAction->actions().at(iMsg)->icon());
    switch (iMsg) {
        case 0:
            execSimpleSection(this);
            break;
        case 1:
            execComplexSection(this);
            break;
        default:
            Base::Console().message("CMD::SectionGrp - invalid iMsg: %d\n", iMsg);
    };
}

Gui::Action* CmdTechDrawSectionGroup::createAction()
{
    Gui::ActionGroup* pcAction = new Gui::ActionGroup(this, Gui::getMainWindow());
    pcAction->setDropDownMenu(true);
    applyCommandData(this->className(), pcAction);

    QAction* p1 = pcAction->addAction(QString());
    p1->setIcon(Gui::BitmapFactory().iconFromTheme("actions/TechDraw_SectionView"));
    p1->setObjectName(QStringLiteral("TechDraw_SectionView"));
    p1->setWhatsThis(QStringLiteral("TechDraw_SectionView"));
    QAction* p2 = pcAction->addAction(QString());
    p2->setIcon(Gui::BitmapFactory().iconFromTheme("actions/TechDraw_ComplexSection"));
    p2->setObjectName(QStringLiteral("TechDraw_ComplexSection"));
    p2->setWhatsThis(QStringLiteral("TechDraw_ComplexSection"));

    _pcAction = pcAction;
    languageChange();

    pcAction->setIcon(p1->icon());
    int defaultId = 0;
    pcAction->setProperty("defaultAction", QVariant(defaultId));

    return pcAction;
}

void CmdTechDrawSectionGroup::languageChange()
{
    Command::languageChange();

    if (!_pcAction)
        return;
    Gui::ActionGroup* pcAction = qobject_cast<Gui::ActionGroup*>(_pcAction);
    QList<QAction*> a = pcAction->actions();

    QAction* arc1 = a[0];
    arc1->setText(QApplication::translate("CmdTechDrawSectionGroup", "Section View"));
    arc1->setToolTip(QApplication::translate("TechDraw_SectionView", "Inserts a simple section view"));
    arc1->setStatusTip(arc1->toolTip());
    QAction* arc2 = a[1];
    arc2->setText(QApplication::translate("CmdTechDrawSectionGroup", "Complex Section View"));
    arc2->setToolTip(
        QApplication::translate("TechDraw_ComplexSection", "Inserts a complex section view"));
    arc2->setStatusTip(arc2->toolTip());
}

bool CmdTechDrawSectionGroup::isActive()
{
    bool havePage = DrawGuiUtil::needPage(this);
    bool haveView = DrawGuiUtil::needView(this, false);
    return (havePage && haveView);
}

//===========================================================================
// TechDraw_SectionView
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawSectionView)

CmdTechDrawSectionView::CmdTechDrawSectionView() : Command("TechDraw_SectionView")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Section View");
    sToolTipText = QT_TR_NOOP("Inserts a new section view based on the selected view in the current page");
    sWhatsThis = "TechDraw_SectionView";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_SectionView";
}

void CmdTechDrawSectionView::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    Gui::TaskView::TaskDialog* dlg = Gui::Control().activeDialog();
    if (dlg) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Task in progress"),
                             QObject::tr("Close active task dialog and try again"));
        return;
    }

    execSimpleSection(this);
}

bool CmdTechDrawSectionView::isActive()
{
    bool havePage = DrawGuiUtil::needPage(this);
    bool haveView = DrawGuiUtil::needView(this);
    bool taskInProgress = false;
    if (havePage) {
        taskInProgress = Gui::Control().activeDialog();
    }
    return (havePage && haveView && !taskInProgress);
}

void execSimpleSection(Gui::Command* cmd)
{
    std::vector<App::DocumentObject*> baseObj =
        cmd->getSelection().getObjectsOfType(TechDraw::DrawViewPart::getClassTypeId());
    if (baseObj.empty()) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Select at least 1 DrawViewPart object as base"));
        return;
    }

    TechDraw::DrawPage* page = DrawGuiUtil::findPage(cmd);
    if (!page) {
        return;
    }

    TechDraw::DrawViewPart* dvp = static_cast<TechDraw::DrawViewPart*>(*baseObj.begin());
    Gui::Control().showDialog(new TaskDlgSectionView(dvp));

    cmd->updateActive();//ok here since dialog doesn't call doc.recompute()
    cmd->commitCommand();
}

//===========================================================================
// TechDraw_ComplexSection
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawComplexSection)

CmdTechDrawComplexSection::CmdTechDrawComplexSection() : Command("TechDraw_ComplexSection")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Complex Section View");
    sToolTipText = QT_TR_NOOP("Inserts a complex section view based on the selected view in the current page");
    sWhatsThis = "TechDraw_ComplexSection";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ComplexSection";
}

void CmdTechDrawComplexSection::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    Gui::TaskView::TaskDialog* dlg = Gui::Control().activeDialog();
    if (dlg) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Task in progress"),
                             QObject::tr("Close active task dialog and try again"));
        return;
    }

    execComplexSection(this);
}

bool CmdTechDrawComplexSection::isActive() { return DrawGuiUtil::needPage(this); }

//Complex Sections can be created without a baseView, so the gathering of input
//for the dialog is more involved that simple section
void execComplexSection(Gui::Command* cmd)
{
    TechDraw::DrawViewPart* baseView(nullptr);
    std::vector<App::DocumentObject*> shapes;
    std::vector<App::DocumentObject*> xShapes;
    App::DocumentObject* profileObject(nullptr);
    std::vector<std::string> profileSubs;
    Gui::ResolveMode resolve = Gui::ResolveMode::OldStyleElement;
    bool single = false;
    auto selection = cmd->getSelection().getSelectionEx(
        nullptr, App::DocumentObject::getClassTypeId(), resolve, single);
    for (auto& sel : selection) {
        bool is_linked = false;
        auto obj = sel.getObject();
        if (obj->isDerivedFrom<TechDraw::DrawPage>()) {
            continue;
        }
        if (obj->isDerivedFrom<TechDraw::DrawViewPart>()) {
            //use the dvp's Sources as sources for this ComplexSection &
            //check the subelement(s) to see if they can be used as a profile
            baseView = static_cast<TechDraw::DrawViewPart*>(obj);
            if (!sel.getSubNames().empty()) {
                //need to add profile subs as parameter
                profileObject = baseView;
                profileSubs = sel.getSubNames();
            }
            continue;
        }
        if (obj->isDerivedFrom<App::LinkElement>()
            || obj->isDerivedFrom<App::LinkGroup>()
            || obj->isDerivedFrom<App::Link>()) {
            is_linked = true;
        }
        // If parent of the obj is a link to another document, we possibly need to treat non-link obj as linked, too
        // 1st, is obj in another document?
        if (obj->getDocument() != cmd->getDocument()) {
            std::set<App::DocumentObject*> parents = obj->getInListEx(true);
            for (auto& parent : parents) {
                // Only consider parents in the current document, i.e. possible links in this View's document
                if (parent->getDocument() != cmd->getDocument()) {
                    continue;
                }
                // 2nd, do we really have a link to obj?
                if (parent->isDerivedFrom<App::LinkElement>()
                    || parent->isDerivedFrom<App::LinkGroup>()
                    || parent->isDerivedFrom<App::Link>()) {
                    // We have a link chain from this document to obj, and obj is in another document -> it is an XLink target
                    is_linked = true;
                }
            }
        }
        if (is_linked) {
            xShapes.push_back(obj);
            continue;
        }
        //not a Link and not null.  assume to be drawable.  Undrawables will be
        // skipped later.
        if (TechDraw::DrawComplexSection::isProfileObject(obj)) {
            profileObject = obj;
        }
        else {
            shapes.push_back(obj);
        }
    }

    if (!baseView) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("No base view selected"));
        return;
    }

    if (shapes.empty() && xShapes.empty() && !baseView) {
        QMessageBox::warning(
            Gui::getMainWindow(), QObject::tr("Wrong selection"),
            QObject::tr("No base view, shapes, groups, or links in this selection"));
        return;
    }
    if (!profileObject) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("No profile object found in selection"));
        return;
    }

    TechDraw::DrawPage* page = DrawGuiUtil::findPage(cmd);
    if (!page) {
        return;
    }

    Gui::Control().showDialog(
        new TaskDlgComplexSection(page, baseView, shapes, xShapes, profileObject, profileSubs));
}

//===========================================================================
// TechDraw_DetailView
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawDetailView)

CmdTechDrawDetailView::CmdTechDrawDetailView() : Command("TechDraw_DetailView")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Detail View");
    sToolTipText = QT_TR_NOOP("Inserts a new detail view based on the selected view in the current page");
    sWhatsThis = "TechDraw_DetailView";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_DetailView";
}

void CmdTechDrawDetailView::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    std::vector<App::DocumentObject*> baseObj =
        getSelection().getObjectsOfType(TechDraw::DrawViewPart::getClassTypeId());
    if (baseObj.empty()) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Select at least 1 DrawViewPart object as base"));
        return;
    }
    TechDraw::DrawViewPart* dvp = static_cast<TechDraw::DrawViewPart*>(*(baseObj.begin()));

    Gui::Control().showDialog(new TaskDlgDetail(dvp));
}

bool CmdTechDrawDetailView::isActive()
{
    bool havePage = DrawGuiUtil::needPage(this);
    bool haveView = DrawGuiUtil::needView(this);
    bool taskInProgress = false;
    if (havePage) {
        taskInProgress = Gui::Control().activeDialog();
    }
    return (havePage && haveView && !taskInProgress);
}

//===========================================================================
// TechDraw_ProjectionGroup
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawProjectionGroup)

CmdTechDrawProjectionGroup::CmdTechDrawProjectionGroup() : Command("TechDraw_ProjectionGroup")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Projection Group");
    sToolTipText = QT_TR_NOOP("Inserts multiple new linked views of the selected objects in the current page");
    sWhatsThis = "TechDraw_ProjectionGroup";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ProjectionGroup";
}

void CmdTechDrawProjectionGroup::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    //set projection direction from selected Face
    //use first object with a face selected
    std::vector<App::DocumentObject*> shapes;
    std::vector<App::DocumentObject*> xShapes;
    App::DocumentObject* partObj = nullptr;
    std::string faceName;
    Gui::ResolveMode resolve = Gui::ResolveMode::OldStyleElement;
    bool single = false;
    auto selection = getSelection().getSelectionEx(nullptr, App::DocumentObject::getClassTypeId(),
                                                   resolve, single);
    for (auto& sel : selection) {
        bool is_linked = false;
        auto obj = sel.getObject();
        if (obj->isDerivedFrom<TechDraw::DrawPage>()) {
            continue;
        }
        if (obj->isDerivedFrom<App::LinkElement>()
            || obj->isDerivedFrom<App::LinkGroup>()
            || obj->isDerivedFrom<App::Link>()) {
            is_linked = true;
        }
        // If parent of the obj is a link to another document, we possibly need to treat non-link obj as linked, too
        // 1st, is obj in another document?
        if (obj->getDocument() != this->getDocument()) {
            std::set<App::DocumentObject*> parents = obj->getInListEx(true);
            for (auto& parent : parents) {
                // Only consider parents in the current document, i.e. possible links in this View's document
                if (parent->getDocument() != this->getDocument()) {
                    continue;
                }
                // 2nd, do we really have a link to obj?
                if (parent->isDerivedFrom<App::LinkElement>()
                    || parent->isDerivedFrom<App::LinkGroup>()
                    || parent->isDerivedFrom<App::Link>()) {
                    // We have a link chain from this document to obj, and obj is in another document -> it is an XLink target
                    is_linked = true;
                }
            }
        }
        if (is_linked) {
            xShapes.push_back(obj);
            continue;
        }
        //not a Link and not null.  assume to be drawable.  Undrawables will be
        // skipped later.
        shapes.push_back(obj);
        if (partObj) {
            continue;
        }
        for (auto& sub : sel.getSubNames()) {
            if (TechDraw::DrawUtil::getGeomTypeFromName(sub) == "Face") {
                faceName = sub;
                partObj = obj;
                break;
            }
        }
    }
    if (shapes.empty() && xShapes.empty()) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("No shapes, groups, or links in this selection"));
        return;
    }

    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();

    Base::Vector3d projDir;
    Gui::WaitCursor wc;

    openCommand(QT_TRANSLATE_NOOP("Command", "Create projection group"));

    std::string multiViewName = getUniqueObjectName("ProjGroup");
    doCommand(Doc, "App.activeDocument().addObject('TechDraw::DrawProjGroup', '%s')",
              multiViewName.c_str());
    doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", PageName.c_str(),
              multiViewName.c_str());

    App::DocumentObject* docObj = getDocument()->getObject(multiViewName.c_str());
    auto multiView(static_cast<TechDraw::DrawProjGroup*>(docObj));
    multiView->Source.setValues(shapes);
    multiView->XSource.setValues(xShapes);
    doCommand(Doc, "App.activeDocument().%s.addProjection('Front')", multiViewName.c_str());

    std::pair<Base::Vector3d, Base::Vector3d> dirs = !faceName.empty() ?
        DrawGuiUtil::getProjDirFromFace(partObj, faceName)
        : DrawGuiUtil::get3DDirAndRot();

    Base::Vector3d checkedDir = checkDirectionVsBasis(dirs.first);
    getDocument()->setStatus(App::Document::Status::SkipRecompute, true);
    doCommand(Doc,
        "App.activeDocument().%s.Anchor.Direction = FreeCAD.Vector(%.12f, %.12f, %.12f)",
        multiViewName.c_str(), checkedDir.x, checkedDir.y, checkedDir.z);
    doCommand(Doc,
        "App.activeDocument().%s.Anchor.RotationVector = FreeCAD.Vector(%.12f, %.12f, %.12f)",
        multiViewName.c_str(), dirs.second.x, dirs.second.y, dirs.second.z);
    doCommand(Doc,
        "App.activeDocument().%s.Anchor.XDirection = FreeCAD.Vector(%.12f, %.12f, %.12f)",
        multiViewName.c_str(), dirs.second.x, dirs.second.y, dirs.second.z);
    getDocument()->setStatus(App::Document::Status::SkipRecompute, false);

    doCommand(Doc, "App.activeDocument().%s.Anchor.recompute()", multiViewName.c_str());
    commitCommand();
    updateActive();

    // create the rest of the desired views
    Gui::Control().showDialog(new TaskDlgProjGroup(multiView, true));
}

bool CmdTechDrawProjectionGroup::isActive()
{
    bool havePage = DrawGuiUtil::needPage(this);
    bool taskInProgress = false;
    if (havePage) {
        taskInProgress = Gui::Control().activeDialog();
    }
    return (havePage && !taskInProgress);
}

//! common checks of Selection for Dimension commands
//non-empty selection, no more than maxObjs selected and at least 1 DrawingPage exists
bool _checkSelectionBalloon(Gui::Command* cmd, unsigned maxObjs)
{
    std::vector<Gui::SelectionObject> selection = cmd->getSelection().getSelectionEx();
    if (selection.empty()) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Incorrect Selection"),
                             QObject::tr("Select an object first"));
        return false;
    }

    const std::vector<std::string> SubNames = selection[0].getSubNames();
    if (SubNames.size() > maxObjs) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Incorrect Selection"),
                             QObject::tr("Too many objects selected"));
        return false;
    }

    std::vector<App::DocumentObject*> pages =
        cmd->getDocument()->getObjectsOfType(TechDraw::DrawPage::getClassTypeId());
    if (pages.empty()) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Incorrect Selection"),
                             QObject::tr("Create a page first"));
        return false;
    }
    return true;
}

bool _checkDrawViewPartBalloon(Gui::Command* cmd)
{
    std::vector<Gui::SelectionObject> selection = cmd->getSelection().getSelectionEx();
    auto objFeat(dynamic_cast<TechDraw::DrawViewPart*>(selection[0].getObject()));
    if (!objFeat) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Incorrect Selection"),
                             QObject::tr("No view of a part in selection"));
        return false;
    }
    return true;
}

bool _checkDirectPlacement(const QGIView* view, const std::vector<std::string>& subNames,
                           QPointF& placement)
{
    // Let's see, if we can help speed up the placement of the balloon:
    // As of now we support:
    //     Single selected vertex: place the balloon tip end here
    //     Single selected edge:   place the balloon tip at its midpoint (suggested placement for e.g. chamfer dimensions)
    //
    // Single selected faces are currently not supported, but maybe we could in this case use the center of mass?

    if (subNames.size() != 1) {
        // If nothing or more than one subjects are selected, let the user decide, where to place the balloon
        return false;
    }

    const QGIViewPart* viewPart = dynamic_cast<const QGIViewPart*>(view);
    if (!viewPart) {
        //not a view of a part, so no geometry to attach to
        return false;
    }

    std::string geoType = TechDraw::DrawUtil::getGeomTypeFromName(subNames[0]);
    if (geoType == "Vertex") {
        int index = TechDraw::DrawUtil::getIndexFromName(subNames[0]);
        TechDraw::VertexPtr vertex =
            static_cast<DrawViewPart*>(viewPart->getViewObject())->getProjVertexByIndex(index);
        if (vertex) {
            placement = viewPart->mapToScene(Rez::guiX(vertex->x()), Rez::guiX(vertex->y()));
            return true;
        }
    }
    else if (geoType == "Edge") {
        int index = TechDraw::DrawUtil::getIndexFromName(subNames[0]);
        TechDraw::BaseGeomPtr geo =
            static_cast<DrawViewPart*>(viewPart->getViewObject())->getGeomByIndex(index);
        if (geo) {
            Base::Vector3d midPoint(Rez::guiX(geo->getMidPoint()));
            placement = viewPart->mapToScene(midPoint.x, midPoint.y);
            return true;
        }
    }

    return false;
}

DEF_STD_CMD_A(CmdTechDrawBalloon)

CmdTechDrawBalloon::CmdTechDrawBalloon() : Command("TechDraw_Balloon")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Balloon Annotation");
    sToolTipText = QT_TR_NOOP("Inserts a new balloon annotation in the selected view");
    sWhatsThis = "TechDraw_Balloon";
    sStatusTip = sToolTipText;
    sPixmap = "TechDraw_Balloon";
}

void CmdTechDrawBalloon::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    bool result = _checkSelectionBalloon(this, 1);
    if (!result) {
        return;
    }

    std::vector<Gui::SelectionObject> selection = getSelection().getSelectionEx();

    auto objFeat(dynamic_cast<TechDraw::DrawView*>(selection[0].getObject()));
    if (!objFeat) {
        return;
    }

    TechDraw::DrawPage* page = objFeat->findParentPage();
    std::string PageName = page->getNameInDocument();

    Gui::Document* guiDoc = Gui::Application::Instance->getDocument(page->getDocument());
    ViewProviderPage* pageVP = freecad_cast<ViewProviderPage*>(guiDoc->getViewProvider(page));
    ViewProviderDrawingView* viewVP =
        freecad_cast<ViewProviderDrawingView*>(guiDoc->getViewProvider(objFeat));

    if (pageVP && viewVP) {
        QGVPage* viewPage = pageVP->getQGVPage();
        QGSPage* scenePage = pageVP->getQGSPage();
        if (viewPage) {
            auto* view = dynamic_cast<QGIView*>(viewVP->getQView());
            QPointF placement;
            if (view && _checkDirectPlacement(view, selection[0].getSubNames(), placement)) {
                //this creates the balloon if something is already selected
                scenePage->createBalloon(placement, objFeat);
                return;
            }
            viewPage->startBalloonPlacing(objFeat);
        }
    }
}

bool CmdTechDrawBalloon::isActive()
{
    bool havePage = DrawGuiUtil::needPage(this);
    bool haveView = DrawGuiUtil::needView(this, false);
    bool taskInProgress = Gui::Control().activeDialog();
    return (havePage && haveView && !taskInProgress);
}

//===========================================================================
// TechDraw_ClipGroup
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawClipGroup)

CmdTechDrawClipGroup::CmdTechDrawClipGroup() : Command("TechDraw_ClipGroup")
{
    // setting the
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Clip Group");
    sToolTipText = QT_TR_NOOP("Inserts a new clip group for the selected view");
    sWhatsThis = "TechDraw_ClipGroup";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ClipGroup";
}

void CmdTechDrawClipGroup::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();

    std::string FeatName = getUniqueObjectName("Clip");
    openCommand(QT_TRANSLATE_NOOP("Command", "Create clip"));
    doCommand(Doc, "App.activeDocument().addObject('TechDraw::DrawViewClip', '%s')",
              FeatName.c_str());
    doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", PageName.c_str(),
              FeatName.c_str());
    updateActive();
    commitCommand();
}

bool CmdTechDrawClipGroup::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// TechDraw_ClipGroupAdd
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawClipGroupAdd)

CmdTechDrawClipGroupAdd::CmdTechDrawClipGroupAdd() : Command("TechDraw_ClipGroupAdd")
{
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Add View To Clip Group");
    sToolTipText = QT_TR_NOOP("Adds the selected view to a clip group");
    sWhatsThis = "TechDraw_ClipGroupAdd";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ClipGroupAdd";
}

void CmdTechDrawClipGroupAdd::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    std::vector<Gui::SelectionObject> selection = getSelection().getSelectionEx();
    if (selection.size() != 2) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Select one clip group and one view"));
        return;
    }

    TechDraw::DrawViewClip* clip = nullptr;
    TechDraw::DrawView* view = nullptr;
    std::vector<Gui::SelectionObject>::iterator itSel = selection.begin();
    for (; itSel != selection.end(); itSel++) {
        if ((*itSel).getObject()->isDerivedFrom<TechDraw::DrawViewClip>()) {
            clip = static_cast<TechDraw::DrawViewClip*>((*itSel).getObject());
        }
        else if ((*itSel).getObject()->isDerivedFrom<TechDraw::DrawView>()) {
            view = static_cast<TechDraw::DrawView*>((*itSel).getObject());
        }
    }
    if (!view) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Select exactly one view to add to clip group"));
        return;
    }
    if (!clip) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Select exactly one clip group"));
        return;
    }

    TechDraw::DrawPage* pageClip = clip->findParentPage();
    TechDraw::DrawPage* pageView = view->findParentPage();

    if (pageClip != pageView) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Clip and view must be from same page"));
        return;
    }

    std::string PageName = pageClip->getNameInDocument();
    std::string ClipName = clip->getNameInDocument();
    std::string ViewName = view->getNameInDocument();

    openCommand(QT_TRANSLATE_NOOP("Command", "Add clip group"));
    doCommand(Doc, "App.activeDocument().%s.ViewObject.Visibility = False", ViewName.c_str());
    doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", ClipName.c_str(),
              ViewName.c_str());
    doCommand(Doc, "App.activeDocument().%s.ViewObject.Visibility = True", ViewName.c_str());
    updateActive();
    commitCommand();
}

bool CmdTechDrawClipGroupAdd::isActive()
{
    bool havePage = DrawGuiUtil::needPage(this);
    bool haveClip = false;
    if (havePage) {
        auto drawClipType(TechDraw::DrawViewClip::getClassTypeId());
        auto selClips = getDocument()->getObjectsOfType(drawClipType);
        if (!selClips.empty()) {
            haveClip = true;
        }
    }
    return (havePage && haveClip);
}

//===========================================================================
// TechDraw_ClipGroupRemove
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawClipGroupRemove)

CmdTechDrawClipGroupRemove::CmdTechDrawClipGroupRemove() : Command("TechDraw_ClipGroupRemove")
{
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Remove From Clip Group");
    sToolTipText = QT_TR_NOOP("Removes a view based on the selected clip group");
    sWhatsThis = "TechDraw_ClipGroupRemove";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ClipGroupRemove";
}

void CmdTechDrawClipGroupRemove::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    auto dObj(getSelection().getObjectsOfType(TechDraw::DrawView::getClassTypeId()));
    if (dObj.empty()) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Select exactly one view to remove from clip group"));
        return;
    }

    auto view(static_cast<TechDraw::DrawView*>(dObj.front()));

    TechDraw::DrawPage* page = view->findParentPage();
    const std::vector<App::DocumentObject*> pViews = page->getViews();
    TechDraw::DrawViewClip* clip(nullptr);
    for (auto& v : pViews) {
        clip = dynamic_cast<TechDraw::DrawViewClip*>(v);
        if (clip && clip->isViewInClip(view)) {
            break;
        }
        clip = nullptr;
    }

    if (!clip) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("View does not belong to a clip"));
        return;
    }

    std::string ClipName = clip->getNameInDocument();
    std::string ViewName = view->getNameInDocument();

    openCommand(QT_TRANSLATE_NOOP("Command", "Remove clip group"));
    doCommand(Doc, "App.activeDocument().%s.ViewObject.Visibility = False", ViewName.c_str());
    doCommand(Doc, "App.activeDocument().%s.removeView(App.activeDocument().%s)", ClipName.c_str(),
              ViewName.c_str());
    doCommand(Doc, "App.activeDocument().%s.ViewObject.Visibility = True", ViewName.c_str());
    updateActive();
    commitCommand();
}

bool CmdTechDrawClipGroupRemove::isActive()
{
    bool havePage = DrawGuiUtil::needPage(this);
    bool haveClip = false;
    if (havePage) {
        auto drawClipType(TechDraw::DrawViewClip::getClassTypeId());
        auto selClips = getDocument()->getObjectsOfType(drawClipType);
        if (!selClips.empty()) {
            haveClip = true;
        }
    }
    return (havePage && haveClip);
}


//===========================================================================
// TechDraw_Symbol
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawSymbol)

CmdTechDrawSymbol::CmdTechDrawSymbol() : Command("TechDraw_Symbol")
{
    // setting the Gui eye-candy
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Insert SVG");
    sToolTipText = QT_TR_NOOP("Inserts a symbol from an SVG file");
    sWhatsThis = "TechDraw_Symbol";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_Symbol";
}

void CmdTechDrawSymbol::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();

    // Reading an image
    const Gui::FileDialog::FilterList filterList {
        {QStringLiteral("SVG"), {"*.svg", "*.svgz"}},
        Gui::FileDialog::Filter::AllFiles(),
    };
    QString filename = Gui::FileDialog::getOpenFileName(
        Gui::getMainWindow(), QObject::tr("Choose an SVG file to open"),
        Preferences::defaultSymbolDir(),
        filterList);

    if (!filename.isEmpty()) {
        std::string FeatName = getUniqueObjectName("Symbol");
        auto filespec = DU::cleanFilespecBackslash(
            Base::Tools::escapeEncodeFilename(filename.toStdString()));
        openCommand(QT_TRANSLATE_NOOP("Command", "Create Symbol"));
        doCommand(Doc, "f = open(\"%s\", 'r', encoding=\"utf-8\")", filespec.c_str());
        doCommand(Doc, "svg = f.read()");
        doCommand(Doc, "f.close()");
        doCommand(Doc, "App.activeDocument().addObject('TechDraw::DrawViewSymbol', '%s')",
                  FeatName.c_str());
        doCommand(Doc, "App.activeDocument().%s.translateLabel('DrawViewSymbol', 'Symbol', '%s')",
              FeatName.c_str(), FeatName.c_str());
        doCommand(Doc, "App.activeDocument().%s.Symbol = svg", FeatName.c_str());

        auto baseView = CommandHelpers::firstViewInSelection(this);
        if (baseView) {
            auto baseName = baseView->getNameInDocument();
            doCommand(Doc, "App.activeDocument().%s.Owner = App.activeDocument().%s",
                      FeatName.c_str(), baseName);
        }

        doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", PageName.c_str(),
                  FeatName.c_str());

        updateActive();
        commitCommand();
    }
}

bool CmdTechDrawSymbol::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// TechDraw_DraftView
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawDraftView)

CmdTechDrawDraftView::CmdTechDrawDraftView() : Command("TechDraw_DraftView")
{
    // setting the Gui eye-candy
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Draft View");
    //: "Draft" is a workbench and should not be translated
    sToolTipText = QT_TR_NOOP("Inserts a view of a Draft object");
    sWhatsThis = "TechDraw_NewDraft";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_DraftView";
}

void CmdTechDrawDraftView::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    std::vector<App::DocumentObject*> objects =
        getSelection().getObjectsOfType(App::DocumentObject::getClassTypeId());

    if (objects.empty()) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Select at least one object"));
        return;
    }

    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();

    std::pair<Base::Vector3d, Base::Vector3d> dirs = DrawGuiUtil::get3DDirAndRot();
    Base::Vector3d checkedDir = checkDirectionVsBasis(dirs.first);
    for (auto* obj : objects) {
         if (obj->isDerivedFrom<TechDraw::DrawPage>() ||
             obj->isDerivedFrom<TechDraw::DrawView>()) {
            // skip over TechDraw objects as they are not valid subjects for a DraftView
            continue;
        }
        std::string FeatName = getUniqueObjectName("DraftView");
        std::string SourceName = obj->getNameInDocument();
        openCommand(QT_TRANSLATE_NOOP("Command", "Create DraftView"));
        doCommand(Doc, "App.activeDocument().addObject('TechDraw::DrawViewDraft', '%s')",
                  FeatName.c_str());
        doCommand(Doc, "App.activeDocument().%s.translateLabel('DrawViewDraft', 'DraftView', '%s')",
              FeatName.c_str(), FeatName.c_str());
        doCommand(Doc, "App.activeDocument().%s.Source = App.activeDocument().%s", FeatName.c_str(),
                  SourceName.c_str());
        doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", PageName.c_str(),
                  FeatName.c_str());
        doCommand(Doc, "if App.activeDocument().%s.Scale: App.activeDocument().%s.Scale = App.activeDocument().%s.Scale",
                  PageName.c_str(), FeatName.c_str(), PageName.c_str());
        doCommand(Doc, "App.activeDocument().%s.Direction = FreeCAD.Vector(%.12f, %.12f, %.12f)",
                  FeatName.c_str(), checkedDir.x, checkedDir.y, checkedDir.z);
        updateActive();
        commitCommand();
    }
}

bool CmdTechDrawDraftView::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// TechDraw_ArchView
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawArchView)

CmdTechDrawArchView::CmdTechDrawArchView() : Command("TechDraw_ArchView")
{
    // setting the Gui eye-candy
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("BIM View");
    sToolTipText = QT_TR_NOOP("Inserts a view of a BIM section plane");
    sWhatsThis = "TechDraw_NewArch";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ArchView";
}

void CmdTechDrawArchView::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    const std::vector<App::DocumentObject*> objects =
        getSelection().getObjectsOfType(App::DocumentObject::getClassTypeId());
    App::DocumentObject* archObject = nullptr;
    int archCount = 0;
    for (auto& obj : objects) {
        if (obj->isDerivedFrom<TechDraw::DrawPage>() ||
            obj->isDerivedFrom<TechDraw::DrawView>()) {
            // skip over TechDraw objects as they are not valid subjects for a ArchView
            continue;
        }
        if (DrawGuiUtil::isArchSection(obj)) {
            archCount++;
            archObject = obj;
        }
    }
    if (archCount > 1) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Select only 1 BIM section plane"));
        return;
    }

    if (!archObject) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("No BIM section plane in selection"));
        return;
    }

    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();

    std::string FeatName = getUniqueObjectName("BIM view");
    std::string SourceName = archObject->getNameInDocument();
    openCommand(QT_TRANSLATE_NOOP("Command", "Create BIM view"));
    doCommand(Doc, "App.activeDocument().addObject('TechDraw::DrawViewArch', '%s')",
              FeatName.c_str());
    doCommand(Doc, "App.activeDocument().%s.translateLabel('DrawViewArch', 'BIM view', '%s')",
              FeatName.c_str(), FeatName.c_str());
    doCommand(Doc, "App.activeDocument().%s.Source = App.activeDocument().%s", FeatName.c_str(),
              SourceName.c_str());
    doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", PageName.c_str(),
              FeatName.c_str());
    doCommand(Doc, "if App.activeDocument().%s.Scale: App.activeDocument().%s.Scale = App.activeDocument().%s.Scale",
        PageName.c_str(), FeatName.c_str(), PageName.c_str());
    updateActive();
    commitCommand();
}

bool CmdTechDrawArchView::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// TechDraw_SpreadsheetView
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawSpreadsheetView)

CmdTechDrawSpreadsheetView::CmdTechDrawSpreadsheetView() : Command("TechDraw_SpreadsheetView")
{
    // setting the
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Spreadsheet View");
    sToolTipText = QT_TR_NOOP("Inserts a view of a spreadsheet in the current page");
    sWhatsThis = "TechDraw_SpreadsheetView";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_SpreadsheetView";
}

void CmdTechDrawSpreadsheetView::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();

    const std::vector<App::DocumentObject*> spreads =
        getSelection().getObjectsOfType(Spreadsheet::Sheet::getClassTypeId());
    if (spreads.size() != 1) {
        QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Wrong selection"),
                             QObject::tr("Select exactly one spreadsheet object"));
        return;
    }
    std::string SpreadName = spreads.front()->getNameInDocument();

    openCommand(QT_TRANSLATE_NOOP("Command", "Create spreadsheet view"));
    std::string FeatName = getUniqueObjectName("Sheet");
    doCommand(Doc, "App.activeDocument().addObject('TechDraw::DrawViewSpreadsheet', '%s')",
              FeatName.c_str());
    doCommand(Doc, "App.activeDocument().%s.translateLabel('DrawViewSpreadsheet', 'Sheet', '%s')",
              FeatName.c_str(), FeatName.c_str());
    doCommand(Doc, "App.activeDocument().%s.Source = App.activeDocument().%s", FeatName.c_str(),
              SpreadName.c_str());

    // look for an owner view in the selection
    auto baseView = CommandHelpers::firstViewInSelection(this);
    if (baseView) {
        auto baseName = baseView->getNameInDocument();
        doCommand(Doc, "App.activeDocument().%s.Owner = App.activeDocument().%s",
                  FeatName.c_str(), baseName);
    }

    doCommand(Doc, "App.activeDocument().%s.addView(App.activeDocument().%s)", PageName.c_str(),
              FeatName.c_str());
    doCommand(Doc, "if App.activeDocument().%s.Scale: App.activeDocument().%s.Scale = App.activeDocument().%s.Scale",
        PageName.c_str(), FeatName.c_str(), PageName.c_str());
    updateActive();
    commitCommand();
}

bool CmdTechDrawSpreadsheetView::isActive()
{
    //need a Page and a SpreadSheet::Sheet
    bool havePage = DrawGuiUtil::needPage(this);
    bool haveSheet = false;
    if (havePage) {
        auto spreadSheetType(Spreadsheet::Sheet::getClassTypeId());
        auto selSheets = getDocument()->getObjectsOfType(spreadSheetType);
        if (!selSheets.empty()) {
            haveSheet = true;
        }
    }
    return (havePage && haveSheet);
}


//===========================================================================
// TechDraw_ExportPageSVG
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawExportPageSVG)

CmdTechDrawExportPageSVG::CmdTechDrawExportPageSVG() : Command("TechDraw_ExportPageSVG")
{
    sGroup = QT_TR_NOOP("File");
    sMenuText = QT_TR_NOOP("Export Page as SVG");
    sToolTipText = QT_TR_NOOP("Exports the current page as an SVG");
    sWhatsThis = "TechDraw_ExportPageSVG";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ExportPageSVG";
}

void CmdTechDrawExportPageSVG::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }
    std::string PageName = page->getNameInDocument();

    Gui::Document* activeGui = Gui::Application::Instance->getDocument(page->getDocument());
    Gui::ViewProvider* vp = activeGui->getViewProvider(page);
    ViewProviderPage* vpPage = freecad_cast<ViewProviderPage*>(vp);

    if (vpPage) {
        vpPage->show();  // make sure a mdi will be available
        vpPage->getMDIViewPage()->saveSVG();
    }
    else {
        QMessageBox::warning(Gui::getMainWindow(),
                             QObject::tr("No drawing page"),
                             QObject::tr("FreeCAD could not find a page to export"));
        return;
    }
}

bool CmdTechDrawExportPageSVG::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// TechDraw_ExportPageDXF
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawExportPageDXF)

CmdTechDrawExportPageDXF::CmdTechDrawExportPageDXF() : Command("TechDraw_ExportPageDXF")
{
    sGroup = QT_TR_NOOP("File");
    sMenuText = QT_TR_NOOP("Export Page as DXF");
    sToolTipText = QT_TR_NOOP("Exports the current page as a DXF");
    sWhatsThis = "TechDraw_ExportPageDXF";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ExportPageDXF";
}

void CmdTechDrawExportPageDXF::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    TechDraw::DrawPage* page = DrawGuiUtil::findPage(this);
    if (!page) {
        return;
    }

    std::vector<App::DocumentObject*> views = page->getViews();
    for (auto& v : views) {
        if (v->isDerivedFrom<TechDraw::DrawViewArch>()) {
            QMessageBox::StandardButton rc = QMessageBox::question(
                Gui::getMainWindow(), QObject::tr("Cannot export selection"),
                QObject::tr("Page contains a BIM view which will not be exported. Continue?"),
                QMessageBox::StandardButtons(QMessageBox::Yes | QMessageBox::No));
            if (rc == QMessageBox::No) {
                return;
            }
            else {
                break;
            }
        }
    }

    //WF? allow more than one TD Page per Dxf file??  1 TD page = 1 DXF file = 1 drawing?
    QString defaultDir;
    QString fileName = Gui::FileDialog::getSaveFileName(
        Gui::getMainWindow(), QObject::tr("Save DXF file"), defaultDir,
        Gui::FileDialog::FilterList{{QStringLiteral("DXF"), {"*.dxf"}}});

    if (fileName.isEmpty()) {
        return;
    }

    std::string PageName = page->getNameInDocument();
    openCommand(QT_TRANSLATE_NOOP("Command", "Save page to DXF"));
    doCommand(Doc, "import TechDraw");
    auto filespec = DU::cleanFilespecBackslash(
        Base::Tools::escapeEncodeFilename(fileName.toStdString()));
    doCommand(Doc, "TechDraw.writeDXFPage(App.activeDocument().%s, u\"%s\")", PageName.c_str(),
              filespec.c_str());
    commitCommand();
}

bool CmdTechDrawExportPageDXF::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// TechDraw_ExportPagePDF
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawExportPagePDF)

CmdTechDrawExportPagePDF::CmdTechDrawExportPagePDF() : Command("TechDraw_ExportPagePDF")
{
    sGroup = QT_TR_NOOP("File");
    sMenuText = QT_TR_NOOP("Export Page as PDF");
    sToolTipText = QT_TR_NOOP("Exports the current page as a PDF");
    sWhatsThis = "TechDraw_ExportPagePDF";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ExportPagePDF";
}

void CmdTechDrawExportPagePDF::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    auto* mvp = qobject_cast<MDIViewPage*>(Gui::getMainWindow()->activeWindow());
    if (mvp) {
        mvp->exportAsPdf();
    }
}

bool CmdTechDrawExportPagePDF::isActive() { return DrawGuiUtil::needPage(this); }

//===========================================================================
// TechDraw_ExportGroup
//===========================================================================
class CmdTechDrawExportGroup : public Gui::GroupCommand
{
public:
    CmdTechDrawExportGroup()
        : GroupCommand("TechDraw_ExportGroup")
    {
        sAppModule = "TechDraw";
        sGroup = QT_TR_NOOP("TechDraw");
        sMenuText = QT_TR_NOOP("Print All Pages");
        sToolTipText = sMenuText;
        sWhatsThis = "TechDraw_ExportGroup";
        sStatusTip = sToolTipText;
        sPixmap = "actions/TechDraw_PrintAll";

        setCheckable(false);

        addCommand("TechDraw_PrintAll");
        addCommand("TechDraw_ExportPagePDF");
        addCommand("TechDraw_ExportPageSVG");
        addCommand("TechDraw_ExportPageDXF");
    }

    const char* className() const override
    {
        return "CmdTechDrawExportGroup";
    }

    bool isActive() override { return DrawGuiUtil::needPage(this); }
};

//===========================================================================
// TechDraw_ProjectShape
//===========================================================================

DEF_STD_CMD_A(CmdTechDrawProjectShape)

CmdTechDrawProjectShape::CmdTechDrawProjectShape() : Command("TechDraw_ProjectShape")
{
    sAppModule = "TechDraw";
    sGroup = QT_TR_NOOP("TechDraw");
    sMenuText = QT_TR_NOOP("Project Shape");
    sToolTipText = QT_TR_NOOP("Creates a projected geometry of the selected object in the 3D view from the current camera angle");
    sWhatsThis = "TechDraw_ProjectShape";
    sStatusTip = sToolTipText;
    sPixmap = "actions/TechDraw_ProjectShape";
}

void CmdTechDrawProjectShape::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    Gui::TaskView::TaskDialog* dlg = Gui::Control().activeDialog();
    if (!dlg) {
        Gui::Control().showDialog(new TaskDlgProjection());
    }
}

bool CmdTechDrawProjectShape::isActive() { return true; }

void CreateTechDrawCommands()
{
    Gui::CommandManager& rcCmdMgr = Gui::Application::Instance->commandManager();

    rcCmdMgr.addCommand(new CmdTechDrawPageDefault());
    rcCmdMgr.addCommand(new CmdTechDrawPageTemplate());
    rcCmdMgr.addCommand(new CmdTechDrawRedrawPage());
    rcCmdMgr.addCommand(new CmdTechDrawPrintAll());
    rcCmdMgr.addCommand(new CmdTechDrawView());
    rcCmdMgr.addCommand(new CmdTechDrawProjectView());
    rcCmdMgr.addCommand(new CmdTechDrawActiveView());
    rcCmdMgr.addCommand(new CmdTechDrawSectionGroup());
    rcCmdMgr.addCommand(new CmdTechDrawSectionView());
    rcCmdMgr.addCommand(new CmdTechDrawComplexSection());
    rcCmdMgr.addCommand(new CmdTechDrawDetailView());
    rcCmdMgr.addCommand(new CmdTechDrawProjectionGroup());
    rcCmdMgr.addCommand(new CmdTechDrawClipGroup());
    rcCmdMgr.addCommand(new CmdTechDrawClipGroupAdd());
    rcCmdMgr.addCommand(new CmdTechDrawClipGroupRemove());
    rcCmdMgr.addCommand(new CmdTechDrawSymbol());
    rcCmdMgr.addCommand(new CmdTechDrawExportPageSVG());
    rcCmdMgr.addCommand(new CmdTechDrawExportPageDXF());
    rcCmdMgr.addCommand(new CmdTechDrawExportPagePDF());
    rcCmdMgr.addCommand(new CmdTechDrawExportGroup());
    rcCmdMgr.addCommand(new CmdTechDrawDraftView());
    rcCmdMgr.addCommand(new CmdTechDrawArchView());
    rcCmdMgr.addCommand(new CmdTechDrawSpreadsheetView());
    rcCmdMgr.addCommand(new CmdTechDrawBalloon());
    rcCmdMgr.addCommand(new CmdTechDrawProjectShape());
    rcCmdMgr.addCommand(new CmdTechDrawBrokenView());

}

//****************************************


//! extract the selected shapes and xShapes and determine if a face has been
//! selected to define the projection direction
void getSelectedShapes(Gui::Command* cmd,
                      std::vector<App::DocumentObject*>& shapes,
                      std::vector<App::DocumentObject*>& xShapes,
                      App::DocumentObject* faceObj,
                      std::string& faceName)
{
    Gui::ResolveMode resolve = Gui::ResolveMode::OldStyleElement;
    bool single = false;
    auto selection = cmd->getSelection().getSelectionEx(nullptr, App::DocumentObject::getClassTypeId(),
                                                   resolve, single);
    for (auto& sel : selection) {
        bool is_linked = false;
        auto obj = sel.getObject();
        if (obj->isDerivedFrom<TechDraw::DrawPage>()) {
            continue;
        }
        if (obj->isDerivedFrom<App::LinkElement>()
            || obj->isDerivedFrom<App::LinkGroup>()
            || obj->isDerivedFrom<App::Link>()) {
            is_linked = true;
        }
        // If parent of the obj is a link to another document, we possibly need to treat non-link obj as linked, too
        // 1st, is obj in another document?
        if (obj->getDocument() != cmd->getDocument()) {
            std::set<App::DocumentObject*> parents = obj->getInListEx(true);
            for (auto& parent : parents) {
                // Only consider parents in the current document, i.e. possible links in this View's document
                if (parent->getDocument() != cmd->getDocument()) {
                    continue;
                }
                // 2nd, do we really have a link to obj?
                if (parent->isDerivedFrom<App::LinkElement>()
                    || parent->isDerivedFrom<App::LinkGroup>()
                    || parent->isDerivedFrom<App::Link>()) {
                    // We have a link chain from this document to obj, and obj is in another document -> it is an XLink target
                    is_linked = true;
                }
            }
        }
        if (is_linked) {
            xShapes.push_back(obj);
            continue;
        }
        //not a Link and not null.  assume to be drawable.  Undrawables will be
        // skipped later.
        shapes.push_back(obj);
        if (faceObj) {
            continue;
        }
        //don't know if this works for an XLink
        for (auto& sub : sel.getSubNames()) {
            if (TechDraw::DrawUtil::getGeomTypeFromName(sub) == "Face") {
                faceName = sub;
                //
                faceObj = obj;
                break;
            }
        }
    }
}

std::pair<Base::Vector3d, Base::Vector3d> viewDirection()
{
    if (!Preferences::useCameraDirection()) {
        return { Base::Vector3d(0, -1, 0), Base::Vector3d(1, 0, 0) };
    }

    auto faceInfo = faceFromSelection();
    if (faceInfo.first) {
        return DrawGuiUtil::getProjDirFromFace(faceInfo.first, faceInfo.second);
    }

    return DrawGuiUtil::get3DDirAndRot();
}

std::pair<App::DocumentObject*, std::string> faceFromSelection()
{
    auto selection = Gui::Selection().getSelectionEx(
        nullptr, App::DocumentObject::getClassTypeId(), Gui::ResolveMode::NoResolve);

    if (selection.empty()) {
        return { nullptr, "" };
    }

    for (auto& sel : selection) {
        for (auto& sub : sel.getSubNames()) {
            if (TechDraw::DrawUtil::getGeomTypeFromName(sub) == "Face") {
                return { sel.getObject(), sub };
            }
        }
    }

    return { nullptr, "" };
}

//! checks for directions that are almost +/- x,y,z.
Base::Vector3d checkDirectionVsBasis(Base::Vector3d dir)
{
    Base::Vector3d closest = DrawUtil::closestBasisOriented(dir);
    if (dir.IsEqual(closest, Precision::Confusion())) {
        return closest;
    }

    double angleDeg = Base::toDegrees(dir.GetAngle(closest));
    constexpr double MaxAngleDeg{1.0};  // absolutely a WAG.
    if (std::fabs(angleDeg) < MaxAngleDeg) {
        // close to a basis, but not quite equal
        auto msgText = QObject::tr("Selected Direction is within %1 degrees of a standard direction. "
                    "Replace selected Direction with %2?")
                    .arg(QString::number(angleDeg))
                    .arg(QString::fromStdString(DU::formatVector(closest)));
        QMessageBox::StandardButton rc = QMessageBox::question(
            Gui::getMainWindow(), QObject::tr("Direction is close to standard"),
            msgText,
            QMessageBox::StandardButtons(QMessageBox::Yes | QMessageBox::No));
        if (rc == QMessageBox::Yes) {
            return closest;
        }
    }

    // not close to a basis vector.
    return dir;

}

