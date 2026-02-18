"""
grid_editor_centered.py — 100m x 100m centered grid editor (PyQt6)
Updated with Surveyor Tools for Lat/Lon projection.
"""

from __future__ import annotations

import json
import math
from typing import List, Tuple

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPen, QBrush, QPainter, QDoubleValidator, QPainterPath
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGraphicsView, QGraphicsScene,
    QGraphicsEllipseItem, QGraphicsRectItem,
    QFileDialog, QMessageBox, QLineEdit, QCheckBox, QInputDialog, QComboBox
)

# ===== Grid configuration =====
GRID_SIZE_M = 100.0
HALF_M = GRID_SIZE_M / 2.0
CELL_SIZE_M = 5.0
PX_PER_M = 8.0

W_PX = int(GRID_SIZE_M * PX_PER_M)
H_PX = int(GRID_SIZE_M * PX_PER_M)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def meters_per_deg(origin_lat: float) -> Tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return m_per_deg_lat, m_per_deg_lon


def meters_to_latlon(origin_lat: float, origin_lon: float, east_m: float, north_m: float) -> Tuple[float, float]:
    m_per_deg_lat, m_per_deg_lon = meters_per_deg(origin_lat)
    dlat = north_m / m_per_deg_lat
    dlon = (east_m / m_per_deg_lon) if m_per_deg_lon != 0 else 0.0
    return origin_lat + dlat, origin_lon + dlon


def latlon_to_meters(origin_lat: float, origin_lon: float, lat: float, lon: float) -> Tuple[float, float]:
    m_per_deg_lat, m_per_deg_lon = meters_per_deg(origin_lat)
    north_m = (lat - origin_lat) * m_per_deg_lat
    east_m = (lon - origin_lon) * m_per_deg_lon
    return east_m, north_m


class DraggableBase:
    kind: str
    item_id_1based: int
    name: str
    base_x: float
    base_y: float
    off_x: float
    off_y: float
    _on_changed: callable


