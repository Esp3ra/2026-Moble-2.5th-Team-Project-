"""TensorRT 8.2 / CUDA 10.2 inference on Nano; no PyCUDA/pip CUDA dependency."""
import ctypes as C
from pathlib import Path
import time

import cv2
import numpy as np

from .config import ROOT


class Cuda:
    def __init__(self):
        self.lib = C.CDLL('/usr/local/cuda/lib64/libcudart.so')
        self.lib.cudaMalloc.argtypes = [C.POINTER(C.c_void_p), C.c_size_t]
        self.lib.cudaMalloc.restype = C.c_int
        self.lib.cudaFree.argtypes = [C.c_void_p]
        self.lib.cudaFree.restype = C.c_int
        self.lib.cudaMemcpy.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_int]
        self.lib.cudaMemcpy.restype = C.c_int
        self.lib.cudaGetErrorString.argtypes = [C.c_int]
        self.lib.cudaGetErrorString.restype = C.c_char_p

    def check(self, result):
        if result:
            raise RuntimeError('CUDA: ' + self.lib.cudaGetErrorString(result).decode())


class PersonDetector:
    def __init__(self, cfg):
        import tensorrt as trt
        self.trt = trt
        self.cfg = cfg
        self.cuda = Cuda()
        self.logger = trt.Logger(trt.Logger.WARNING)
        trt.init_libnvinfer_plugins(self.logger, '')
        path = Path(cfg['engine'])
        if not path.is_absolute():
            path = ROOT / path
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(path.read_bytes())
        if self.engine is None:
            raise RuntimeError('Engine incompatible: rebuild it on this Jetson')
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError('Unable to allocate TensorRT execution context')
        self.buffers, self.pointers = [], []
        self.input_index = None
        try:
            for i in range(self.engine.num_bindings):
                if self.engine.binding_is_input(i):
                    self.context.set_binding_shape(i, (1, 3, cfg['input_size'], cfg['input_size']))
            for i in range(self.engine.num_bindings):
                shape = tuple(self.context.get_binding_shape(i))
                if any(n <= 0 for n in shape):
                    raise RuntimeError('Only static-shape engines are supported')
                host = np.empty(shape, dtype=trt.nptype(self.engine.get_binding_dtype(i)))
                pointer = C.c_void_p()
                self.cuda.check(self.cuda.lib.cudaMalloc(C.byref(pointer), host.nbytes))
                self.buffers.append(host)
                self.pointers.append(pointer.value)
                if self.engine.binding_is_input(i):
                    self.input_index = i
            # v6.0 exports three raw heads as well as decoded predictions. The
            # first output is NOT the detection tensor; use its explicit name.
            self.output_index = self.engine.get_binding_index('output')
            if self.input_index is None or self.output_index < 0:
                raise RuntimeError('Unexpected YOLO bindings')
            if self.buffers[self.input_index].shape != (1, 3, cfg['input_size'], cfg['input_size']):
                raise RuntimeError('Unexpected YOLOv5n input shape')
            if self.buffers[self.output_index].ndim != 3 or self.buffers[self.output_index].shape[-1] != 85:
                raise RuntimeError('Unexpected decoded YOLO detection shape')
        except Exception:
            self.close()
            raise

    def inspect(self, frame):
        started = time.monotonic()
        height, width = frame.shape[:2]
        x, y, w, h = self.cfg['roi']
        x0, y0 = int(x * width), int(y * height)
        x1, y1 = min(width, int((x + w) * width)), min(height, int((y + h) * height))
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            raise ValueError('Empty detection ROI')
        size = self.cfg['input_size']
        scale = min(float(size) / crop.shape[1], float(size) / crop.shape[0])
        nw, nh = int(round(crop.shape[1] * scale)), int(round(crop.shape[0] * scale))
        pad_x, pad_y = (size - nw) // 2, (size - nh) // 2
        padded = np.full((size, size, 3), 114, dtype=np.uint8)
        padded[pad_y:pad_y + nh, pad_x:pad_x + nw] = cv2.resize(crop, (nw, nh))
        blob = cv2.dnn.blobFromImage(padded, 1.0 / 255, (size, size), swapRB=True)
        host = self.buffers[self.input_index]
        np.copyto(host.reshape(-1), blob.reshape(-1).astype(host.dtype, copy=False))
        self.cuda.check(self.cuda.lib.cudaMemcpy(self.pointers[self.input_index], host.ctypes.data, host.nbytes, 1))
        if self.engine.has_implicit_batch_dimension:
            ok = self.context.execute(1, self.pointers)
        else:
            ok = self.context.execute_v2(self.pointers)
        if not ok:
            raise RuntimeError('TensorRT execution failed')
        output = self.buffers[self.output_index]
        self.cuda.check(self.cuda.lib.cudaMemcpy(output.ctypes.data, self.pointers[self.output_index], output.nbytes, 2))
        if not np.isfinite(output).all():
            raise RuntimeError('GPU produced non-finite detections; observation is invalid')
        boxes = decode_yolo(output, self.cfg['confidence'], scale, pad_x, pad_y, (x0, y0, x1, y1))
        return {'count': len(boxes), 'boxes': boxes, 'backend': 'TensorRT GPU FP16',
                'inference_ms': (time.monotonic() - started) * 1000, 'box': (x0, y0, x1, y1)}

    def close(self):
        for pointer in getattr(self, 'pointers', []):
            self.cuda.lib.cudaFree(pointer)
        self.pointers = []


def decode_yolo(output, threshold, scale, pad_x, pad_y, roi):
    """COCO person is class 0. Use objectness * class score, then NMS."""
    rows = output.reshape(-1, 85)
    scores = rows[:, 4] * rows[:, 5]
    mask = (scores >= threshold) & np.isfinite(rows).all(axis=1) & (np.argmax(rows[:, 5:], axis=1) == 0)
    candidates = rows[mask]
    scores = scores[mask]
    x0, y0, x1, y1 = roi
    rectangles, confidences = [], []
    for row, score in zip(candidates, scores):
        cx, cy, width, height = row[:4]
        left = max(x0, min(x1, x0 + int((cx - width / 2 - pad_x) / scale)))
        top = max(y0, min(y1, y0 + int((cy - height / 2 - pad_y) / scale)))
        right = max(x0, min(x1, x0 + int((cx + width / 2 - pad_x) / scale)))
        bottom = max(y0, min(y1, y0 + int((cy + height / 2 - pad_y) / scale)))
        if right > left and bottom > top:
            rectangles.append([left, top, right - left, bottom - top])
            confidences.append(float(score))
    indices = cv2.dnn.NMSBoxes(rectangles, confidences, threshold, 0.45) if rectangles else []
    boxes = []
    for index in np.asarray(indices).reshape(-1):
        left, top, width, height = rectangles[int(index)]
        boxes.append({'box': [left, top, left + width, top + height], 'confidence': confidences[int(index)]})
    return boxes
