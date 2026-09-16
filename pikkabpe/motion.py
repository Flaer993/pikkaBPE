import time
import cv2


class Motion:
    """Motion proposals only; moving-camera frames never become stock operations."""
    def __init__(self):
        self.bg = cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=36, detectShadows=False)
        self.settled_after = time.monotonic() + 2
        self.last = 0.0

    def camera_moved(self):
        self.settled_after = time.monotonic() + 1.5
        self.bg = cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=36, detectShadows=False)

    def detect(self, frame):
        small = cv2.resize(frame, (640, 360))
        mask = self.bg.apply(small)
        if time.monotonic() < self.settled_after:
            return None
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in contours if 900 < cv2.contourArea(c) < 640*360*.55]
        if not valid:
            return None
        x, y, w, h = cv2.boundingRect(max(valid, key=cv2.contourArea))
        return (x/640, y/360, w/640, h/360)
