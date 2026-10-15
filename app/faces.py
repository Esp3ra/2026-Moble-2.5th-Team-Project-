"""YuNet/SFace on TensorRT, with the OpenCV model preprocessing conventions."""
import ctypes as C
from pathlib import Path

import cv2
import numpy as np

from .config import ROOT
from .identities import IdentityStore, unit
from .inference import Cuda
from .proximity import nearest_person


class Engine:
    def __init__(self, filename):
        import tensorrt as trt
        self.cuda = Cuda()
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        path = Path(filename)
        self.engine = self.runtime.deserialize_cuda_engine((path if path.is_absolute() else ROOT / path).read_bytes())
        if self.engine is None:
            raise RuntimeError('얼굴 인식 GPU 모델을 읽을 수 없습니다.')
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError('얼굴 인식 GPU 실행 준비에 실패했습니다.')
        self.host, self.pointers, self.names = [], [], {}
        try:
            for i in range(self.engine.num_bindings):
                shape = tuple(self.context.get_binding_shape(i))
                if any(d <= 0 for d in shape):
                    raise RuntimeError('얼굴 모델의 입력 크기를 확인해 주세요.')
                array = np.empty(shape, dtype=trt.nptype(self.engine.get_binding_dtype(i)))
                pointer = C.c_void_p()
                self.cuda.check(self.cuda.lib.cudaMalloc(C.byref(pointer), array.nbytes))
                self.host.append(array)
                self.pointers.append(pointer.value)
                self.names[self.engine.get_binding_name(i)] = i
                if self.engine.binding_is_input(i):
                    self.input_index = i
        except Exception:
            self.close()
            raise

    def run(self, blob):
        target = self.host[self.input_index]
        np.copyto(target, blob.astype(target.dtype, copy=False))
        self.cuda.check(self.cuda.lib.cudaMemcpy(self.pointers[self.input_index], target.ctypes.data, target.nbytes, 1))
        if not self.context.execute_v2(self.pointers):
            raise RuntimeError('얼굴 인식 GPU 실행 오류')
        result = {}
        for name, i in self.names.items():
            if i == self.input_index:
                continue
            array = self.host[i]
            self.cuda.check(self.cuda.lib.cudaMemcpy(array.ctypes.data, self.pointers[i], array.nbytes, 2))
            if not np.isfinite(array).all():
                raise RuntimeError('얼굴 인식 결과가 올바르지 않습니다.')
            result[name] = array.astype(np.float32, copy=True)
        return result

    def close(self):
        for pointer in getattr(self, 'pointers', []):
            self.cuda.lib.cudaFree(pointer)
        self.pointers = []


def align_face(frame, points):
    source = np.asarray(points, dtype=np.float64).reshape(5, 2)
    target = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                       [41.5493, 92.3655], [70.7299, 92.2041]])
    src, dst = source - source.mean(0), target - target.mean(0)
    covariance = dst.T.dot(src) / 5
    u, singular, vt = np.linalg.svd(covariance)
    sign = np.ones(2)
    if np.linalg.det(covariance) < 0:
        sign[-1] = -1
    variance = (src * src).sum() / 5
    if variance < 1e-6 or np.linalg.matrix_rank(covariance) < 2:
        raise ValueError('얼굴을 정면으로 향해 주세요.')
    rotation = u.dot(np.diag(sign)).dot(vt)
    scale = float(singular.dot(sign) / variance)
    transform = np.column_stack((scale * rotation, target.mean(0) - scale * rotation.dot(source.mean(0))))
    return cv2.warpAffine(frame, transform, (112, 112))


