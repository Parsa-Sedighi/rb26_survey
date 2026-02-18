"""
grid_editor_centered.py — 100m x 100m centered grid editor (PyQt6)

Key behavior (per-item offsets):
- Each item has BASE (bx, by) and OFFSET (ox, oy)
- FINAL position used for display + lat/lon + drawing is:
      x = bx + ox
      y = by + oy

What you do:
- Select an item
- Set Offset X / Offset Y
- Click "Apply Offset (selected)"
=> Only that item updates on the board + X/Y + Lat/Lon.

Dragging / typing X/Y / typing Lat/Lon sets the FINAL position.
The editor preserves the offset by adjusting the BASE accordingly.

JSON format (keeps your requested keys):
"waypoints": [
  { "id": 1, "name": "start", "x": 3.2, "y": -2.0, "offset": {"x": 0.1, "y": -0.2} }
]

Install:
  pip install PyQt6

Run:
  python3 grid_editor_centered.py
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
    # Small-area approximation
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

    # BASE coords (meters)
    base_x: float
    base_y: float

    # OFFSET coords (meters) — user correction per item
    off_x: float
    off_y: float

    _on_changed: callable


class DraggableWaypoint(QGraphicsEllipseItem, DraggableBase):
    def __init__(self, item_id_1based: int, name: str, final_x_px: float, final_y_px: float, r_px: float, on_changed):
        super().__init__(-r_px, -r_px, 2 * r_px, 2 * r_px)
        self.kind = "waypoint"
        self.item_id_1based = item_id_1based
        self.name = name

        # Start with base = final, offset = 0
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

    # Precise hit-test so nearby items don't get grabbed
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
        self.setWindowTitle("Centered Grid Editor — Per-Item Offsets (Base + Offset = Final)")

        self.scene = QGraphicsScene(0, 0, W_PX, H_PX)
        self.view = GridView(self.scene, on_double_click=self.handle_double_click_add)

        self.waypoints: List[DraggableWaypoint] = []
        self.missions: List[DraggableMission] = []

        # ===== UI =====
        self.status_lbl = QLabel("Select an item and edit Offset X/Y to correct ONLY that item.")
        self.selected_lbl = QLabel("Selected: none")

        self.name_box = QLineEdit()
        self.name_box.setPlaceholderText("Name (e.g., start, gate1, dock)")

        # These show FINAL (base+offset)
        self.x_box = QLineEdit()
        self.y_box = QLineEdit()
        self.x_box.setPlaceholderText("X / East (m) (FINAL)")
        self.y_box.setPlaceholderText("Y / North (m) (FINAL)")

        self.lat_box = QLineEdit()
        self.lon_box = QLineEdit()
        self.lat_box.setPlaceholderText("Latitude (deg) (FINAL)")
        self.lon_box.setPlaceholderText("Longitude (deg) (FINAL)")

        self.origin_lat = QLineEdit()
        self.origin_lon = QLineEdit()
        self.origin_lat.setPlaceholderText("Origin lat (at center 0,0)")
        self.origin_lon.setPlaceholderText("Origin lon (at center 0,0)")

        # Per-item offsets (persistent)
        self.offx_box = QLineEdit()
        self.offy_box = QLineEdit()
        self.offx_box.setPlaceholderText("Offset X (m) (per item)")
        self.offy_box.setPlaceholderText("Offset Y (m) (per item)")
        self.offx_box.setText("0.0")
        self.offy_box.setText("0.0")

        v_xy = QDoubleValidator(-1e6, 1e6, 6)
        v_lat = QDoubleValidator(-90.0, 90.0, 10)
        v_lon = QDoubleValidator(-180.0, 180.0, 10)
        self.x_box.setValidator(v_xy)
        self.y_box.setValidator(v_xy)
        self.offx_box.setValidator(v_xy)
        self.offy_box.setValidator(v_xy)
        self.lat_box.setValidator(v_lat)
        self.lon_box.setValidator(v_lon)

        self.snap_cb = QCheckBox("Snap to 5m grid")
        self.snap_cb.setChecked(False)

        self.add_mode = QComboBox()
        self.add_mode.addItems(["Waypoint", "Mission Element"])

        btn_add_wp = QPushButton("Add Waypoint (center)")
        btn_add_ms = QPushButton("Add Mission (center)")
        btn_apply_name = QPushButton("Apply Name")
        btn_apply_xy = QPushButton("Apply X/Y (final)")
        btn_apply_ll = QPushButton("Apply Lat/Lon (final)")
        btn_apply_offset = QPushButton("Apply Offset (selected)")
        btn_clear = QPushButton("Clear All")
        btn_save = QPushButton("Save JSON")
        btn_load = QPushButton("Load JSON")
        btn_set_origin = QPushButton("Set Origin (prompt)")

        btn_add_wp.clicked.connect(self.add_waypoint_center)
        btn_add_ms.clicked.connect(self.add_mission_center)
        btn_apply_name.clicked.connect(self.apply_name)
        btn_apply_xy.clicked.connect(self.apply_from_xy_boxes)
        btn_apply_ll.clicked.connect(self.apply_from_latlon_boxes)
        btn_apply_offset.clicked.connect(self.apply_selected_offset_set)
        btn_clear.clicked.connect(self.clear_all)
        btn_save.clicked.connect(self.save_json)
        btn_load.clicked.connect(self.load_json)
        btn_set_origin.clicked.connect(self.prompt_set_origin)

        self.name_box.returnPressed.connect(self.apply_name)
        self.x_box.returnPressed.connect(self.apply_from_xy_boxes)
        self.y_box.returnPressed.connect(self.apply_from_xy_boxes)
        self.lat_box.returnPressed.connect(self.apply_from_latlon_boxes)
        self.lon_box.returnPressed.connect(self.apply_from_latlon_boxes)
        self.offx_box.returnPressed.connect(self.apply_selected_offset_set)
        self.offy_box.returnPressed.connect(self.apply_selected_offset_set)

        root = QWidget()
        main = QVBoxLayout(root)
        main.addWidget(self.view)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Double-click adds:"))
        row1.addWidget(self.add_mode)
        row1.addSpacing(10)
        row1.addWidget(btn_add_wp)
        row1.addWidget(btn_add_ms)
        row1.addWidget(self.snap_cb)
        row1.addSpacing(10)
        row1.addWidget(btn_load)
        row1.addWidget(btn_save)
        row1.addWidget(btn_clear)
        main.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(self.status_lbl, 3)
        row2.addWidget(self.selected_lbl, 2)
        main.addLayout(row2)

        row_name = QHBoxLayout()
        row_name.addWidget(QLabel("Name:"))
        row_name.addWidget(self.name_box)
        row_name.addWidget(btn_apply_name)
        main.addLayout(row_name)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("X (m):"))
        row3.addWidget(self.x_box)
        row3.addWidget(QLabel("Y (m):"))
        row3.addWidget(self.y_box)
        row3.addWidget(btn_apply_xy)
        row3.addSpacing(20)
        row3.addWidget(QLabel("Origin lat:"))
        row3.addWidget(self.origin_lat)
        row3.addWidget(QLabel("Origin lon:"))
        row3.addWidget(self.origin_lon)
        row3.addWidget(btn_set_origin)
        main.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Lat:"))
        row4.addWidget(self.lat_box)
        row4.addWidget(QLabel("Lon:"))
        row4.addWidget(self.lon_box)
        row4.addWidget(btn_apply_ll)
        main.addLayout(row4)

        row5 = QHBoxLayout()
        row5.addWidget(QLabel("Offset X (m):"))
        row5.addWidget(self.offx_box)
        row5.addWidget(QLabel("Offset Y (m):"))
        row5.addWidget(self.offy_box)
        row5.addWidget(btn_apply_offset)
        row5.addStretch(1)
        main.addLayout(row5)

        self.setCentralWidget(root)

        self.scene.selectionChanged.connect(self.update_readout)

        self.draw_grid()
        self.update_readout()

    # ===== Centered conversions: pixels <-> meters =====
    def px_to_meters(self, x_px: float, y_px: float) -> Tuple[float, float]:
        x = (x_px - (W_PX / 2.0)) / PX_PER_M
        y = ((H_PX / 2.0) - y_px) / PX_PER_M
        return x, y

    def meters_to_px(self, x: float, y: float) -> Tuple[float, float]:
        x_px = (W_PX / 2.0) + (x * PX_PER_M)
        y_px = (H_PX / 2.0) - (y * PX_PER_M)
        return x_px, y_px

    def snap_xy(self, x: float, y: float) -> Tuple[float, float]:
        if not self.snap_cb.isChecked():
            return x, y

        def snap(v: float) -> float:
            return round(v / CELL_SIZE_M) * CELL_SIZE_M

        return snap(x), snap(y)

    def clamp_xy(self, x: float, y: float) -> Tuple[float, float]:
        return clamp(x, -HALF_M, HALF_M), clamp(y, -HALF_M, HALF_M)

    # ===== Origin helpers =====
    def origin_is_valid(self) -> bool:
        try:
            float(self.origin_lat.text().strip())
            float(self.origin_lon.text().strip())
            return True
        except Exception:
            return False

    def get_origin(self) -> Tuple[float, float]:
        return float(self.origin_lat.text().strip()), float(self.origin_lon.text().strip())

    # ===== Selection =====
    def selected_item(self):
        sel = self.scene.selectedItems()
        if not sel:
            return None
        item = sel[0]
        if isinstance(item, (DraggableWaypoint, DraggableMission)):
            return item
        return None

    # ===== Base/Offset/Final helpers =====
    def final_from_item(self, item: DraggableBase) -> Tuple[float, float]:
        return item.base_x + item.off_x, item.base_y + item.off_y

    def set_item_final(self, item: DraggableBase, final_x: float, final_y: float):
        # Preserve offset; adjust base so base+offset==final
        item.base_x = final_x - item.off_x
        item.base_y = final_y - item.off_y
        self._apply_item_to_scene(item)

    def set_item_offset(self, item: DraggableBase, off_x: float, off_y: float):
        # Preserve base; change offset -> final moves
        item.off_x = off_x
        item.off_y = off_y
        self._apply_item_to_scene(item)

    def _apply_item_to_scene(self, item: DraggableBase):
        # Clamp/snap FINAL, then recompute base from FINAL (keeping offset)
        final_x, final_y = self.final_from_item(item)
        final_x, final_y = self.clamp_xy(final_x, final_y)
        final_x, final_y = self.snap_xy(final_x, final_y)
        item.base_x = final_x - item.off_x
        item.base_y = final_y - item.off_y

        x_px, y_px = self.meters_to_px(final_x, final_y)
        item.setPos(QPointF(x_px, y_px))

    # ===== Drawing grid =====
    def draw_grid(self):
        self.scene.clear()

        border_pen = QPen(Qt.GlobalColor.black, 2)
        self.scene.addRect(0, 0, W_PX, H_PX, border_pen)

        major_pen = QPen(Qt.GlobalColor.black, 1)
        minor_pen = QPen(Qt.GlobalColor.gray, 1)

        step_px = CELL_SIZE_M * PX_PER_M
        n = int(GRID_SIZE_M / CELL_SIZE_M)

        for i in range(1, n):
            x = i * step_px
            y = i * step_px
            pen = major_pen if (i % 2 == 0) else minor_pen
            self.scene.addLine(x, 0, x, H_PX, pen)
            self.scene.addLine(0, y, W_PX, y, pen)

        axis_pen = QPen(Qt.GlobalColor.black, 2)
        self.scene.addLine(W_PX / 2.0, 0, W_PX / 2.0, H_PX, axis_pen)
        self.scene.addLine(0, H_PX / 2.0, W_PX, H_PX / 2.0, axis_pen)

    # ===== Add items =====
    def handle_double_click_add(self, x_px: float, y_px: float):
        final_x, final_y = self.px_to_meters(x_px, y_px)
        if self.add_mode.currentText().lower().startswith("waypoint"):
            self._add_waypoint(final_x, final_y, name=f"wp{len(self.waypoints)+1}", select=True)
        else:
            self._add_mission(final_x, final_y, name=f"ms{len(self.missions)+1}", select=True)

    def _add_waypoint(self, final_x: float, final_y: float, name: str, select: bool = True):
        final_x, final_y = self.clamp_xy(final_x, final_y)
        final_x, final_y = self.snap_xy(final_x, final_y)
        x_px, y_px = self.meters_to_px(final_x, final_y)

        item_id_1based = len(self.waypoints) + 1
        item = DraggableWaypoint(item_id_1based, name, x_px, y_px, r_px=6.0, on_changed=self.on_item_moved)
        # base starts as final, offset 0
        item.base_x, item.base_y = final_x, final_y
        item.off_x, item.off_y = 0.0, 0.0

        self.scene.addItem(item)
        self.waypoints.append(item)

        if select:
            item.setSelected(True)
            self.update_readout()

    def _add_mission(self, final_x: float, final_y: float, name: str, select: bool = True):
        final_x, final_y = self.clamp_xy(final_x, final_y)
        final_x, final_y = self.snap_xy(final_x, final_y)
        x_px, y_px = self.meters_to_px(final_x, final_y)

        item_id_1based = len(self.missions) + 1
        item = DraggableMission(item_id_1based, name, x_px, y_px, size_px=12.0, on_changed=self.on_item_moved)
        item.base_x, item.base_y = final_x, final_y
        item.off_x, item.off_y = 0.0, 0.0

        self.scene.addItem(item)
        self.missions.append(item)

        if select:
            item.setSelected(True)
            self.update_readout()

    def add_waypoint_center(self):
        self._add_waypoint(0.0, 0.0, name=f"wp{len(self.waypoints)+1}", select=True)

    def add_mission_center(self):
        self._add_mission(0.0, 0.0, name=f"ms{len(self.missions)+1}", select=True)

    # ===== Drag move handler =====
    def on_item_moved(self):
        # When user drags, they drag the FINAL position.
        sel = self.selected_item()
        if sel is not None:
            final_x, final_y = self.px_to_meters(sel.pos().x(), sel.pos().y())
            final_x, final_y = self.clamp_xy(final_x, final_y)
            final_x, final_y = self.snap_xy(final_x, final_y)
            self.set_item_final(sel, final_x, final_y)
        self.update_readout()

    # ===== Manual apply =====
    def apply_name(self):
        sel = self.selected_item()
        if sel is None:
            return
        name = self.name_box.text().strip()
        if not name:
            QMessageBox.information(self, "Name", "Name cannot be empty.")
            return
        sel.name = name
        self.update_readout()

    def apply_from_xy_boxes(self):
        # X/Y boxes are FINAL coords
        sel = self.selected_item()
        if sel is None:
            return
        try:
            final_x = float(self.x_box.text().strip())
            final_y = float(self.y_box.text().strip())
        except Exception:
            QMessageBox.warning(self, "Invalid X/Y", "Enter valid numbers for X and Y.")
            return

        final_x, final_y = self.clamp_xy(final_x, final_y)
        final_x, final_y = self.snap_xy(final_x, final_y)
        self.set_item_final(sel, final_x, final_y)
        self.update_readout()

    def apply_from_latlon_boxes(self):
        # Lat/Lon sets FINAL coords
        sel = self.selected_item()
        if sel is None:
            return
        if not self.origin_is_valid():
            QMessageBox.information(self, "Origin needed", "Set a valid origin lat/lon (at center 0,0) to use Lat/Lon edits.")
            return
        try:
            lat = float(self.lat_box.text().strip())
            lon = float(self.lon_box.text().strip())
        except Exception:
            QMessageBox.warning(self, "Invalid Lat/Lon", "Enter valid numbers for latitude and longitude.")
            return

        o_lat, o_lon = self.get_origin()
        final_x, final_y = latlon_to_meters(o_lat, o_lon, lat, lon)
        final_x, final_y = self.clamp_xy(final_x, final_y)
        final_x, final_y = self.snap_xy(final_x, final_y)
        self.set_item_final(sel, final_x, final_y)
        self.update_readout()

    def apply_selected_offset_set(self):
        # Offset boxes set per-item offset; base stays; final moves.
        sel = self.selected_item()
        if sel is None:
            return
        try:
            off_x = float(self.offx_box.text().strip())
            off_y = float(self.offy_box.text().strip())
        except Exception:
            QMessageBox.warning(self, "Invalid Offset", "Enter valid numbers for Offset X and Offset Y.")
            return

        self.set_item_offset(sel, off_x, off_y)
        self.update_readout()

    # ===== Readout =====
    def update_readout(self):
        sel = self.selected_item()
        if sel is None:
            self.selected_lbl.setText("Selected: none")
            self._set_boxes_safely("", "", "", "", "", "", "")
            return

        final_x, final_y = self.final_from_item(sel)

        if isinstance(sel, DraggableWaypoint):
            self.selected_lbl.setText(f"Selected: Waypoint {sel.item_id_1based}")
        else:
            self.selected_lbl.setText(f"Selected: Mission {sel.item_id_1based}")

        lat_txt = ""
        lon_txt = ""
        if self.origin_is_valid():
            try:
                o_lat, o_lon = self.get_origin()
                lat, lon = meters_to_latlon(o_lat, o_lon, final_x, final_y)
                lat_txt = f"{lat:.8f}"
                lon_txt = f"{lon:.8f}"
            except Exception:
                pass

        self._set_boxes_safely(
            sel.name,
            f"{final_x:.3f}",
            f"{final_y:.3f}",
            lat_txt,
            lon_txt,
            f"{sel.off_x:.3f}",
            f"{sel.off_y:.3f}",
        )

    def _set_boxes_safely(self, name: str, x: str, y: str, lat: str, lon: str, offx: str, offy: str):
        self.name_box.blockSignals(True)
        self.x_box.blockSignals(True)
        self.y_box.blockSignals(True)
        self.lat_box.blockSignals(True)
        self.lon_box.blockSignals(True)
        self.offx_box.blockSignals(True)
        self.offy_box.blockSignals(True)
        try:
            self.name_box.setText(name)
            self.x_box.setText(x)
            self.y_box.setText(y)
            self.lat_box.setText(lat)
            self.lon_box.setText(lon)
            self.offx_box.setText(offx)
            self.offy_box.setText(offy)
        finally:
            self.name_box.blockSignals(False)
            self.x_box.blockSignals(False)
            self.y_box.blockSignals(False)
            self.lat_box.blockSignals(False)
            self.lon_box.blockSignals(False)
            self.offx_box.blockSignals(False)
            self.offy_box.blockSignals(False)

    # ===== Origin helper =====
    def prompt_set_origin(self):
        lat_txt, ok1 = QInputDialog.getText(self, "Origin (center)", "Enter origin latitude at (0,0):")
        if not ok1:
            return
        lon_txt, ok2 = QInputDialog.getText(self, "Origin (center)", "Enter origin longitude at (0,0):")
        if not ok2:
            return
        self.origin_lat.setText(lat_txt.strip())
        self.origin_lon.setText(lon_txt.strip())
        self.update_readout()

    # ===== JSON save/load =====
    def save_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save", "mission.json", "JSON (*.json)")
        if not path:
            return

        wps = []
        for w in self.waypoints:
            x, y = self.final_from_item(w)
            wps.append({
                "id": int(w.item_id_1based),
                "name": str(w.name),
                "x": float(round(x, 3)),
                "y": float(round(y, 3)),
                "offset": {"x": float(round(w.off_x, 3)), "y": float(round(w.off_y, 3))},
            })

        ms = []
        for m in self.missions:
            x, y = self.final_from_item(m)
            ms.append({
                "id": int(m.item_id_1based),
                "name": str(m.name),
                "x": float(round(x, 3)),
                "y": float(round(y, 3)),
                "offset": {"x": float(round(m.off_x, 3)), "y": float(round(m.off_y, 3))},
            })

        data = {
            "origin": {
                "lat": self.origin_lat.text().strip(),
                "lon": self.origin_lon.text().strip(),
            },
            "waypoints": wps,
            "mission_elements": ms,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self.status_lbl.setText(f"Saved {len(wps)} waypoint(s), {len(ms)} mission element(s) to {path}")

    def load_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load", "", "JSON (*.json)")
        if not path:
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        origin = data.get("origin", {})
        self.origin_lat.setText(str(origin.get("lat", "")).strip())
        self.origin_lon.setText(str(origin.get("lon", "")).strip())

        # Rebuild scene and clear lists
        self.scene.clear()
        self.draw_grid()
        self.waypoints.clear()
        self.missions.clear()

        for wp in data.get("waypoints", []):
            try:
                final_x = float(wp["x"])
                final_y = float(wp["y"])
                name = str(wp.get("name", "")).strip() or f"wp{len(self.waypoints)+1}"
                off = wp.get("offset", {})
                off_x = float(off.get("x", 0.0))
                off_y = float(off.get("y", 0.0))
            except Exception:
                continue

            self._add_waypoint(final_x, final_y, name=name, select=False)
            w = self.waypoints[-1]
            w.off_x, w.off_y = off_x, off_y
            # adjust base so final stays the same
            w.base_x = final_x - w.off_x
            w.base_y = final_y - w.off_y
            self._apply_item_to_scene(w)

        for me in data.get("mission_elements", []):
            try:
                final_x = float(me["x"])
                final_y = float(me["y"])
                name = str(me.get("name", "")).strip() or f"ms{len(self.missions)+1}"
                off = me.get("offset", {})
                off_x = float(off.get("x", 0.0))
                off_y = float(off.get("y", 0.0))
            except Exception:
                continue

            self._add_mission(final_x, final_y, name=name, select=False)
            m = self.missions[-1]
            m.off_x, m.off_y = off_x, off_y
            m.base_x = final_x - m.off_x
            m.base_y = final_y - m.off_y
            self._apply_item_to_scene(m)

        # Renumber IDs sequentially
        for i, w in enumerate(self.waypoints):
            w.item_id_1based = i + 1
        for i, m in enumerate(self.missions):
            m.item_id_1based = i + 1

        if self.waypoints:
            self.waypoints[0].setSelected(True)
        elif self.missions:
            self.missions[0].setSelected(True)

        self.status_lbl.setText(f"Loaded {len(self.waypoints)} waypoint(s), {len(self.missions)} mission element(s).")
        self.update_readout()

    def clear_all(self):
        self.scene.clear()
        self.draw_grid()
        self.waypoints.clear()
        self.missions.clear()
        self.update_readout()


def main():
    app = QApplication([])
    w = MainWindow()
    w.resize(1300, 980)
    w.show()
    app.exec()


if __name__ == "__main__":
    main()