"""Share one GPU between local object detection and local 3D generation."""
import threading

GPU_LOCK = threading.Lock()
