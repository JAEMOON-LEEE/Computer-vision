"""Download a bounded TAD research pilot from the authors' public Drive archive.

Only public source media are read; no remote scripts are executed. Zipfile
verifies CRCs, and output paths are constructed from validated video basenames.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

import requests

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"datasets/public-sources/real-traffic-v1/tad"
INDEX=ROOT/"runs/real-traffic-v1/tad-index.json"


class HTTPRangeFile(io.RawIOBase):
    def __init__(self,url,size):self.url=url;self.size=size;self.pos=0;self.cache_start=-1;self.cache=b""
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.pos
    def seek(self,offset,whence=0):
        self.pos=offset if whence==0 else self.pos+offset if whence==1 else self.size+offset
        if self.pos<0:raise ValueError("Negative archive seek")
        return self.pos
    def read(self,n=-1):
        n=self.size-self.pos if n<0 else min(n,self.size-self.pos)
        if n<=0:return b""
        if n>256*1024*1024:raise ValueError("Pilot archive member exceeds memory bound")
        if self.cache_start<=self.pos and self.pos+n<=self.cache_start+len(self.cache):
            start=self.pos-self.cache_start;value=self.cache[start:start+n]
        else:
            start=self.pos;end=min(self.size-1,start+max(n,65536)-1)
            with requests.get(self.url,headers={"Range":f"bytes={start}-{end}"},timeout=(15,120)) as response:
                response.raise_for_status()
                if response.status_code!=206 or response.headers.get("Content-Range")!=f"bytes {start}-{end}/{self.size}":raise ValueError("Unexpected archive range")
                content=response.content
            if len(content)!=end-start+1:raise ValueError("Truncated archive range")
            if n<65536:self.cache_start,self.cache=start,content
            value=content[:n]
        self.pos+=len(value);return value


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/"manifest.json").exists():print("Existing TAD pilot preserved");return
    if not INDEX.exists():
        response=requests.get("https://drive.google.com/uc?export=download&id=14GNlNcWLzN-sbzvmrMuSbAg_rZZ5yd26",timeout=30);response.raise_for_status()
        uuid=re.search('name="uuid" value="([^"]+)',response.text)
        if not uuid:raise ValueError("Public Drive download form changed")
        url="https://drive.usercontent.google.com/download?id=14GNlNcWLzN-sbzvmrMuSbAg_rZZ5yd26&export=download&confirm=t&uuid="+uuid[1]
        with requests.get(url,headers={"Range":"bytes=0-1"},timeout=30) as response:
            response.raise_for_status();size=int(response.headers["Content-Range"].split("/")[-1])
        with zipfile.ZipFile(HTTPRangeFile(url,size)) as archive:
            files=[{"name":m.filename,"size":m.file_size,"compressed":m.compress_size} for m in archive.infolist()]
        INDEX.parent.mkdir(parents=True,exist_ok=True);INDEX.write_text(json.dumps({"url":url,"size":size,"files":files},ensure_ascii=False,indent=2),encoding="utf8")
    index=json.loads(INDEX.read_text(encoding="utf8"));groups={}
    for entry in index["files"]:
        name=entry["name"]
        if not name.endswith(".mp4"):continue
        official="test" if "/test/" in name else "train";target=0 if "/normal/" in name else 1
        groups.setdefault((official,target),[]).append(entry)
    selected=[]
    for (official,target),entries in groups.items():
        entries=sorted(entries,key=lambda e:(e["size"],e["name"]))[:60 if official=="train" else 100]
        entries=sorted(entries,key=lambda e:hashlib.sha256(e["name"].encode()).hexdigest())
        for i,entry in enumerate(entries):
            selected.append({**entry,"split":"test" if official=="test" else "val" if i<12 else "train","target":target,"official_split":official})
    def acquire(entry):
        filename=Path(entry["name"]).name
        if not re.fullmatch(r"[a-zA-Z0-9_-]+\.mp4",filename):raise ValueError("Unexpected video name")
        target=OUT/entry["split"]/("accident" if entry["target"] else "normal")/filename
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists() or target.stat().st_size!=entry["size"]:
            with zipfile.ZipFile(HTTPRangeFile(index["url"],index["size"])) as archive:payload=archive.read(entry["name"])
            part=target.with_suffix(".mp4.part");part.write_bytes(payload);part.replace(target)
        payload=target.read_bytes()
        return {**entry,"path":str(target.resolve()),"sha256":hashlib.sha256(payload).hexdigest()}
    rows=[]
    with ThreadPoolExecutor(4) as pool:
        for row in pool.map(acquire,selected):
            rows.append(row)
            if len(rows)%10==0:print("TAD verified",len(rows),"/",len(selected),flush=True)
    report={"source":"https://github.com/UnicomAI/UnicomBenchmark/tree/main/TADBench",
        "source_archive_size":index["size"],"license":"No explicit dataset license in source README; local research pilot only; no redistribution",
        "labels":"Weak clip-level labels from official accident/normal folders; not contact-frame or participant labels",
        "selection":"Smallest 60 per class from official train; first12 by SHA used for validation; all official test",
        "camera_disjoint":False,"clips":rows}
    (OUT/"manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    print("TAD ready",len(rows),"bytes",sum(r["size"] for r in rows),flush=True)


if __name__=="__main__":main()
