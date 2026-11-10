# ops#654: the studio's ordered feature list as the only truth; each Body's chain is its projection.
# reconcile() diffs the projection against the document and creates, reorders, suppresses or removes
# steps, reusing step objects by (feature key, part). Property test: random edit sequences, after each
# one the document must equal the one built from scratch from the final list.
# Designed geometry: three 10 mm boxes A (x0..10), B (x20..30), C (x40..50); a feature is a box tool
# (cut or fuse) from a record, computed once at studio level; each part gets a generic applier step.
import os, sys, json, random, traceback, time
sys.path.insert(0, r"D:\CustomFreeCAD\work\standby-a\mods")
import FreeCAD as App
import Part, PartDesign
import proj654
from PartDesignTests.TestStudio import pad, sketch, xyPlane

OUT = os.environ.get("RECON_OUT", r"D:\CustomFreeCAD\work\standby-a\reconcile.log")
FILES = r"D:\CustomFreeCAD\work\standby-a\files"
BUG = os.environ.get("RECON_BUG") == "append"
PARTS = (("A", 0), ("B", 20), ("C", 40))
L = []


def log(*a):
    L.append(" ".join(str(x) for x in a))


# ----------------------------------------------------------------------------- the list (truth)
def readList(doc):
    h = doc.getObject("History")
    return json.loads(h.Records), h.Bar


def writeList(doc, records, bar):
    h = doc.getObject("History")
    h.Records = json.dumps(records)
    h.Bar = bar


def project(records, bar):
    """part -> [(key, suppressed)] in order: every record with a step in that part. A part dropped from
    a scope keeps its step, suppressed ("kept"); a record at or after the bar is held (Tip before it)."""
    chains = {p: [] for p, _ in PARTS}
    for r in records:
        for p in r["scope"] + r["kept"]:
            chains[p].append((r["key"], r["suppressed"] or p not in r["scope"]))
    tips = {}
    for p in chains:
        held = {r["key"] for r in records[bar:]}
        active = [k for k, _ in chains[p] if k not in held]
        tips[p] = active[-1] if active else None
    return chains, tips


# ----------------------------------------------------------------------------- the document
def newStudio(name):
    doc = App.newDocument(name)
    doc.UndoMode = 1
    S = doc.addObject("App::Part", "S")
    h = doc.addObject("App::FeaturePython", "History")
    h.addProperty("App::PropertyString", "Records", "History").Records = "[]"
    h.addProperty("App::PropertyInteger", "Bar", "History").Bar = 0
    S.addObject(h)
    for p, x in PARTS:
        b = doc.addObject("PartDesign::Body", p)
        S.addObject(b)
        pad(b, p + "Pad", sketch(b, p + "Sk", xyPlane(b), (x, 0, x + 10, 10)), 10)
    doc.recompute()
    return doc


def toolName(key):
    return "T_" + key


def stepName(key, part):
    return f"St_{key}_{part}"


def reconcile(doc):
    records, bar = readList(doc)
    chains, tips = project(records, bar)
    S = doc.getObject("S")
    byKey = {r["key"]: r for r in records}
    # tools: one per record, at studio level
    for r in records:
        t = doc.getObject(toolName(r["key"]))
        if not t:
            t = doc.addObject("Part::FeaturePython", toolName(r["key"]))
            proj654.Box(t)
            S.addObject(t)
        x0, y0, x1, y1 = r["rect"]
        z0, z1 = (10 - r["depth"], 10.001) if r["op"] == "Cut" else (9.999, 10 + r["depth"])
        vals = dict(X0=x0, Y0=y0, X1=x1, Y1=y1, Z0=z0, Z1=z1)
        for k, v in vals.items():
            if abs(getattr(t, k) - v) > 1e-12:
                setattr(t, k, v)
    for o in list(doc.Objects):
        if o.Name.startswith("T_") and o.Name[2:] not in byKey:
            doc.removeObject(o.Name)
    for p, _ in PARTS:
        body = doc.getObject(p)
        want = chains[p]
        wantKeys = [k for k, _ in want]
        have = {o.Key: o for o in body.Group if hasattr(o, "Key")}
        # remove steps whose record or part is gone
        for k, o in list(have.items()):
            if k not in wantKeys:
                body.removeObject(o)
                doc.removeObject(o.Name)
                del have[k]
        base = doc.getObject(p + "Pad")
        prev = base
        for k, sup in want:
            r = byKey[k]
            o = have.get(k)
            if not o:
                cls = "PartDesign::FeatureSubtractivePython" if r["op"] == "Cut" else "PartDesign::FeatureAdditivePython"
                o = doc.addObject(cls, stepName(k, p))
                proj654.Applier(o)
                o.Key = k
                if BUG:
                    body.insertObject(o, None, False)  # appended at the end, as makeSiblings does today
                else:
                    body.insertObject(o, prev, True)
                have[k] = o
            elif BUG:
                pass
            else:
                # in place? the step right after prev in the Body's solid chain
                solids = [x for x in body.Group if x.isDerivedFrom("PartDesign::Feature")]
                i = solids.index(prev)
                if i + 1 >= len(solids) or solids[i + 1] is not o:
                    body.removeObject(o)
                    body.insertObject(o, prev, True)
            if o.Tool != doc.getObject(toolName(k)):
                o.Tool = doc.getObject(toolName(k))
            if o.Op != r["op"]:
                o.Op = r["op"]
            if o.Suppressed != sup:
                o.Suppressed = sup
            prev = o
        tipKey = tips[p]
        tip = have[tipKey] if tipKey else base
        if body.Tip != tip:
            body.Tip = tip


