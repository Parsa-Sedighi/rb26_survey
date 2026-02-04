"""
map.py — Offline satellite-image waypoint editor (PyQt6)

What it does:
- Loads a satellite image from a hardcoded path on startup (no file dialog needed).
- Lets you set 2 calibration points (click pixel -> enter lat/lon).
- Adds exactly 1 waypoint automatically (center) after the image loads.
- Drag the waypoint; it shows live lat/lon for the selected point.
- Optional: load a GPS track CSV (lat,lon) to overlay your run.
- Save/Load waypoints JSON (includes calibration + waypoint pixel/lat/lon).

Install:
  pip install PyQt6

Run:
  python3 map.py
"""

import json
import csv
from dataclasses import dataclass
from typing import Optional, List, Tuple, Callable

from PyQt6.QtCore import Qt, QPointF, QEvent, QRectF
from PyQt6.QtGui import QPixmap, QPen, QBrush, QPainter
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QLineEdit, QMessageBox, QInputDialog
)

# ======= EDIT THIS PATH TO YOUR IMAGE =======
DEFAULT_IMAGE_PATH = "/Users/parsasedighi/Desktop/GitHub/RB26_Map/AbbyWoodCT.png"
# If your image is in the same folder as this script, you can do:
# DEFAULT_IMAGE_PATH = "satellite.png"


@dataclass
class CalPoint:
    px: float
    py: float
    lat: float
    lon: float


class GeoMapper:
    """
    Simple linear pixel <-> lat/lon mapping using TWO calibration points.
    Assumes the image is north-up and the area isn't huge (good enough for "drag-to-correct" workflow).

    lon = lon1 + (px - px1) * (lon2 - lon1) / (px2 - px1)
    lat = lat1 + (py - py1) * (lat2 - lat1) / (py2 - py1)
    """
    def __init__(self):
        self.p1: Optional[CalPoint] = None
        self.p2: Optional[CalPoint] = None

    def is_ready(self) -> bool:
        return (
            self.p1 is not None and self.p2 is not None and
            (self.p2.px != self.p1.px) and (self.p2.py != self.p1.py) and
            (self.p2.lon != self.p1.lon) and (self.p2.lat != self.p1.lat)
        )

    def set_points(self, p1: CalPoint, p2: CalPoint):
        self.p1, self.p2 = p1, p2

    def px_to_ll(self, px: float, py: float) -> Tuple[float, float]:
        if not self.is_ready():
            raise RuntimeError("GeoMapper not calibrated.")
        p1, p2 = self.p1, self.p2

        lon = p1.lon + (px - p1.px) * (p2.lon - p1.lon) / (p2.px - p1.px)
        lat = p1.lat + (py - p1.py) * (p2.lat - p1.lat) / (p2.py - p1.py)
        return lat, lon

    def ll_to_px(self, lat: float, lon: float) -> Tuple[float, float]:
        if not self.is_ready():
            raise RuntimeError("GeoMapper not calibrated.")
        p1, p2 = self.p1, self.p2

        px = p1.px + (lon - p1.lon) * (p2.px - p1.px) / (p2.lon - p1.lon)
        py = p1.py + (lat - p1.lat) * (p2.py - p1.py) / (p2.lat - p1.lat)
        return px, py


