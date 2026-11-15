# make_r3.py: oracle 26's R3 batch (ops#640). Plain Python, no FreeCAD.
#   python3 make_r3.py templates <dir>              writes <dir>/T1.json T2.json T3.json T5f.json T5c.json
#   python3 make_r3.py rows <dir> <truth jsonl>...  writes <dir>/rows.txt: up to 60 BEYOND states, `T<n> {p:v,...} edit_tail`
# A template is an Onshape feature list in order. Every number is an expression over the NAMED parameters (Onshape
# variables #name, defaults given), so a row is rebuilt by setting the variables and regenerating, never by replaying
# edits. Units mm and degrees. Planes: Top = XY, Front = XZ, Right = YZ. Return per row: volume, area, face count,
# and each feature's state (OK / warning / error), as for R1 and R2.
import json, os, sys, random

T1 = dict(template="T1", note="plate with a through-all rectangular pocket, a cylinder boss, a through hole and a 90 deg countersink hole",
    params=dict(a=100, b=60, t=8, px=10, py=10, pw=20, ph=15, bx=50, by=40, rb=8, hb=10, hx=80, hy=15, rh=4, kx=80, ky=45, d=5, D=10),
    features=[
        dict(name="PlateSk", type="sketch", plane="Top", entities=[dict(rect=dict(corner=["0", "0"], size=["#a", "#b"]))]),
        dict(name="Plate", type="extrude", op="new", profile="PlateSk", end="blind", depth="#t"),
        dict(name="PocketSk", type="sketch", plane="top face of Plate (z = #t)", entities=[dict(rect=dict(corner=["#px", "#py"], size=["#pw", "#ph"]))]),
        dict(name="ThruPocket", type="extrude", op="remove", profile="PocketSk", end="through all", direction="-Z"),
        dict(name="BossSk", type="sketch", plane="top face of Plate", entities=[dict(circle=dict(center=["#bx", "#by"], radius="#rb"))]),
        dict(name="Boss", type="extrude", op="add", profile="BossSk", end="blind", depth="#hb", direction="+Z"),
        dict(name="HoleSk", type="sketch", plane="top face of Plate", entities=[dict(circle=dict(center=["#hx", "#hy"], radius="#rh"))]),
        dict(name="ThruHole", type="extrude", op="remove", profile="HoleSk", end="through all", direction="-Z"),
        dict(name="CSinkSk", type="sketch", plane="top face of Plate", entities=[dict(point=["#kx", "#ky"])]),
        dict(name="CSink", type="hole", style="countersink", diameter="#d", countersink_diameter="#D", countersink_angle="90", end="through all", at="CSinkSk point"),
    ])
T2 = dict(template="T2", note="centred plate; a linear pattern of m blind (or through) pockets; a circular pattern of n through holes about Z",
    params=dict(a=120, b=80, t=10, x0=-50, y0=-37, w=12, h=8, d=4, m=4, L=80, R=18, rh=3, n=6),
    features=[
        dict(name="PlateSk", type="sketch", plane="Top", entities=[dict(rect=dict(corner=["-#a/2", "-#b/2"], size=["#a", "#b"]))]),
        dict(name="Plate", type="extrude", op="new", profile="PlateSk", end="blind", depth="#t"),
        dict(name="RowSk", type="sketch", plane="top face of Plate", entities=[dict(rect=dict(corner=["#x0", "#y0"], size=["#w", "#h"]))]),
        dict(name="RowPocket", type="extrude", op="remove", profile="RowSk", end="blind", depth="#d", direction="-Z",
             note="when #d >= #t it cuts through; FreeCAD then clips at the plate's bottom"),
        dict(name="RowPat", type="linear pattern", kind="feature", of="RowPocket", direction="X", count="#m", spacing="#L/(#m-1)",
             note="FreeCAD's Length is first-to-last = #L"),
        dict(name="HoleSk", type="sketch", plane="top face of Plate", entities=[dict(circle=dict(center=["#R", "0"], radius="#rh"))]),
        dict(name="Hole", type="extrude", op="remove", profile="HoleSk", end="through all", direction="-Z"),
        dict(name="HolePat", type="circular pattern", kind="feature", of="Hole", axis="Z (Top plane normal through the origin)", count="#n", angle="360", equal_spacing=True),
    ])
T3 = dict(template="T3", note="centred box; a cylinder boss on top; mirrored about the Right plane (the copies overlap when |cx| < r)",
    params=dict(a=100, b=60, t=8, cx=25, cy=0, r=10, h=12),
    features=[
        dict(name="PlateSk", type="sketch", plane="Top", entities=[dict(rect=dict(corner=["-#a/2", "-#b/2"], size=["#a", "#b"]))]),
        dict(name="Plate", type="extrude", op="new", profile="PlateSk", end="blind", depth="#t"),
        dict(name="BossSk", type="sketch", plane="top face of Plate", entities=[dict(circle=dict(center=["#cx", "#cy"], radius="#r"))]),
        dict(name="Boss", type="extrude", op="add", profile="BossSk", end="blind", depth="#h", direction="+Z"),
        dict(name="MirBoss", type="mirror", kind="feature", of="Boss", plane="Right", op="add"),
    ])
def t5(kind):
    return dict(template="T5" + kind[0].lower(), note="box a x b x c; an equal %s of size r on all 12 edges (all=1) or on the 4 edges parallel to Z (all=0)" % kind.lower(),
        params=dict(a=40, b=30, c=20, r=3, all=1),
        features=[
            dict(name="BoxSk", type="sketch", plane="Top", entities=[dict(rect=dict(corner=["0", "0"], size=["#a", "#b"]))]),
            dict(name="Box", type="extrude", op="new", profile="BoxSk", end="blind", depth="#c"),
            dict(name="Dress", type=kind.lower(), edges="all=1: all 12 edges of Box; all=0: the 4 edges of Box parallel to Z",
                 **({"radius": "#r", "cross_section": "circular"} if kind == "Fillet" else {"distance": "#r", "chamfer_type": "equal distance"})),
        ])
TEMPLATES = dict(T1=T1, T2=T2, T3=T3, T5f=t5("Fillet"), T5c=t5("Chamfer"))

if sys.argv[1] == "templates":
    os.makedirs(sys.argv[2], exist_ok=True)
    for k, x in TEMPLATES.items():
        json.dump(x, open(os.path.join(sys.argv[2], k + ".json"), "w"), indent=1)
else:
    rows = {}
    for f in sys.argv[3:]:
        for line in open(f):
            r = json.loads(line)
            if r.get("v") == "BEYOND" and r.get("p"):
                t = os.path.basename(f).split("-")[0]
                key = (t, json.dumps(r["p"], sort_keys=True))
                rows.setdefault(key, "%s %s %s | FreeCAD: %s V=%s A=%s red=%s" % (t, json.dumps(r["p"], sort_keys=True).replace(" ", ""),
                    r["edit"].replace(" ", ""), r.get("why"), None if r.get("vol") is None else round(r["vol"], 3),
                    None if r.get("area") is None else round(r["area"], 3), ",".join(r.get("red") or []) or "-"))
    by = {}
    for (t, _p), line in rows.items():
        by.setdefault(t, []).append(line)
    rng = random.Random(26); out = []
    for t in sorted(by):   # even share per template, 60 at most
        rng.shuffle(by[t]); out += by[t][:60 // len(by)]
    open(os.path.join(sys.argv[2], "rows.txt"), "w").write("\n".join(out) + "\n")
    print(len(out), "rows of", len(rows))
