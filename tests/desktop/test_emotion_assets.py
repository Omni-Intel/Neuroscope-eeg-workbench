from neuroscope_eeg.desktop.emotion_assets import (
    EMOTION_CATEGORIES,
    load_emotion_manifest,
    select_emotion_images,
)


def test_bundled_emotion_manifest_contains_seven_categories_of_fifteen() -> None:
    images = load_emotion_manifest()
    assert len(images) == 105
    assert {image.fine_category for image in images} == set(EMOTION_CATEGORIES)
    assert all(sum(image.fine_category == category for image in images) == 15 for category in EMOTION_CATEGORIES)
    assert all(image.path.is_file() for image in images)


def test_quick_emotion_selection_uses_three_per_category_without_long_runs() -> None:
    images = load_emotion_manifest()
    selected = select_emotion_images(images, per_category=3, seed=17)
    assert len(selected) == 21
    assert all(sum(image.fine_category == category for image in selected) == 3 for category in EMOTION_CATEGORIES)
    assert all(
        len({image.fine_category for image in selected[index : index + 3]}) > 1
        for index in range(len(selected) - 2)
    )
    assert selected == select_emotion_images(images, per_category=3, seed=17)


def test_full_emotion_selection_uses_all_fifteen_per_category() -> None:
    images = load_emotion_manifest()
    selected = select_emotion_images(images, per_category=15, seed=17)
    assert len(selected) == 105
    assert all(sum(image.fine_category == category for image in selected) == 15 for category in EMOTION_CATEGORIES)
    assert all(
        len({image.fine_category for image in selected[index : index + 3]}) > 1
        for index in range(len(selected) - 2)
    )
    for start in (0, 35, 70):
        block = selected[start : start + 35]
        assert all(sum(image.fine_category == category for image in block) == 5 for category in EMOTION_CATEGORIES)