class DraggablePoint(QGraphicsEllipseItem):
    def __init__(self, x: float, y: float, r: float, idx: int, on_moved: Callable[[], None]):
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.setPos(QPointF(x, y))
        self.setFlags(
            QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.idx = idx
        self._on_moved = on_moved
        self.setBrush(QBrush(Qt.GlobalColor.red))
        self.setPen(QPen(Qt.GlobalColor.black, 1))

    def itemChange(self, change, value):
        # Update lat/lon live while dragging
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionHasChanged:
            try:
                self._on_moved()
            except Exception:
                pass
        return super().itemChange(change, value)


class MapView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self.setRenderHints(self.renderHints() | QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event):
        # Zoom with wheel
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Offline Waypoint Editor (Image ↔ Lat/Lon)")

        self.scene = QGraphicsScene()
        self.view = MapView(self.scene)

        self.image_item: Optional[QGraphicsPixmapItem] = None
        self.track_item: Optional[QGraphicsPathItem] = None

        self.geomap = GeoMapper()
        self.points: List[DraggablePoint] = []

        # UI
        self.status_lbl = QLabel("Tip: Auto-loads DEFAULT_IMAGE_PATH. Then set Cal P1 and Cal P2.")
        self.selected_lbl = QLabel("Selected: none")

        self.lat_box = QLineEdit()
        self.lon_box = QLineEdit()
        self.lat_box.setReadOnly(True)
        self.lon_box.setReadOnly(True)

        btn_load_img = QPushButton("Load Image (Dialog)")
        btn_set_cal1 = QPushButton("Set Cal P1 (click)")
        btn_set_cal2 = QPushButton("Set Cal P2 (click)")
        btn_add_wp   = QPushButton("Add Waypoint (center)")
        btn_save     = QPushButton("Save Waypoints JSON")
        btn_load     = QPushButton("Load Waypoints JSON")
        btn_loadtrk  = QPushButton("Load Track CSV (lat,lon)")

        btn_load_img.clicked.connect(self.load_image_dialog)
        btn_set_cal1.clicked.connect(lambda: self.set_cal_point(which=1))
        btn_set_cal2.clicked.connect(lambda: self.set_cal_point(which=2))
        btn_add_wp.clicked.connect(self.add_waypoint_center)
        btn_save.clicked.connect(self.save_waypoints)
        btn_load.clicked.connect(self.load_waypoints)
        btn_loadtrk.clicked.connect(self.load_track_csv)

        top = QWidget()
        layout = QVBoxLayout(top)
        layout.addWidget(self.view)

        bar = QHBoxLayout()
        for b in [btn_load_img, btn_set_cal1, btn_set_cal2, btn_add_wp, btn_loadtrk, btn_load, btn_save]:
            bar.addWidget(b)
        layout.addLayout(bar)

        info = QHBoxLayout()
        info.addWidget(self.status_lbl, 3)
        info.addWidget(self.selected_lbl, 2)
        info.addWidget(QLabel("Lat:"))
        info.addWidget(self.lat_box)
        info.addWidget(QLabel("Lon:"))
        info.addWidget(self.lon_box)
        layout.addLayout(info)

        self.setCentralWidget(top)

        # Click-to-pick calibration pixels
        self._cal_pick_mode: Optional[int] = None  # 1 or 2
        self.view.viewport().installEventFilter(self)

        self.scene.selectionChanged.connect(self.update_selected_readout)

        # Auto-load image on startup (no dialog)
        self.load_image_from_path(DEFAULT_IMAGE_PATH)

    # --------- Event filter for calibration picking ----------
    def eventFilter(self, obj, event):
        if obj == self.view.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            if self._cal_pick_mode in (1, 2) and event.button() == Qt.MouseButton.LeftButton:
                pos = self.view.mapToScene(event.pos())
                self.pick_calibration_pixel(pos.x(), pos.y(), which=self._cal_pick_mode)
                self._cal_pick_mode = None
                return True
        return super().eventFilter(obj, event)

    # --------- Image loading ----------
    def load_image_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        self.load_image_from_path(path)

    def load_image_from_path(self, path: str):
        pix = QPixmap(path)
        if pix.isNull():
            self.status_lbl.setText(f"Could not load image from: {path}")
            QMessageBox.warning(self, "Image load failed", f"Could not load image:\n{path}")
            return False

        # Clear scene and reset
        self.scene.clear()
        self.points.clear()
        self.track_item = None
        self.geomap = GeoMapper()  # reset calibration

        self.image_item = QGraphicsPixmapItem(pix)
        self.scene.addItem(self.image_item)
        self.scene.setSceneRect(QRectF(pix.rect()))

        self.status_lbl.setText(f"Image loaded from: {path}\nNow set Cal P1 and Cal P2.")
        self.selected_lbl.setText("Selected: none")
        self.lat_box.setText("")
        self.lon_box.setText("")

        # Add exactly 1 waypoint automatically
        self.add_waypoint_center()
        return True

    # --------- Calibration ----------
    def set_cal_point(self, which: int):
        if self.image_item is None:
            QMessageBox.information(self, "No image", "Load an image first.")
            return
        self._cal_pick_mode = which
        self.status_lbl.setText(f"Click on the image to set calibration point P{which} pixel location…")

    def pick_calibration_pixel(self, px: float, py: float, which: int):
        lat, ok1 = self._prompt_float(f"Enter latitude for P{which} (pixel {px:.1f},{py:.1f})")
        if not ok1:
            self.status_lbl.setText("Calibration canceled.")
            return
        lon, ok2 = self._prompt_float(f"Enter longitude for P{which} (pixel {px:.1f},{py:.1f})")
        if not ok2:
            self.status_lbl.setText("Calibration canceled.")
            return

        cp = CalPoint(px=px, py=py, lat=lat, lon=lon)
        if which == 1:
            self.geomap.p1 = cp
            self.status_lbl.setText("Cal P1 set. Now set Cal P2.")
        else:
            self.geomap.p2 = cp
            self.status_lbl.setText("Cal P2 set. Now set Cal P1.")

        if self.geomap.p1 is not None and self.geomap.p2 is not None:
            # finalize
            self.geomap.set_points(self.geomap.p1, self.geomap.p2)
            if self.geomap.is_ready():
                self.status_lbl.setText("Calibrated! Drag waypoint; lat/lon updates live. (You can load a track CSV too.)")
                self.update_selected_readout()
            else:
                QMessageBox.warning(
                    self,
                    "Calibration invalid",
                    "Calibration points are invalid (need different x/y and different lat/lon).\nTry again with two separated points."
                )
                self.status_lbl.setText("Calibration invalid. Try again.")

    def _prompt_float(self, title: str) -> Tuple[float, bool]:
        text, ok = QInputDialog.getText(self, "Input", title)
        if not ok:
            return 0.0, False
        try:
            return float(text.strip()), True
        except ValueError:
            QMessageBox.warning(self, "Invalid", "Please enter a valid number.")
            return 0.0, False

    # --------- Waypoints ----------
    def add_waypoint_center(self):
        if self.image_item is None:
            QMessageBox.information(self, "No image", "Load an image first.")
            return
        rect = self.scene.sceneRect()
        x = rect.center().x()
        y = rect.center().y()
        idx = len(self.points)

        p = DraggablePoint(x, y, r=6.0, idx=idx, on_moved=self.update_selected_readout)
        self.scene.addItem(p)
        self.points.append(p)

        p.setSelected(True)
        self.update_selected_readout()

    def update_selected_readout(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, DraggablePoint)]
        if not sel:
            self.selected_lbl.setText("Selected: none")
            self.lat_box.setText("")
            self.lon_box.setText("")
            return

        p: DraggablePoint = sel[0]
        self.selected_lbl.setText(f"Selected: WP{p.idx}")

        if self.geomap.is_ready():
            try:
                lat, lon = self.geomap.px_to_ll(p.pos().x(), p.pos().y())
                self.lat_box.setText(f"{lat:.8f}")
                self.lon_box.setText(f"{lon:.8f}")
            except Exception:
                self.lat_box.setText("—")
                self.lon_box.setText("—")
        else:
            self.lat_box.setText("— (set Cal P1/P2)")
            self.lon_box.setText("— (set Cal P1/P2)")

    # --------- Save / Load ----------
    def save_waypoints(self):
        if not self.geomap.is_ready():
            QMessageBox.information(self, "Not calibrated", "Set Cal P1 and Cal P2 first.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Save waypoints", "waypoints.json", "JSON (*.json)")
        if not path:
            return

        data = {
            "calibration": {
                "p1": self.geomap.p1.__dict__,
                "p2": self.geomap.p2.__dict__,
            },
            "waypoints": []
        }

        for p in self.points:
            lat, lon = self.geomap.px_to_ll(p.pos().x(), p.pos().y())
            data["waypoints"].append({
                "id": p.idx,
                "lat": lat,
                "lon": lon,
                "px": p.pos().x(),
                "py": p.pos().y(),
            })

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self.status_lbl.setText(f"Saved {len(self.points)} waypoint(s) to {path}")

    def load_waypoints(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load waypoints", "", "JSON (*.json)")
        if not path:
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cal = data.get("calibration")
        if cal and "p1" in cal and "p2" in cal:
            p1 = CalPoint(**cal["p1"])
            p2 = CalPoint(**cal["p2"])
            self.geomap.set_points(p1, p2)

        # Remove existing points
        for p in self.points:
            self.scene.removeItem(p)
        self.points.clear()

        # Load points
        for wp in data.get("waypoints", []):
            idx = int(wp.get("id", len(self.points)))
            if "px" in wp and "py" in wp:
                x, y = float(wp["px"]), float(wp["py"])
            else:
                if not self.geomap.is_ready():
                    continue
                x, y = self.geomap.ll_to_px(float(wp["lat"]), float(wp["lon"]))

            p = DraggablePoint(x, y, r=6.0, idx=idx, on_moved=self.update_selected_readout)
            self.scene.addItem(p)
            self.points.append(p)

        # Re-index sequentially
        for i, p in enumerate(self.points):
            p.idx = i

        self.status_lbl.setText(f"Loaded {len(self.points)} waypoint(s) from {path}")
        if self.points:
            self.points[0].setSelected(True)
        self.update_selected_readout()

    # --------- Track overlay ----------
    def load_track_csv(self):
        if not self.geomap.is_ready():
            QMessageBox.information(self, "Not calibrated", "Set Cal P1 and Cal P2 first (needed to draw track).")
            return

        path, _ = QFileDialog.getOpenFileName(self, "Load track CSV", "", "CSV (*.csv)")
        if not path:
            return

        pts_ll: List[Tuple[float, float]] = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            QMessageBox.warning(self, "Track", "CSV is empty.")
            return

        # Detect header
        start_idx = 0
        header = [c.strip().lower() for c in rows[0]]
        if any(h in ("lat", "latitude") for h in header) or any(h in ("lon", "lng", "longitude") for h in header):
            start_idx = 1

        for r in rows[start_idx:]:
            if len(r) < 2:
                continue
            try:
                lat = float(r[0])
                lon = float(r[1])
                pts_ll.append((lat, lon))
            except ValueError:
                continue

        if len(pts_ll) < 2:
            QMessageBox.warning(self, "Track", "Not enough valid points found in CSV (need lat,lon columns).")
            return

        from PyQt6.QtGui import QPainterPath
        path_item = QPainterPath()

        x0, y0 = self.geomap.ll_to_px(pts_ll[0][0], pts_ll[0][1])
        path_item.moveTo(x0, y0)

        for lat, lon in pts_ll[1:]:
            x, y = self.geomap.ll_to_px(lat, lon)
            path_item.lineTo(x, y)

        if self.track_item is not None:
            self.scene.removeItem(self.track_item)

        self.track_item = QGraphicsPathItem(path_item)
        self.track_item.setPen(QPen(Qt.GlobalColor.blue, 2))
        self.scene.addItem(self.track_item)

        self.status_lbl.setText(f"Loaded track with {len(pts_ll)} points. Drag waypoint to match your run.")


def main():
    app = QApplication([])
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    app.exec()


if __name__ == "__main__":
    main()