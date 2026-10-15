"""Rank apparent person size in one RGB view; these scores are not distances."""
import math


def nearest_person(boxes, face_boxes):
    """Face scale first; a body-only person still competes with visible faces.

    Body width/3 and height/7 are explicitly heuristic face-equivalent scales.
    They keep a nearby turned-away or partially cropped person in contention.
    Identity is deliberately absent from selection, so a registered face can
    never win simply because it is registered.
    """
    candidates = []
    for index, person in enumerate(boxes):
        face = face_boxes.get(index)
        if face is not None:
            width, height = face[2:4]
            score = math.sqrt(width * height) if width > 0 and height > 0 else 0
            basis = 'face_size'
        else:
            x0, y0, x1, y1 = person['box']
            width, height = x1 - x0, y1 - y0
            score = max(width / 3.0, height / 7.0) if width > 0 and height > 0 else 0
            basis = 'body_size'
        if math.isfinite(score) and score > 0:
            # If scales are exactly equal, do not hide a person with no face.
            candidates.append((score, face is None, -index, basis))
    if not candidates:
        return {'index': None, 'scale': 0, 'basis': 'none'}
    score, _, negative_index, basis = max(candidates)
    return {'index': -negative_index, 'scale': float(score), 'basis': basis}
