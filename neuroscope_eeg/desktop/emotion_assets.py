from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import random


@dataclass(frozen=True, slots=True)
class EmotionImage:
    image_id: str
    file: str
    fine_category: str
    fine_category_zh: str
    valence: str
    path: Path


EMOTION_CATEGORIES = {
    "amusement": ("愉悦", "positive"),
    "disgust": ("厌恶", "negative"),
    "fear": ("恐惧", "negative"),
    "inspiration": ("鼓舞", "positive"),
    "neutral": ("中性", "neutral"),
    "sadness": ("悲伤", "negative"),
    "tenderness": ("温情", "positive"),
}


def emotion_asset_root() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "emotion_arousal"


def load_emotion_manifest(root: Path | None = None) -> tuple[EmotionImage, ...]:
    asset_root = root or emotion_asset_root()
    manifest_path = asset_root / "manifest.json"
    try:
        raw_entries = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取情绪图片清单：{manifest_path}") from exc
    images = tuple(
        EmotionImage(
            image_id=str(entry["id"]),
            file=str(entry["file"]),
            fine_category=str(entry["fine_category"]),
            fine_category_zh=str(entry["fine_category_zh"]),
            valence=str(entry["valence"]),
            path=asset_root / "images" / str(entry["file"]),
        )
        for entry in raw_entries
    )
    counts = Counter(image.fine_category for image in images)
    if len(images) != 105 or counts != Counter({category: 15 for category in EMOTION_CATEGORIES}):
        raise ValueError("情绪图片清单必须包含七个细分类，每类 15 张，共 105 张")
    if len({image.image_id for image in images}) != len(images) or len({image.file for image in images}) != len(images):
        raise ValueError("情绪图片清单包含重复 ID 或文件名")
    for image in images:
        expected_zh, expected_valence = EMOTION_CATEGORIES.get(image.fine_category, (None, None))
        if (image.fine_category_zh, image.valence) != (expected_zh, expected_valence):
            raise ValueError(f"情绪类别映射错误：{image.file}")
        if not image.path.is_file():
            raise ValueError(f"缺少情绪图片：{image.path}")
    return images


def select_emotion_images(
    images: tuple[EmotionImage, ...],
    *,
    per_category: int,
    seed: int = 17,
) -> tuple[EmotionImage, ...]:
    if per_category <= 0 or per_category > 15:
        raise ValueError("per_category must be between 1 and 15")
    rng = random.Random(seed)
    selected: list[EmotionImage] = []
    for category in EMOTION_CATEGORIES:
        group = [image for image in images if image.fine_category == category]
        selected.extend(rng.sample(group, per_category))
    for _attempt in range(1000):
        rng.shuffle(selected)
        if all(
            len({image.fine_category for image in selected[index : index + 3]}) > 1
            for index in range(len(selected) - 2)
        ):
            return tuple(selected)
    raise RuntimeError("could not arrange emotion images without a three-image category run")
