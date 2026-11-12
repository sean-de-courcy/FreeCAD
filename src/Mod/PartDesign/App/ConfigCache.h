// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
// The cache of other configurations' shapes (FreeCAD-CH ops#671 C3, notes/configurations-design.md
// 12; Onshape's "Studio + instances"). An assembly instance (an App::Link outside a configured
// studio) shows the configuration its ConfigKey names. In the studio's active configuration it
// links the live Body; in any other, it links an entry: a hidden ConfigShape in the studio's
// document holding that configuration's shape of that part.
//  - A studio edit (or an outside object it reads) never builds anything: it marks the studio's
//    entries stale, and after its recompute the instances on stale entries are touched.
//  - The pass runs when a consumer recomputes and an instance asked for it (the reader check):
//    one hidden copy of the studio's document per pass, one switch per key, every entry of that
//    key filled from the copy's Bodies (by part id), then the instances are retargeted, touched
//    and the consumer recomputed. Never inside a transaction (its undo step stays the user's).
//  - Never a stale shape shown as current: an instance on a stale entry errors (or, after a
//    studio edit, stays touched) until the pass; a key that fails errors on its instances, naming
//    the key, with no old shape.
// Stale state lives in memory (a transaction rollback can't revert it in an unknown order); the
// hidden ConfigStale property mirrors it at every stable point and at save, for the next load.

#include <functional>
#include <map>
#include <string>
#include <vector>

#include <App/PropertyStandard.h>
#include <Base/Placement.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class Document;
class DocumentObject;
class Part;
}  // namespace App

namespace PartDesign
{

class Body;

class PartDesignExport ConfigShape: public Part::Feature
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::ConfigShape);

public:
    ConfigShape();
    ~ConfigShape() override;

    App::PropertyString ConfigStudio;  ///< the studio's internal name ("": the document's top level)
    App::PropertyString ConfigKey;     ///< the configuration's canonical key
    App::PropertyString ConfigPartId;  ///< the part's id (Body::StudioPartId)
    App::PropertyString ConfigError;   ///< why the configuration has no such part ("": none)
    App::PropertyBool ConfigStale;     ///< the stale state's mirror, for the next load

    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;
    void onDocumentRestored() override;
    const char* getViewProviderName() const override
    {
        return "PartGui::ViewProviderPart";
    }
    /// A sub name through the Body it stands for ("Pad.Face3", the Tip's name kept by joints)
    /// resolves to the element ("Face3")
    App::DocumentObject* getSubObject(const char* subname,
                                      PyObject** pyObj,
                                      Base::Matrix4D* mat,
                                      bool transform,
                                      int depth) const override;

    bool isStale() const
    {
        return stale;
    }
    void setStale(bool on)
    {
        stale = on;
    }

private:
    bool stale = true;
};

/// Whether obj is an entry or the entries' group (never a studio's object)
PartDesignExport bool isConfigCacheObject(const App::DocumentObject* obj);

/// The reader check's part for an instance (App::Link) on a configured studio's part (a Body) or
/// on an entry: why it can't show its configuration now (empty: it can). It asks for a pass when
/// one would give it its shape
PartDesignExport std::string configCacheReaderError(const App::DocumentObject* reader,
                                                    const App::DocumentObject* source,
                                                    const std::string& c1Error);

/// Runs the pass now for doc's instances (all of them that need one; null: every open document's).
/// Refuses (false, why) while a transaction is open
PartDesignExport bool configRefresh(App::Document* doc, std::string* why);

/// Sets instance's configuration (values: input id or name -> row, bool or value; missing:
/// defaults) and touches it; the next recompute shows it
PartDesignExport bool configSetInstanceKey(App::DocumentObject* instance,
                                           const std::map<std::string, std::string>& values,
                                           std::string* why);

/// A part of a studio in one configuration: its Body in the studio's document, and its global
/// placement in that configuration
struct ConfigStudioPart
{
    Body* body = nullptr;
    Base::Placement placement;
};
/// The parts doc's studio (null: the top level) has in the configuration values names (missing
/// inputs: the defaults), in the document's order (Onshape's whole-studio insert of a configured
/// studio): its Bodies less those merged, consumed or deleted. The active configuration is read
/// live; another from a hidden copy, the document left as it was. A part with no Body in the live
/// document (a piece only that configuration makes) is left out. False, why: no inputs, a bad
/// value, a copy or a switch that failed
PartDesignExport bool configStudioParts(App::Document* doc,
                                        App::Part* studio,
                                        const std::map<std::string, std::string>& values,
                                        std::vector<ConfigStudioPart>& parts,
                                        std::string* why);
/// The Body an instance stands for (its ConfigPart, else its linked Body), or null
PartDesignExport App::DocumentObject* configInstancePart(const App::DocumentObject* instance);

/// doc's entries
PartDesignExport std::vector<ConfigShape*> configCacheEntries(const App::Document* doc);

struct ConfigCacheStats
{
    long passes = 0;    ///< passes run
    long copies = 0;    ///< hidden copies opened
    long keys = 0;      ///< switches made in copies
    long fills = 0;     ///< entries filled (a shape or an error)
    long deferred = 0;  ///< passes put off (a transaction open)
    long foreignWrites = 0;  ///< writes in the cache's unrecorded scope it doesn't call derived (warned)
    double copySeconds = 0;  ///< time spent saving and opening copies
};
PartDesignExport ConfigCacheStats configCacheStats();

/// How the GUI runs a requested pass (PartDesignGui: QTimer::singleShot(0)); without one, it runs
/// at once (FreeCADCmd)
PartDesignExport void setConfigPassScheduler(std::function<void(std::function<void()>)> scheduler);

/// While alive, edits are a configuration switch's, not intent: nothing is marked stale
class PartDesignExport ConfigSwitchGuard
{
public:
    ConfigSwitchGuard();
    ~ConfigSwitchGuard();
    ConfigSwitchGuard(const ConfigSwitchGuard&) = delete;
    ConfigSwitchGuard& operator=(const ConfigSwitchGuard&) = delete;
};

/// Connects the stale marking and the pass trigger; at module init
PartDesignExport void registerConfigCacheHooks();

}  // namespace PartDesign
