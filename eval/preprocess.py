"""Image preprocessing variants for the OCR evaluation. Not used by the app."""
from __future__ import annotations

import math

import cv2
import numpy as np


def deskew(bgr: np.ndarray) -> tuple[np.ndarray, float]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, 1, math.pi / 180, threshold=80,
        minLineLength=max(bgr.shape[1] // 5, 40), maxLineGap=30,
    )
    if lines is None:
        return bgr, 0.0
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if abs(angle) <= 12:
            angles.append(angle)
    if len(angles) < 3:
        return bgr, 0.0
    angle = float(np.median(angles))
    if abs(angle) < 0.4:
        return bgr, 0.0
    height, width = bgr.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    rotated = cv2.warpAffine(
        bgr, matrix, (width, height), flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255),
    )
    return rotated, angle


def denoise(bgr: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoisingColored(bgr, None, 6, 6, 7, 21)


def binarize(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 15)
    return cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)


def upscale(bgr: np.ndarray) -> tuple[np.ndarray, float]:
    height, width = bgr.shape[:2]
    short = min(height, width)
    if short >= 1200:
        return bgr, 1.0
    scale = min(3.0, 1200 / short)
    out = cv2.resize(bgr, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_CUBIC)
    return out, scale


def _red_mask(bgr: np.ndarray) -> np.ndarray:
    red = bgr[:, :, 2].astype(np.int16)
    green = bgr[:, :, 1].astype(np.int16)
    blue = bgr[:, :, 0].astype(np.int16)
    return (red > 140) & (red > green + 35) & (red > blue + 35)


def suppress_red(bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Drop red ink by color channel. Dark text under a seal is kept via min(G, B)."""
    out = bgr.copy()
    darker = np.minimum(bgr[:, :, 0], bgr[:, :, 1])
    painted = np.stack([darker, darker, darker], axis=-1)
    # Pure red ink sits on white paper: push those pixels to white.
    # Mixed pixels (red over black) keep the darker channel.
    white_ink = mask & (darker > 180)
    out[white_ink] = 255
    keep = mask & ~white_ink
    out[keep] = painted[keep]
    return out


def red_channel(bgr: np.ndarray) -> np.ndarray:
    return suppress_red(bgr, _red_mask(bgr))


def _seal_circles(bgr: np.ndarray) -> list[tuple[int, int, int]]:
    mask = _red_mask(bgr).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    circles = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 800:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        circularity = 4 * math.pi * area / (perimeter * perimeter)
        if circularity < 0.45:
            continue
        (x, y), radius = cv2.minEnclosingCircle(contour)
        circles.append((int(x), int(y), int(radius * 1.05) + 2))
    return circles


def red_seal_only(bgr: np.ndarray) -> np.ndarray:
    circles = _seal_circles(bgr)
    if not circles:
        return bgr
    region = np.zeros(bgr.shape[:2], dtype=np.uint8)
    for x, y, radius in circles:
        cv2.circle(region, (x, y), radius, 1, thickness=-1)
    return suppress_red(bgr, _red_mask(bgr) & region.astype(bool))


def seal_circles_pil_space(bgr: np.ndarray) -> list[tuple[int, int, int]]:
    return _seal_circles(bgr)


def apply_variant(bgr: np.ndarray, name: str) -> np.ndarray:
    """Pre-specified transforms. ``combo`` was fixed before scoring:

    upscale when the short side is under 1200, then deskew, then remove red
    only inside detected round seals. Denoise and full binarization are
    measured separately and are not part of the combo.
    """
    if name in ("", "none"):
        return bgr
    if name == "deskew":
        return deskew(bgr)[0]
    if name == "denoise":
        return denoise(bgr)
    if name == "binarize":
        return binarize(bgr)
    if name == "upscale":
        return upscale(bgr)[0]
    if name == "red_channel":
        return red_channel(bgr)
    if name == "red_seal":
        return red_seal_only(bgr)
    if name == "combo":
        image, _ = upscale(bgr)
        image, _ = deskew(image)
        return red_seal_only(image)
    raise KeyError(name)
