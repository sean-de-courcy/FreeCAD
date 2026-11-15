import json, sys
for l in open(sys.argv[1]):
    d = json.loads(l)
    if "debug" in d:
        print("DEBUG", d); continue
    if "summary" in d:
        print("SUMMARY", d["summary"]); continue
    v = d.get("verdict")
    line = f'{d["step"]:3} {d["kind"]:9} {str(d.get("desc"))[:28]:28} {v:7} rc={d.get("solve")} t={d.get("t")}'
    if v != "OK" or len(sys.argv) > 2:
        line += f' bad={(d.get("bad") or [])[:3]} err={(d.get("errors") or [])[:2]} fresh={(d.get("fresh") or [])[:3]} {d.get("exc","")}'
    print(line)