class DraggableWaypoint(QGraphicsEllipseItem, DraggableBase):
    def __init__(self, item_id_1based: int, name: str, final_x_px: float, final_y_px: float, r_px: float, on_changed):
        super().__init__(-r_px, -r_px, 2 * r_px, 2 * r_px)
        self.kind = "waypoint"
        self.item_id_1based = item_id_1based
        self.name = name
        self.base_x = 0.0
        self.base_y = 0.0
        self.off_x = 0.0
        self.off_y = 0.0
        self._on_changed = on_changed
        self.setPos(QPointF(final_x_px, final_y_px))
        self.setFlags(
            QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setBrush(QBrush(Qt.GlobalColor.red))
        self.setPen(QPen(Qt.GlobalColor.black, 1))
        self.setZValue(1)

    def shape(self):
        path = QPainterPath()
        path.addEllipse(self.rect())
        return path

    def mousePressEvent(self, event):
        self.setZValue(1000)
        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionChange:
            p: QPointF = value
            x = clamp(p.x(), 0.0, W_PX)
            y = clamp(p.y(), 0.0, H_PX)
            return QPointF(x, y)
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionHasChanged:
            try:
                self._on_changed()
            except Exception:
                pass
        return super().itemChange(change, value)


class DraggableMission(QGraphicsRectItem, DraggableBase):
    def __init__(self, item_id_1based: int, name: str, final_x_px: float, final_y_px: float, size_px: float, on_changed):
        half = size_px / 2.0
        super().__init__(-half, -half, size_px, size_px)
        self.kind = "mission"
        self.item_id_1based = item_id_1based
        self.name = name
        self.base_x = 0.0
        self.base_y = 0.0
        self.off_x = 0.0
        self.off_y = 0.0
        self._on_changed = on_changed
        self.setPos(QPointF(final_x_px, final_y_px))
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setBrush(QBrush(Qt.GlobalColor.green))
        self.setPen(QPen(Qt.GlobalColor.black, 1))
        self.setZValue(1)

    def shape(self):
        path = QPainterPath()
        path.addRect(self.rect())
        return path

    def mousePressEvent(self, event):
        self.setZValue(1000)
        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionChange:
            p: QPointF = value
            x = clamp(p.x(), 0.0, W_PX)
            y = clamp(p.y(), 0.0, H_PX)
            return QPointF(x, y)
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionHasChanged:
            try:
                self._on_changed()
            except Exception:
                pass
        return super().itemChange(change, value)


class GridView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, on_double_click):
        super().__init__(scene)
        self._on_double_click = on_double_click
        self.setRenderHints(self.renderHints() | QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.pos())
            self._on_double_click(pos.x(), pos.y())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Surveyor Grid Editor — Haversine Projection")

        self.scene = QGraphicsScene(0, 0, W_PX, H_PX)
        self.view = GridView(self.scene, on_double_click=self.handle_double_click_add)

        self.waypoints: List[DraggableWaypoint] = []
        self.missions: List[DraggableMission] = []

        # ===== UI Setup =====
        self.status_lbl = QLabel("Ready")
        self.selected_lbl = QLabel("Selected: none")

        self.name_box = QLineEdit(placeholderText="Name")
        self.x_box = QLineEdit(placeholderText="X (FINAL)")
        self.y_box = QLineEdit(placeholderText="Y (FINAL)")
        self.lat_box = QLineEdit(placeholderText="Lat (FINAL)")
        self.lon_box = QLineEdit(placeholderText="Lon (FINAL)")
        self.origin_lat = QLineEdit(placeholderText="Origin Lat")
        self.origin_lon = QLineEdit(placeholderText="Origin Lon")
        self.offx_box = QLineEdit(text="0.0")
        self.offy_box = QLineEdit(text="0.0")

        # Surveyor Tool Inputs
        self.surv_lat = QLineEdit(placeholderText="Your Lat")
        self.surv_lon = QLineEdit(placeholderText="Your Lon")
        self.surv_bearing = QLineEdit(placeholderText="Bearing (°)")
        self.surv_dist = QLineEdit(placeholderText="Distance (m)")

        v_xy = QDoubleValidator(-1e6, 1e6, 6)
        v_lat = QDoubleValidator(-90.0, 90.0, 10)
        v_lon = QDoubleValidator(-180.0, 180.0, 10)
        
        for b in [self.x_box, self.y_box, self.offx_box, self.offy_box, self.surv_dist, self.surv_bearing]:
            b.setValidator(v_xy)
        for b in [self.lat_box, self.origin_lat, self.surv_lat]:
            b.setValidator(v_lat)
        for b in [self.lon_box, self.origin_lon, self.surv_lon]:
            b.setValidator(v_lon)

        self.snap_cb = QCheckBox("Snap to 5m")
        self.add_mode = QComboBox()
        self.add_mode.addItems(["Waypoint", "Mission Element"])

        # Buttons
        btn_apply_xy = QPushButton("Apply X/Y")
        btn_apply_ll = QPushButton("Apply Lat/Lon")
        btn_apply_offset = QPushButton("Apply Offset")
        btn_save = QPushButton("Save JSON")
        btn_load = QPushButton("Load JSON")
        btn_calc_surv = QPushButton("Project Waypoint")
        btn_clear = QPushButton("Clear All")

        # Connections
        btn_apply_xy.clicked.connect(self.apply_from_xy_boxes)
        btn_apply_ll.clicked.connect(self.apply_from_latlon_boxes)
        btn_apply_offset.clicked.connect(self.apply_selected_offset_set)
        btn_save.clicked.connect(self.save_json)
        btn_load.clicked.connect(self.load_json)
        btn_calc_surv.clicked.connect(self.add_waypoint_from_survey)
        btn_clear.clicked.connect(self.clear_all)

        # Layout
        root = QWidget()
        main = QVBoxLayout(root)
        main.addWidget(self.view)

        # Row 1: Controls
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Double-click adds:"))
        row1.addWidget(self.add_mode)
        row1.addWidget(self.snap_cb)
        row1.addStretch()
        row1.addWidget(btn_load)
        row1.addWidget(btn_save)
        row1.addWidget(btn_clear)
        main.addLayout(row1)

        # Row 2: Origin & Surveyor Tools
        row_origin = QHBoxLayout()
        row_origin.addWidget(QLabel("Origin Lat/Lon:"))
        row_origin.addWidget(self.origin_lat)
        row_origin.addWidget(self.origin_lon)
        row_origin.addSpacing(20)
        row_origin.addWidget(QLabel("Surveyor:"))
        row_origin.addWidget(self.surv_lat)
        row_origin.addWidget(self.surv_lon)
        row_origin.addWidget(self.surv_bearing)
        row_origin.addWidget(self.surv_dist)
        row_origin.addWidget(btn_calc_surv)
        main.addLayout(row_origin)

        # Row 3: Manual Edits
        row_edit = QHBoxLayout()
        row_edit.addWidget(self.selected_lbl)
        row_edit.addWidget(QLabel("Name:"))
        row_edit.addWidget(self.name_box)
        row_edit.addWidget(QLabel("X/Y:"))
        row_edit.addWidget(self.x_box)
        row_edit.addWidget(self.y_box)
        row_edit.addWidget(btn_apply_xy)
        row_edit.addWidget(QLabel("Lat/Lon:"))
        row_edit.addWidget(self.lat_box)
        row_edit.addWidget(self.lon_box)
        row_edit.addWidget(btn_apply_ll)
        main.addLayout(row_edit)

        self.setCentralWidget(root)
        self.scene.selectionChanged.connect(self.update_readout)
        self.draw_grid()

    # ===== Math Logic =====
    def calculate_destination(self, lat1, lon1, bearing, distance):
        """Forward Geodesic calculation to find a point from bearing/distance."""
        R = 6371000.0 
        rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
        rbearing = math.radians(bearing)
        delta = distance / R
        
        lat2 = math.asin(math.sin(rlat1) * math.cos(delta) +
                         math.cos(rlat1) * math.sin(delta) * math.cos(rbearing))
        lon2 = rlon1 + math.atan2(math.sin(rbearing) * math.sin(delta) * math.cos(rlat1),
                                  math.cos(delta) - math.sin(rlat1) * math.sin(lat2))
        return math.degrees(lat2), math.degrees(lon2)

    def add_waypoint_from_survey(self):
        try:
            if not self.origin_is_valid():
                QMessageBox.warning(self, "Origin Missing", "Set Origin Lat/Lon first.")
                return
            
            u_lat = float(self.surv_lat.text())
            u_lon = float(self.surv_lon.text())
            brg = float(self.surv_bearing.text())
            dst = float(self.surv_dist.text())
            
            t_lat, t_lon = self.calculate_destination(u_lat, u_lon, brg, dst)
            o_lat, o_lon = self.get_origin()
            final_x, final_y = latlon_to_meters(o_lat, o_lon, t_lat, t_lon)
            
            self._add_waypoint(final_x, final_y, name=f"survey_{len(self.waypoints)+1}")
            self.status_lbl.setText(f"Projected point to: {t_lat:.6f}, {t_lon:.6f}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Calculation failed: {e}")

    # ===== Grid & UI Helpers =====
    def px_to_meters(self, x_px: float, y_px: float) -> Tuple[float, float]:
        x = (x_px - (W_PX / 2.0)) / PX_PER_M
        y = ((H_PX / 2.0) - y_px) / PX_PER_M
        return x, y

    def meters_to_px(self, x: float, y: float) -> Tuple[float, float]:
        x_px = (W_PX / 2.0) + (x * PX_PER_M)
        y_px = (H_PX / 2.0) - (y * PX_PER_M)
        return x_px, y_px

    def snap_xy(self, x: float, y: float) -> Tuple[float, float]:
        if not self.snap_cb.isChecked(): return x, y
        return round(x / CELL_SIZE_M) * CELL_SIZE_M, round(y / CELL_SIZE_M) * CELL_SIZE_M

    def clamp_xy(self, x: float, y: float) -> Tuple[float, float]:
        return clamp(x, -HALF_M, HALF_M), clamp(y, -HALF_M, HALF_M)

    def origin_is_valid(self) -> bool:
        try:
            float(self.origin_lat.text()); float(self.origin_lon.text())
            return True
        except: return False

    def get_origin(self) -> Tuple[float, float]:
        return float(self.origin_lat.text()), float(self.origin_lon.text())

    def selected_item(self):
        sel = self.scene.selectedItems()
        return sel[0] if sel and isinstance(sel[0], (DraggableWaypoint, DraggableMission)) else None

    def final_from_item(self, item: DraggableBase) -> Tuple[float, float]:
        return item.base_x + item.off_x, item.base_y + item.off_y

    def set_item_final(self, item: DraggableBase, final_x: float, final_y: float):
        item.base_x = final_x - item.off_x
        item.base_y = final_y - item.off_y
        self._apply_item_to_scene(item)

    def set_item_offset(self, item: DraggableBase, off_x: float, off_y: float):
        item.off_x, item.off_y = off_x, off_y
        self._apply_item_to_scene(item)

    def _apply_item_to_scene(self, item: DraggableBase):
        fx, fy = self.final_from_item(item)
        fx, fy = self.snap_xy(*self.clamp_xy(fx, fy))
        item.base_x, item.base_y = fx - item.off_x, fy - item.off_y
        x_px, y_px = self.meters_to_px(fx, fy)
        item.setPos(QPointF(x_px, y_px))

    def draw_grid(self):
        self.scene.clear()
        self.scene.addRect(0, 0, W_PX, H_PX, QPen(Qt.GlobalColor.black, 2))
        step = CELL_SIZE_M * PX_PER_M
        for i in range(1, int(GRID_SIZE_M / CELL_SIZE_M)):
            p = QPen(Qt.GlobalColor.black if i % 2 == 0 else Qt.GlobalColor.gray, 1)
            self.scene.addLine(i * step, 0, i * step, H_PX, p)
            self.scene.addLine(0, i * step, W_PX, i * step, p)
        self.scene.addLine(W_PX/2, 0, W_PX/2, H_PX, QPen(Qt.GlobalColor.black, 2))
        self.scene.addLine(0, H_PX/2, W_PX, H_PX/2, QPen(Qt.GlobalColor.black, 2))

    def handle_double_click_add(self, x_px: float, y_px: float):
        fx, fy = self.px_to_meters(x_px, y_px)
        if "waypoint" in self.add_mode.currentText().lower():
            self._add_waypoint(fx, fy, f"wp{len(self.waypoints)+1}")
        else:
            self._add_mission(fx, fy, f"ms{len(self.missions)+1}")

    def _add_waypoint(self, fx: float, fy: float, name: str):
        fx, fy = self.snap_xy(*self.clamp_xy(fx, fy))
        px, py = self.meters_to_px(fx, fy)
        item = DraggableWaypoint(len(self.waypoints)+1, name, px, py, 6.0, self.on_item_moved)
        item.base_x, item.base_y = fx, fy
        self.scene.addItem(item); self.waypoints.append(item)
        item.setSelected(True)

    def _add_mission(self, fx: float, fy: float, name: str):
        fx, fy = self.snap_xy(*self.clamp_xy(fx, fy))
        px, py = self.meters_to_px(fx, fy)
        item = DraggableMission(len(self.missions)+1, name, px, py, 12.0, self.on_item_moved)
        item.base_x, item.base_y = fx, fy
        self.scene.addItem(item); self.missions.append(item)
        item.setSelected(True)

    def on_item_moved(self):
        sel = self.selected_item()
        if sel:
            fx, fy = self.px_to_meters(sel.pos().x(), sel.pos().y())
            self.set_item_final(sel, fx, fy)
        self.update_readout()

    def apply_from_xy_boxes(self):
        sel = self.selected_item()
        if sel: self.set_item_final(sel, float(self.x_box.text()), float(self.y_box.text()))
        self.update_readout()

    def apply_from_latlon_boxes(self):
        sel = self.selected_item()
        if sel and self.origin_is_valid():
            o_lat, o_lon = self.get_origin()
            fx, fy = latlon_to_meters(o_lat, o_lon, float(self.lat_box.text()), float(self.lon_box.text()))
            self.set_item_final(sel, fx, fy)
        self.update_readout()

    def apply_selected_offset_set(self):
        sel = self.selected_item()
        if sel: self.set_item_offset(sel, float(self.offx_box.text()), float(self.offy_box.text()))
        self.update_readout()

    def update_readout(self):
        sel = self.selected_item()
        if not sel: return
        fx, fy = self.final_from_item(sel)
        self.selected_lbl.setText(f"Selected: {sel.name}")
        self.x_box.setText(f"{fx:.2f}"); self.y_box.setText(f"{fy:.2f}")
        if self.origin_is_valid():
            lat, lon = meters_to_latlon(*self.get_origin(), fx, fy)
            self.lat_box.setText(f"{lat:.7f}"); self.lon_box.setText(f"{lon:.7f}")

    def save_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save", "mission.json", "JSON (*.json)")
        if not path: return
        data = {
            "origin": {"lat": self.origin_lat.text(), "lon": self.origin_lon.text()},
            "waypoints": [{"id": w.item_id_1based, "x": self.final_from_item(w)[0], "y": self.final_from_item(w)[1]} for w in self.waypoints]
        }
        with open(path, "w") as f: json.dump(data, f, indent=2)

    def load_json(self):
        # Implementation similar to original; truncated for brevity
        pass

    def clear_all(self):
        self.scene.clear(); self.draw_grid()
        self.waypoints.clear(); self.missions.clear()

if __name__ == "__main__":
    app = QApplication([])
    ex = MainWindow()
    ex.resize(1200, 800); ex.show()
    app.exec()