def snapshot(doc):
    """What must equal the from-scratch build: per Body the steps in order (key, suppressed), the Tip,
    and the Tip's volume, area and solid count."""
    out = {}
    for p, _ in PARTS:
        body = doc.getObject(p)
        steps = [(o.Key, bool(o.Suppressed)) for o in body.Group if hasattr(o, "Key")]
        tip = body.Tip
        shp = tip.Shape
        out[p] = dict(steps=steps, tip=getattr(tip, "Key", "base"), volume=round(shp.Volume, 4),
                      area=round(shp.Area, 4), solids=len(shp.Solids))
    return out


def fromScratch(records, bar):
    d = newStudio("scratch")
    writeList(d, records, bar)
    reconcile(d)
    d.recompute()
    snap = snapshot(d)
    App.closeDocument(d.Name)
    return snap


# ----------------------------------------------------------------------------- random edits
def touches(rect):
    x0, _, x1, _ = rect
    return [p for p, x in PARTS if x0 < x + 10 and x1 > x]


def op_insert(rng, records, bar, counter):
    x0 = rng.choice([2, 5, 8, 22, 25, 42, 45, 5, 25])
    w = rng.choice([2, 4, 8, 20, 25])
    y0 = rng.choice([1, 2, 4])
    rect = [x0, y0, x0 + w, y0 + rng.choice([2, 3, 5])]
    parts = touches(rect) or ["A"]
    scope = sorted(rng.sample(parts, rng.randint(1, len(parts))))
    r = dict(key=f"F{counter}", rect=rect, depth=rng.choice([1, 2, 3, 4]), op=rng.choice(["Cut", "Cut", "Fuse"]),
             scope=scope, kept=[], suppressed=False)
    at = rng.randint(0, len(records))
    records.insert(at, r)
    if at < bar or bar == len(records) - 1:
        bar += 1
    return records, bar, f"insert {r['key']} {r['op']} {rect} d{r['depth']} scope {scope} at {at}"


def edit(rng, records, bar, counter):
    kinds = ["insert"] * 3 + ["delete", "move", "scope", "depth", "suppress", "bar"]
    if not records:
        kinds = ["insert"]
    k = rng.choice(kinds)
    records = json.loads(json.dumps(records))
    if k == "insert":
        return op_insert(rng, records, bar, counter)
    i = rng.randrange(len(records))
    r = records[i]
    if k == "delete":
        del records[i]
        if i < bar:
            bar -= 1
        return records, bar, f"delete {r['key']}"
    if k == "move":
        j = rng.randrange(len(records))
        records.insert(j, records.pop(i))
        return records, bar, f"move {r['key']} {i}->{j}"
    if k == "scope":
        p = rng.choice([p for p, _ in PARTS])
        if p in r["scope"] and len(r["scope"]) > 1:
            r["scope"].remove(p)
            if p not in r["kept"]:
                r["kept"].append(p)
        elif p not in r["scope"]:
            r["scope"] = sorted(r["scope"] + [p])
            if p in r["kept"]:
                r["kept"].remove(p)
        return records, bar, f"scope {r['key']} {r['scope']} kept {r['kept']}"
    if k == "depth":
        r["depth"] = rng.choice([1, 2, 3, 4, 5])
        return records, bar, f"depth {r['key']} {r['depth']}"
    if k == "suppress":
        r["suppressed"] = not r["suppressed"]
        return records, bar, f"suppress {r['key']} {r['suppressed']}"
    bar = rng.randint(0, len(records))
    return records, bar, f"bar {bar}"


def run(seed, nops):
    rng = random.Random(seed)
    doc = newStudio(f"prop{seed}")
    path = os.path.join(FILES, f"prop{seed}.FCStd")
    counter = 0
    bad = 0
    history = []
    for step in range(nops):
        roll = rng.random()
        if roll < 0.12 and doc.UndoCount:
            doc.undo()
            what = "undo"
        elif roll < 0.18 and doc.RedoCount:
            doc.redo()
            what = "redo"
        elif roll < 0.23:
            doc.saveAs(path)
            App.closeDocument(doc.Name)
            doc = App.openDocument(path)
            doc.UndoMode = 1
            what = "save, close, reopen"
        else:
            records, bar = readList(doc)
            counter += 1
            records, bar, what = edit(rng, records, bar, counter)
            doc.openTransaction(what)
            writeList(doc, records, bar)
            reconcile(doc)
            doc.commitTransaction()
        doc.recompute()
        bad_objs = [o.Name for o in doc.Objects if "Invalid" in o.State]
        records, bar = readList(doc)
        got = snapshot(doc)
        want = fromScratch(records, bar)
        history.append(what)
        if got != want or bad_objs:
            bad += 1
            log(f"  seed {seed} op {step} MISMATCH after: {what}")
            log(f"    errors: {bad_objs}")
            for p in got:
                if got[p] != want[p]:
                    log(f"    {p}: doc {got[p]}")
                    log(f"    {p}: new {want[p]}")
            if bad > 3:
                break
    stats = dict(records=len(readList(doc)[0]), objects=len(doc.Objects))
    App.closeDocument(doc.Name)
    return bad, history, stats


t0 = time.time()
total = 0
try:
    seeds = [int(s) for s in os.environ.get("RECON_SEEDS", "1,2,3,4,5,6").split(",")]
    nops = int(os.environ.get("RECON_OPS", "40"))
    for seed in seeds:
        bad, hist, stats = run(seed, nops)
        total += bad
        kinds = {}
        for h in hist:
            kinds[h.split()[0]] = kinds.get(h.split()[0], 0) + 1
        log(f"seed {seed}: {len(hist)} ops, mismatches {bad}, ops {kinds}, final {stats}")
except Exception:
    log("EXCEPTION " + traceback.format_exc())
    total += 1
log(f"TOTAL mismatches {total}, {time.time() - t0:.0f} s")
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(L) + "\n")
os._exit(0)
