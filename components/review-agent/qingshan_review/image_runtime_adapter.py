"""Dependency-light CLI wrapper for full-resolution still-image OCR.

This module is intentionally invoked with a Python runtime that already owns
OpenCV/RapidOCR.  The review package itself therefore remains installable in a
small production environment while every recognition keeps its exact box.
"""
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path


def main() -> int:
    p=argparse.ArgumentParser();p.add_argument("--image",required=True);p.add_argument("--out",required=True);p.add_argument("--confidence",type=float,default=.75)
    a=p.parse_args();path=Path(a.image).expanduser().resolve()
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
        frame=cv2.imread(str(path))
        if frame is None:raise RuntimeError("cv2_imread_failed")
        result,_=RapidOCR()(frame);hits=[]
        for box,text,confidence in result or []:
            clean=str(text).strip();score=float(confidence)
            if not clean or score<a.confidence:continue
            xs=[float(x[0]) for x in box];ys=[float(x[1]) for x in box]
            hits.append({"text":clean,"confidence":round(score,6),"region":{"x":round(min(xs),2),"y":round(min(ys),2),"width":round(max(xs)-min(xs),2),"height":round(max(ys)-min(ys),2),"polygon":box}})
        data={"schema":"qingshan.runtime_still_ocr.v1","status":"FAIL" if hits else "PASS","source_image":str(path),"candidate_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"confidence_threshold":a.confidence,"recognitions":hits,"critical_text_failures":len(hits),"engine":"RapidOCR/ONNX Runtime"}
    except Exception as exc:
        data={"schema":"qingshan.runtime_still_ocr.v1","status":"ERROR","source_image":str(path),"candidate_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"error":f"{type(exc).__name__}: {exc}"}
    Path(a.out).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    return 0 if data["status"]=="PASS" else 1

if __name__=="__main__":raise SystemExit(main())
