"""Shared lock for local vision inference on constrained machines."""
from threading import Lock

LOCAL_INFERENCE_LOCK = Lock()