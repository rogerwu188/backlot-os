"""Scan an exact time range of a video with RapidOCR and preserve frame evidence."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--video',required=True);p.add_argument('--out',required=True);p.add_argument('--start',type=float,required=True);p.add_argument('--end',type=float,required=True);p.add_argument('--interval',type=float,default=.5);p.add_argument('--confidence',type=float,default=.5);a=p.parse_args();video=Path(a.video).resolve()
 try:
  import cv2
  from rapidocr_onnxruntime import RapidOCR
  cap=cv2.VideoCapture(str(video));engine=RapidOCR();rows=[];samples=[];t=max(0,a.start)
  if not cap.isOpened():raise RuntimeError('cv2_video_open_failed')
  while t<a.end-1e-6:
   cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read()
   if not ok:raise RuntimeError(f'frame_decode_failed_at_{t:.6f}')
   frame_no=int(round(cap.get(cv2.CAP_PROP_POS_FRAMES)-1));samples.append({'time_seconds':round(t,6),'frame':frame_no})
   result,_=engine(frame)
   for box,text,confidence in result or []:
    clean=str(text).strip();score=float(confidence)
    if clean and score>=a.confidence:rows.append({'time_seconds':round(t,6),'frame':frame_no,'text':clean,'confidence':round(score,6),'region':{'polygon':box}})
   t+=a.interval
  cap.release();data={'schema':'qingshan.video_ocr_gap_scan.v1','status':'PASS','video':str(video),'candidate_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'start_seconds':a.start,'end_seconds':a.end,'sample_interval_seconds':a.interval,'sample_count':len(samples),'samples':samples,'recognitions':rows,'engine':'RapidOCR/ONNX Runtime'}
 except Exception as exc:data={'schema':'qingshan.video_ocr_gap_scan.v1','status':'ERROR','video':str(video),'candidate_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'start_seconds':a.start,'end_seconds':a.end,'error':f'{type(exc).__name__}: {exc}'}
 Path(a.out).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');return 0 if data['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
