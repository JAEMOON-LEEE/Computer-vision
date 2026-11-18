from detection.taxonomy import CATEGORY_IDS, DELINEATOR_STATES, FACILITY_STATES, ROAD_MODEL_CLASSES, model_classes


def test_delineator_classes_preserve_existing_category_ids():
    assert CATEGORY_IDS['person'] == 0
    assert CATEGORY_IDS['pothole'] == 6
    assert CATEGORY_IDS['barrier'] == 9
    assert [CATEGORY_IDS[name] for name in DELINEATOR_STATES] == [10, 11, 12]
    assert [CATEGORY_IDS[name] for name in FACILITY_STATES] == [13, 14, 15, 16]
    assert not set(DELINEATOR_STATES) & set(ROAD_MODEL_CLASSES)


def test_delineator_detector_names_are_recognized_without_changing_model_ids():
    assert model_classes({0: 'delineator_normal', 1: 'delineator_broken', 2: 'delineator_fallen'}) == {
        0: 'delineator_normal', 1: 'delineator_broken', 2: 'delineator_fallen'
    }
