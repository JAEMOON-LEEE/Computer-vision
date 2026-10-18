"""Project categories; model class IDs are kept separately in exported records."""

TRAFFIC = ("person", "car", "truck", "bus", "motorcycle", "bicycle")
ROAD = ("pothole", "crack", "debris")
STRUCTURES = ("barrier",)
ROAD_MODEL_CLASSES = ROAD + STRUCTURES
CATEGORIES = TRAFFIC + ROAD_MODEL_CLASSES
CATEGORY_IDS = {name: index for index, name in enumerate(CATEGORIES)}


def model_classes(names, allowed=CATEGORIES):
    if isinstance(names, list):
        names = dict(enumerate(names))
    return {int(index): name for index, name in names.items() if name in allowed}
