"""Crop storage. NON-NEGOTIABLE #2: only the derived 224x224 JPEG crop is
ever written to disk -- raw uploaded enrollment photos and raw camera frames
are held in memory for the duration of one request and discarded, never
persisted."""
from __future__ import annotations

import base64
import uuid
from pathlib import Path

import cv2
import numpy as np

from app.config import get_settings

settings = get_settings()


def _crop_with_padding(image: np.ndarray, box: tuple[float, float, float, float], padding: float = 0.25) -> np.ndarray:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    x1 -= bw * padding
    x2 += bw * padding
    y1 -= bh * padding
    y2 += bh * padding
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(w, int(x2)), min(h, int(y2))
    if x2 <= x1 or y2 <= y1:
        return image
    return image[y1:y2, x1:x2]


def save_face_crop(image: np.ndarray, box: tuple[float, float, float, float], subdir: str) -> str:
    """Crops with padding, resizes to `settings.crop_max_dim` square, saves as
    JPEG q85, and returns the path RELATIVE to media_root (what gets stored
    in the DB)."""
    crop = _crop_with_padding(image, box)
    dim = settings.crop_max_dim
    resized = cv2.resize(crop, (dim, dim))
    rel_dir = Path(subdir)
    (settings.media_root_path / rel_dir).mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.jpg"
    rel_path = rel_dir / filename
    cv2.imwrite(str(settings.media_root_path / rel_path), resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return str(rel_path)


def save_base64_jpeg(b64_data: str, subdir: str) -> str:
    """The kiosk already crops+encodes the best-shot to a 224x224 JPEG before
    posting it (it never sends a raw frame), so this just persists the bytes
    -- no further cropping/resizing needed server-side."""
    raw = base64.b64decode(b64_data)
    rel_dir = Path(subdir)
    (settings.media_root_path / rel_dir).mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.jpg"
    rel_path = rel_dir / filename
    with open(settings.media_root_path / rel_path, "wb") as fh:
        fh.write(raw)
    return str(rel_path)


def absolute_path(rel_path: str) -> Path:
    return settings.media_root_path / rel_path