class FaceRecognizer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.detector = Engine(cfg['detector_engine'])
        try:
            self.recognizer = Engine(cfg['recognizer_engine'])
            path = Path(cfg['database'])
            self.store = IdentityStore(path if path.is_absolute() else ROOT / path, cfg['threshold'])
        except Exception:
            self.close()
            raise

    def detect(self, frame):
        height, width = frame.shape[:2]
        scale = min(640.0 / width, 640.0 / height)
        image = np.zeros((640, 640, 3), np.uint8)
        resized = cv2.resize(frame, (int(round(width * scale)), int(round(height * scale))))
        image[:resized.shape[0], :resized.shape[1]] = resized
        output = self.detector.run(cv2.dnn.blobFromImage(image))
        boxes, scores, landmarks = [], [], []
        for stride in (8, 16, 32):
            score = np.sqrt(np.clip(output['cls_' + str(stride)].reshape(-1), 0, 1)
                            * np.clip(output['obj_' + str(stride)].reshape(-1), 0, 1))
            bbox = output['bbox_' + str(stride)].reshape(-1, 4)
            kps = output['kps_' + str(stride)].reshape(-1, 5, 2)
            cols = 640 // stride
            for index in np.flatnonzero(score >= 0.85):
                grid = np.array([index % cols, index // cols])
                center = (grid + bbox[index, :2]) * stride / scale
                size = np.exp(np.clip(bbox[index, 2:], -10, 10)) * stride / scale
                left, top = center - size / 2
                if not 0 <= center[0] < width or not 0 <= center[1] < height:
                    continue
                boxes.append([int(left), int(top), int(size[0]), int(size[1])])
                scores.append(float(score[index]))
                landmarks.append((kps[index] + grid) * stride / scale)
        indices = cv2.dnn.NMSBoxes(boxes, scores, 0.85, 0.3) if boxes else []
        return [(boxes[int(i)], landmarks[int(i)]) for i in np.asarray(indices).reshape(-1)]

    def inspect(self, frame, persons, roi):
        self.store.reload()
        faces = self.detect(frame)
        boxes = [dict(p) for p in persons]
        matched_faces, seen = {}, []
        x0, y0, x1, y1 = roi
        for box, landmarks in faces:
            x, y, w, h = box
            cx, cy = x + w / 2, y + h / 2
            if not x0 <= cx < x1 or not y0 <= cy < y1:
                continue
            owners = [i for i, p in enumerate(boxes) if i not in matched_faces
                      and p['box'][0] <= cx <= p['box'][2] and p['box'][1] <= cy <= p['box'][3]]
            if owners:
                index = min(owners, key=lambda i: (boxes[i]['box'][2] - boxes[i]['box'][0]) * (boxes[i]['box'][3] - boxes[i]['box'][1]))
            else:
                index = len(boxes)
                boxes.append({'box': [max(0, x), max(0, y), min(frame.shape[1], x+w), min(frame.shape[0], y+h)], 'confidence': 0.85})
            matched_faces[index] = (box, landmarks)
            seen.append({'box': box, 'person_index': index, 'name': None, 'quality': None, 'selected': False})
        target = nearest_person(boxes, {i: pair[0] for i, pair in matched_faces.items()})
        index = target['index']
        identity, vector, quality = None, None, False
        if index in matched_faces:
            box, landmarks = matched_faces[index]
            x, y, w, h = box
            quality = min(w, h) >= self.cfg['min_face_pixels']
            if quality:
                try:
                    crop = align_face(frame, landmarks)
                    quality = cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() >= 35
                    if quality:
                        vector = unit(self.recognizer.run(cv2.dnn.blobFromImage(crop, 1, (112, 112), swapRB=True))['fc1'].reshape(-1))
                        identity = self.store.match(vector)
                except ValueError:
                    quality = False
        for face in seen:
            if face['person_index'] == index:
                face.update(name=identity['name'] if identity else None, quality=bool(quality), selected=True)
        return {'count': len(boxes), 'boxes': boxes, 'faces': seen,
                'selection': 'nearest', 'target_index': index, 'target_scale': target['scale'],
                'target_basis': target['basis'], 'target_recognized': identity is not None,
                'recognized_ids': [identity['id']] if identity else [],
                'recognized_names': [identity['name']] if identity else [],
                'registered_count': len(self.store.people),
                '_enrollment': vector.tolist() if vector is not None and len(boxes) == 1 and len(seen) == 1 else None}

    def close(self):
        for name in ('detector', 'recognizer'):
            if getattr(self, name, None):
                getattr(self, name).close()
