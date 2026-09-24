#!/usr/bin/env python3
"""3절 — 모든 세션·조각의 동시 검출 비율과 적중률을 한 표로 모은다.
라벨 파일(/tmp/labels.json)이 있으면 정답 라벨을 붙여 빈 구간을 검증한다.
"""
import json, glob, os
LAB=json.load(open("/tmp/labels.json")) if os.path.exists("/tmp/labels.json") else {}
rows=[]
for f in sorted(glob.glob("/tmp/score_*_*.json")):
    d=json.load(open(f))
    tag=d["session"].split("_")[1]; mode=d["mode"]
    for n,v in d["pieces"].items():
        key=f"{tag}|{mode}|{n}"
        rows.append(dict(tag=tag,mode=mode,name=n,label=LAB.get(key,"?"),
                         kind=v["kind"],area=v["area"],size=v["size"],hit=v["hit"],
                         one=v["one"],two=v["two"],ratio=v["ratio"],
                         n_hi=v["n_hi"],n_lo=v["n_lo"],cmax=v["conf_hi_max"]))
print(f"조각 {len(rows)}개\n")
print("3-1. 동시 검출 비율 (덮는 프레임 >= 5 인 조각만 — 표본이 적으면 비율이 무의미)")
sub=[r for r in rows if r["mode"]=="_new" and r["one"]>=5]
for r in sorted(sub,key=lambda x:x["ratio"]):
    print(f"  {r['tag']:<12}{r['name']:<22}{r['label']:<16}"
          f"{r['ratio']*100:>7.1f}%  ({r['two']}/{r['one']})  적중{r['hit']*100:5.1f}%")
print("\n3-2. 적중률 오름차순 (전부)")
for r in sorted([x for x in rows if x["mode"]=="_new"],key=lambda x:x["hit"]):
    print(f"  {r['tag']:<12}{r['name']:<22}{r['label']:<16}{r['hit']*100:>6.1f}%"
          f"  고신뢰{r['n_hi']:>5} 저신뢰{r['n_lo']:>5} maxconf{r['cmax']:.2f}")
