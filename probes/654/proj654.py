# ops#654 probe: a generic step that only applies a tool (tool once, apply per part).
import FreeCAD as App
import Part


def toolOf(src):
    """The tool a source gives: a PartDesign feature's AddSubShape in the document frame, or a shape."""
    if hasattr(src, "AddSubShape"):
        tool = src.AddSubShape.copy()
        tool.Placement = src.Placement
        return tool
    return src.Shape.copy()


class Applier:
    """One class for every feature type: base (op) tool, then refine."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkGlobal", "Tool", "Step")
        obj.addProperty("App::PropertyString", "Op", "Step").Op = "Cut"
        obj.addProperty("App::PropertyString", "Key", "Step")
        obj.Proxy = self

    def execute(self, obj):
        tool = toolOf(obj.Tool)
        base = obj.BaseFeature.Shape if obj.BaseFeature else Part.Shape()
        if base.isNull():
            if obj.Op != "Fuse":
                raise ValueError("No merge scope selected: nothing to apply to")
            result = tool
        elif obj.Op == "Fuse":
            result = base.fuse(tool)
        elif obj.Op == "Common":
            result = base.common(tool)
        else:
            result = base.cut(tool)
        result = result.removeSplitter()
        obj.AddSubShape = tool
        obj.Shape = result

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class Box:
    """A studio-level tool maker for the property test: a box from a record, computed once."""

    def __init__(self, obj):
        for p in ("X0", "Y0", "X1", "Y1", "Z0", "Z1"):
            obj.addProperty("App::PropertyFloat", p, "Tool")
        obj.Proxy = self

    def execute(self, obj):
        obj.Shape = Part.makeBox(obj.X1 - obj.X0, obj.Y1 - obj.Y0, obj.Z1 - obj.Z0,
                                 App.Vector(obj.X0, obj.Y0, obj.Z0))

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None
