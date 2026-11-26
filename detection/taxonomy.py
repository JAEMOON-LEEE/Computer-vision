"""Project categories; model class IDs are kept separately in exported records."""

TRAFFIC = ("person", "car", "truck", "bus", "motorcycle", "bicycle")
ROAD = ("pothole", "crack", "debris")
STRUCTURES = ("barrier",)
ROAD_MODEL_CLASSES = ROAD + STRUCTURES
# Append new classes to preserve all existing category IDs.
DELINEATOR_STATES = ("delineator_normal", "delineator_broken", "delineator_fallen")
FACILITY_STATES = ("manhole_normal", "manhole_abnormal", "guardrail_normal", "guardrail_abnormal")
CATEGORIES = TRAFFIC + ROAD_MODEL_CLASSES + DELINEATOR_STATES + FACILITY_STATES
CATEGORY_IDS = {name: index for index, name in enumerate(CATEGORIES)}


def model_classes(names, allowed=CATEGORIES):
    if isinstance(names, list):
        names = dict(enumerate(names))
    return {int(index): name for index, name in names.items() if name in allowed}
