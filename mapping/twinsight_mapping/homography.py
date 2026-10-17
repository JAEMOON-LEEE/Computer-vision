"""픽셀 좌표 ↔ 노면 좌표 Homography."""

from __future__ import annotations

import cv2
import numpy as np


def fit_homography(pixels: np.ndarray, ground: np.ndarray) -> np.ndarray:
    """픽셀 (N, 2) → 노면 (N, 2) Homography를 최소제곱으로 구한다. 점은 4개 이상 필요하다."""
    pixels = np.asarray(pixels, dtype=np.float64)
    ground = np.asarray(ground, dtype=np.float64)
    if len(pixels) < 4:
        raise ValueError(f"Homography에는 기준점이 4개 이상 필요합니다 (현재 {len(pixels)}개)")

    H, _ = cv2.findHomography(pixels, ground, method=0)
    if H is None:
        raise ValueError("Homography를 구하지 못했습니다. 기준점이 한 직선 위에 몰려 있지 않은지 확인하세요")

    # 기준점에서 동차 좌표 w가 양수가 되도록 부호를 맞춘다. 그래야 지평선 너머(w <= 0)를 가려낼 수 있다.
    w = np.c_[pixels, np.ones(len(pixels))] @ H[2]
    if np.median(w) < 0:
        H = -H
    return H / np.linalg.norm(H)


def pixels_to_ground(H: np.ndarray, pixels: np.ndarray) -> np.ndarray:
    """픽셀 (N, 2) → 노면 (N, 2). 지평선 위쪽 픽셀은 노면에 닿지 않으므로 nan."""
    pixels = np.atleast_2d(np.asarray(pixels, dtype=np.float64))
    homogeneous = np.c_[pixels, np.ones(len(pixels))] @ H.T
    w = homogeneous[:, 2:3]
    with np.errstate(divide="ignore", invalid="ignore"):
        ground = homogeneous[:, :2] / w
    ground[w[:, 0] <= 1e-12] = np.nan
    return ground


def select_spread_points(pixels: np.ndarray, n: int) -> np.ndarray:
    """화면 전체에 고르게 퍼진 n개 점의 인덱스(최원점 샘플링).

    실제 CCTV에서 기준점을 고를 때처럼 화면 구석구석에서 점을 고른다.
    """
    pixels = np.asarray(pixels, dtype=np.float64)
    n = min(n, len(pixels))
    if n <= 0:
        return np.empty(0, dtype=int)

    chosen = [int(np.argmax(np.linalg.norm(pixels - pixels.mean(axis=0), axis=1)))]
    nearest = np.linalg.norm(pixels - pixels[chosen[0]], axis=1)
    while len(chosen) < n:
        idx = int(np.argmax(nearest))
        chosen.append(idx)
        nearest = np.minimum(nearest, np.linalg.norm(pixels - pixels[idx], axis=1))
    return np.array(chosen, dtype=int)
