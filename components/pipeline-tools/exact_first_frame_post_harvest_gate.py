#!/usr/bin/env python3
"""Read-only frame-0 authority and frame-0-to-frame-1 continuity gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ssim(left: np.ndarray, right: np.ndarray) -> float:
    a = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY).astype(np.float64)
    b = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY).astype(np.float64)
    ma, mb = float(a.mean()), float(b.mean())
    va, vb = float(a.var()), float(b.var())
    covariance = float(((a - ma) * (b - mb)).mean())
    return ((2 * ma * mb + 6.5025) * (2 * covariance + 58.5225)) / (
        (ma * ma + mb * mb + 6.5025) * (va + vb + 58.5225)
    )


def _phash(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    block = cv2.dct(np.float32(cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)))[:8, :8]
    return (block > np.median(block[1:, :])).flatten()


def pair_metrics(left: np.ndarray, right: np.ndarray) -> dict[str, float | int]:
    small_left = cv2.resize(left, (180, 320), interpolation=cv2.INTER_AREA)
    small_right = cv2.resize(right, (180, 320), interpolation=cv2.INTER_AREA)
    gray_left = cv2.cvtColor(small_left, cv2.COLOR_BGR2GRAY)
    gray_right = cv2.cvtColor(small_right, cv2.COLOR_BGR2GRAY)
    flow = cv2.calcOpticalFlowFarneback(gray_left, gray_right, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    return {
        "mae": float(np.abs(small_left.astype(np.float32) - small_right.astype(np.float32)).mean()),
        "ssim": float(_ssim(small_left, small_right)),
        "phash_hamming": int(np.count_nonzero(_phash(small_left) != _phash(small_right))),
        "mean_luma_jump": abs(float(gray_left.mean()) - float(gray_right.mean())),
        "mean_optical_flow": float(np.linalg.norm(flow, axis=2).mean()),
    }


def frame0_metrics(authority: np.ndarray, decoded: np.ndarray) -> dict[str, float | int]:
    if authority.shape[:2] != decoded.shape[:2]:
        authority = cv2.resize(authority, (decoded.shape[1], decoded.shape[0]), interpolation=cv2.INTER_LANCZOS4)
    difference = authority.astype(np.float32) - decoded.astype(np.float32)
    mse = float(np.square(difference).mean())
    return {
        "mae": float(np.abs(difference).mean()),
        "ssim": float(_ssim(authority, decoded)),
        "phash_hamming": int(np.count_nonzero(_phash(authority) != _phash(decoded))),
        "psnr_db": 10 * math.log10((255.0 * 255.0) / mse) if mse else float("inf"),
    }


def evaluate_arrays(authority: np.ndarray, frames: list[np.ndarray]) -> dict[str, Any]:
    if len(frames) < 13:
        raise ValueError("At least 13 decoded frames are required")
    authority_at_size = cv2.resize(authority, (frames[0].shape[1], frames[0].shape[0]), interpolation=cv2.INTER_LANCZOS4)
    frame0 = frame0_metrics(authority_at_size, frames[0])
    baseline = [pair_metrics(frames[index], frames[index + 1]) for index in range(1, 12)]
    transition = pair_metrics(frames[0], frames[1])
    authority_to_frame1 = pair_metrics(authority_at_size, frames[1])
    median_mae = float(np.median([row["mae"] for row in baseline]))
    median_phash = int(np.median([row["phash_hamming"] for row in baseline]))
    median_luma = float(np.median([row["mean_luma_jump"] for row in baseline]))
    median_flow = float(np.median([row["mean_optical_flow"] for row in baseline]))
    thresholds = {
        "minimum_frame0_ssim": 0.98,
        "maximum_frame0_mae": 3.0,
        "maximum_frame0_phash_hamming": 3,
        "maximum_transition_mae": max(3.0, 3.0 * median_mae),
        "maximum_transition_phash_hamming": max(3, median_phash + 3),
        "maximum_transition_luma_jump": max(3.0, 3.0 * median_luma),
        "maximum_transition_mean_optical_flow": max(1.0, 3.0 * median_flow),
    }
    frame0_pass = (
        float(frame0["ssim"]) >= thresholds["minimum_frame0_ssim"]
        and float(frame0["mae"]) <= thresholds["maximum_frame0_mae"]
        and int(frame0["phash_hamming"]) <= thresholds["maximum_frame0_phash_hamming"]
    )
    transition_pass = (
        float(transition["mae"]) <= thresholds["maximum_transition_mae"]
        and int(transition["phash_hamming"]) <= thresholds["maximum_transition_phash_hamming"]
        and float(transition["mean_luma_jump"]) <= thresholds["maximum_transition_luma_jump"]
        and float(transition["mean_optical_flow"]) <= thresholds["maximum_transition_mean_optical_flow"]
    )
    authority_to_frame1_diagnostic_pass = (
        float(authority_to_frame1["mae"]) <= thresholds["maximum_transition_mae"]
        and int(authority_to_frame1["phash_hamming"]) <= thresholds["maximum_transition_phash_hamming"]
        and float(authority_to_frame1["mean_luma_jump"]) <= thresholds["maximum_transition_luma_jump"]
        and float(authority_to_frame1["mean_optical_flow"]) <= thresholds["maximum_transition_mean_optical_flow"]
    )
    return {
        "status": "PASS" if frame0_pass and transition_pass else "FAIL",
        "frame0_authority": {"status": "PASS" if frame0_pass else "FAIL", "metrics": frame0},
        "frame0_to_frame1_continuity": {
            "status": "PASS" if transition_pass else "FAIL",
            "operands": ["decoded_frame0", "decoded_frame1"],
            "metrics": transition,
        },
        "authority_to_frame1_composite_diagnostic": {
            "status": "PASS" if authority_to_frame1_diagnostic_pass else "FAIL",
            "role": "DIAGNOSTIC_ONLY_DOES_NOT_AFFECT_GATE_STATUS",
            "operands": ["authority_at_decoded_size", "decoded_frame1"],
            "metrics": authority_to_frame1,
        },
        "baseline_medians": {
            "mae": median_mae,
            "phash_hamming": median_phash,
            "mean_luma_jump": median_luma,
            "mean_optical_flow": median_flow,
        },
        "thresholds": thresholds,
        "automatic_repair": "FORBIDDEN_NO_PREPEND_NO_REPLACEMENT",
    }


def evaluate_files(video: Path, authority_image: Path, expected_authority_sha256: str) -> dict[str, Any]:
    if _sha256(authority_image) != expected_authority_sha256:
        raise ValueError("Authority image SHA mismatch")
    authority = cv2.imread(str(authority_image))
    if authority is None:
        raise ValueError("Authority image cannot be decoded")
    capture = cv2.VideoCapture(str(video))
    frames: list[np.ndarray] = []
    while len(frames) < 13:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    report = evaluate_arrays(authority, frames)
    return {
        "schema": "backlotos.exact_first_frame_post_harvest_gate.v1",
        **report,
        "video": str(video),
        "video_sha256": _sha256(video),
        "authority_image": str(authority_image),
        "authority_image_sha256": expected_authority_sha256,
        "human_review_required": [
            "double silhouette or duplicate prop edge",
            "one-frame exposure flash",
            "pose teleport or camera/crop jump",
            "owner/count/transfer discontinuity",
        ],
        "policy": "This gate never mutates media. A failure must be preserved; a one-frame prepend or replacement is not an automatic fix.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--authority-image", required=True)
    parser.add_argument("--authority-sha256", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = evaluate_files(Path(args.video).resolve(), Path(args.authority_image).resolve(), args.authority_sha256)
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
