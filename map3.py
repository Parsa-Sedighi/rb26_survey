import json
import math
from typing import List, Tuple
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPen, QBrush, QFont, QPainter
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGraphicsView, QGraphicsScene,
    QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsTextItem, 
    QFileDialog, QMessageBox, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QFormLayout, QDialog, QDialogButtonBox
)

# ===== Competition Constants (Nathan Benderson Park) =====
ORIGIN_LAT = 27.374831        
ORIGIN_LON = -82.452441       
R_EARTH = 6371000.0

# ===== Dynamic Grid Parameters (updated via UI) =====
# Defaults: 100m wide, 100m tall, 8px/m
GRID_WIDTH_M  = 100.0
GRID_HEIGHT_M = 100.0
PX_PER_M      = 4.0           # 2m per cell → cell = 2*PX_PER_M px; adjusted on resize
CELL_SIZE_M   = 2.0           # fixed cell size in meters

W_PX = int(GRID_WIDTH_M  * PX_PER_M)
H_PX = int(GRID_HEIGHT_M * PX_PER_M)

# Origin in pixel space (boat starts bottom-center)
CENTER_X_PX = W_PX / 2
CENTER_Y_PX = H_PX * 0.9

# ===== Math Engine =====

def latlon_to_meters(lat, lon):
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(ORIGIN_LAT))
    return (lon - ORIGIN_LON) * m_lon, (lat - ORIGIN_LAT) * m_lat

def meters_to_latlon(east_m, north_m):
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(ORIGIN_LAT))
    return ORIGIN_LAT + (north_m / m_lat), ORIGIN_LON + (east_m / m_lon)

def haversine_distance(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R_EARTH * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def bearing_between(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def calculate_projection(user_lat, user_lon, west_brg, dist):
    true_brg = (270 + west_brg) % 360
    phi1, lam1 = math.radians(user_lat), math.radians(user_lon)
    theta, delta = math.radians(true_brg), dist / R_EARTH
    phi2 = math.asin(math.sin(phi1)*math.cos(delta) + math.cos(phi1)*math.sin(delta)*math.cos(theta))
    lam2 = lam1 + math.atan2(math.sin(theta)*math.sin(delta)*math.cos(phi1), math.cos(delta)-math.sin(phi1)*math.sin(phi2))
    return math.degrees(phi2), math.degrees(lam2)

# ===== Graphics Items =====

class MapItem:
    def setup_base(self, initial_name):
        self.display_name = initial_name
        self.label = QGraphicsTextItem(self.display_name, self)
        self.label.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        self.label.setPos(8, -10)
        self.start_pos = self.pos()

    def update_label(self, name):
        self.display_name = name
        self.label.setPlainText(name)

    def update_coords(self):
        # Y axis = West (north in scene is up, but scene Y increases downward)
        # x pixel offset from center → North meters
        # y pixel offset from center → East meters (positive down = positive east... wait:
        #   CENTER_Y_PX is at bottom, so going UP (smaller y) = going North
        #   We map: north_m = (CENTER_X_PX - pos.x()) / PX_PER_M  [west is +x, north is -y direction... see axes]
        # 
        # Per user: Y axis = West, X axis = North
        # In scene: pos.x() increases right (North), pos.y() increases down (East... inverted West)
        # West is actually -North in standard terms; but per user, we just treat it as:
        #   north_m from center = (pos.x() - CENTER_X_PX) / PX_PER_M
        #   east_m from center  = (CENTER_Y_PX - pos.y()) / PX_PER_M  [up = positive]
        north_m = (self.pos().x() - CENTER_X_PX) / PX_PER_M
        east_m  = (CENTER_Y_PX  - self.pos().y()) / PX_PER_M
        self.lat, self.lon = meters_to_latlon(east_m, north_m)

    def get_displacement_m(self):
        dx = (self.pos().x() - self.start_pos.x()) / PX_PER_M
        dy = (self.pos().y() - self.start_pos.y()) / PX_PER_M
        return math.sqrt(dx**2 + dy**2)

class MissionElement(QGraphicsRectItem, MapItem):
    def __init__(self, x, y, name, on_move, size=5):
        s = size
        super().__init__(-s, -s, s * 2, s * 2)
        self.setBrush(QBrush(Qt.GlobalColor.green))
        self.setPos(x, y)
        self.on_move = on_move
        self.setup_base(name)
        self.update_coords()
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable |
                      self.GraphicsItemFlag.ItemIsSelectable |
                      self.GraphicsItemFlag.ItemSendsGeometryChanges)

    def set_size(self, size):
        self.setRect(-size, -size, size * 2, size * 2)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged:
            self.update_coords(); self.on_move(self)
        return super().itemChange(change, value)

class Waypoint(QGraphicsEllipseItem, MapItem):
    def __init__(self, x, y, name, on_move, size=5):
        s = size
        super().__init__(-s, -s, s * 2, s * 2)
        self.setBrush(QBrush(Qt.GlobalColor.red))
        self.setPos(x, y)
        self.on_move = on_move
        self.setup_base(name)
        self.update_coords()
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable |
                      self.GraphicsItemFlag.ItemIsSelectable |
                      self.GraphicsItemFlag.ItemSendsGeometryChanges)

    def set_size(self, size):
        self.setRect(-size, -size, size * 2, size * 2)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged:
            self.update_coords(); self.on_move(self)
        return super().itemChange(change, value)

# ===== Grid Config Dialog =====

class GridConfigDialog(QDialog):
    """
    Dialog to set the grid from two bottom corner GPS coords + a width.
    The grid center-bottom is the midpoint of the two bottom corners.
    Width overrides the distance between the two points (for exact sizing).
    Height is computed to make the grid square (or user can adjust).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Grid")
        layout = QFormLayout(self)

        self.lb_lat  = QLineEdit(str(ORIGIN_LAT)); layout.addRow("Left-Bottom Lat:",  self.lb_lat)
        self.lb_lon  = QLineEdit(str(ORIGIN_LON)); layout.addRow("Left-Bottom Lon:",  self.lb_lon)
        self.rb_lat  = QLineEdit(str(ORIGIN_LAT)); layout.addRow("Right-Bottom Lat:", self.rb_lat)
        self.rb_lon  = QLineEdit(str(float(ORIGIN_LON) + 0.001)); layout.addRow("Right-Bottom Lon:", self.rb_lon)
        self.width_m = QLineEdit("100"); layout.addRow("Grid Width (m):",  self.width_m)
        self.height_m= QLineEdit("100"); layout.addRow("Grid Height (m):", self.height_m)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_values(self):
        return (float(self.lb_lat.text()), float(self.lb_lon.text()),
                float(self.rb_lat.text()), float(self.rb_lon.text()),
                float(self.width_m.text()), float(self.height_m.text()))

# ===== Zoomable View =====

class ZoomableGraphicsView(QGraphicsView):
    """QGraphicsView with smooth mouse-wheel zoom centered on cursor."""
    ZOOM_FACTOR = 1.15
    MIN_ZOOM = 0.05
    MAX_ZOOM = 50.0

    def __init__(self, scene):
        super().__init__(scene)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._zoom_level = 1.0

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = self.ZOOM_FACTOR if delta > 0 else 1.0 / self.ZOOM_FACTOR
        new_zoom = self._zoom_level * factor
        if self.MIN_ZOOM <= new_zoom <= self.MAX_ZOOM:
            self._zoom_level = new_zoom
            self.scale(factor, factor)


# ===== Main App =====

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboBoat 2026 | Surveyor v19.0")

        # Grid state
        self.grid_width_m  = GRID_WIDTH_M
        self.grid_height_m = GRID_HEIGHT_M
        self.px_per_m      = PX_PER_M
        self.w_px          = W_PX
        self.h_px          = H_PX
        self.center_x_px   = CENTER_X_PX
        self.center_y_px   = CENTER_Y_PX
        # bottom-center lat/lon (used as local origin for display)
        self.origin_lat    = ORIGIN_LAT
        self.origin_lon    = ORIGIN_LON

        self.scene = QGraphicsScene(0, 0, self.w_px, self.h_px)
        self.view  = ZoomableGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.items = []

        central_widget = QWidget()
        main_h_layout  = QHBoxLayout(central_widget)
        left_layout    = QVBoxLayout()
        left_layout.addWidget(self.view)

        # ---- Grid Config Button + Point Size ----
        grid_bar = QHBoxLayout()
        self.lbl_grid = QLabel(f"Grid: {self.grid_width_m:.0f}m × {self.grid_height_m:.0f}m  |  Cell: {CELL_SIZE_M}m")
        btn_grid = QPushButton("⚙ Configure Grid")
        btn_grid.clicked.connect(self.configure_grid)

        self.point_size = 5  # default radius in px
        grid_bar.addWidget(self.lbl_grid); grid_bar.addStretch()
        grid_bar.addWidget(QLabel("Point size (px):"))
        self.spin_size = QLineEdit(str(self.point_size)); self.spin_size.setFixedWidth(35)
        self.spin_size.editingFinished.connect(self.apply_point_size)
        grid_bar.addWidget(self.spin_size)
        grid_bar.addWidget(btn_grid)
        left_layout.addLayout(grid_bar)

        # ---- Projection Controls ----
        c_lay = QHBoxLayout()
        self.type_combo = QComboBox(); self.type_combo.addItems(["Object (Green)", "Waypoint (Red)"])
        self.in_lat  = QLineEdit(placeholderText="Obs Lat")
        self.in_lon  = QLineEdit(placeholderText="Obs Lon")
        self.in_brg  = QLineEdit(placeholderText="Brg (0=W)")
        self.in_dist = QLineEdit(placeholderText="Dist (m)")
        btn_proj = QPushButton("🚀 Project"); btn_proj.clicked.connect(self.add_by_projection)
        c_lay.addWidget(self.type_combo); c_lay.addWidget(self.in_lat); c_lay.addWidget(self.in_lon)
        c_lay.addWidget(self.in_brg); c_lay.addWidget(self.in_dist); c_lay.addWidget(btn_proj)
        left_layout.addLayout(c_lay)

        # ---- Modification Controls ----
        edit_lay = QHBoxLayout()
        self.lbl_delta = QLabel("Move Delta: 0.00m")
        self.nudge_w = QLineEdit("0.0"); self.nudge_w.setFixedWidth(50)
        self.nudge_n = QLineEdit("0.0"); self.nudge_n.setFixedWidth(50)
        btn_nudge = QPushButton("Move"); btn_nudge.clicked.connect(self.nudge_item)
        btn_del   = QPushButton("❌ Delete"); btn_del.clicked.connect(self.delete_item)
        btn_load  = QPushButton("📂 Load JSON"); btn_load.clicked.connect(self.load_mission)
        btn_save  = QPushButton("💾 Save JSON"); btn_save.clicked.connect(self.save_mission)

        edit_lay.addWidget(self.lbl_delta); edit_lay.addSpacing(10)
        edit_lay.addWidget(QLabel("W(m):")); edit_lay.addWidget(self.nudge_w)
        edit_lay.addWidget(QLabel("N(m):")); edit_lay.addWidget(self.nudge_n)
        edit_lay.addWidget(btn_nudge); edit_lay.addStretch()
        edit_lay.addWidget(btn_del); edit_lay.addWidget(btn_load); edit_lay.addWidget(btn_save)
        left_layout.addLayout(edit_lay)

        # ---- Right Panel ----
        right_panel = QVBoxLayout()
        right_panel.addWidget(QLabel("<b>WAYPOINT LIST</b> (click Name to rename)"))

        copy_lay = QHBoxLayout()
        btn_copy_objs = QPushButton("📋 Copy Objects")
        btn_copy_objs.clicked.connect(lambda: self.copy_to_clipboard("objects"))
        btn_copy_wps  = QPushButton("📋 Copy Waypoints")
        btn_copy_wps.clicked.connect(lambda: self.copy_to_clipboard("waypoints"))
        copy_lay.addWidget(btn_copy_objs); copy_lay.addWidget(btn_copy_wps)
        right_panel.addLayout(copy_lay)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Lat", "Lon"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # Only Name column editable; others read-only (enforced in refresh_table)
        self.table.itemChanged.connect(self.on_table_name_changed)
        right_panel.addWidget(self.table)

        main_h_layout.addLayout(left_layout, 7)
        main_h_layout.addLayout(right_panel, 3)
        self.setCentralWidget(central_widget)

        self.draw_grid()
        self.view.mouseDoubleClickEvent = self.handle_double_click
        self.scene.selectionChanged.connect(self.handle_selection)

    # ===== Grid Configuration =====

    def configure_grid(self):
        dlg = GridConfigDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        lb_lat, lb_lon, rb_lat, rb_lon, width_m, height_m = dlg.get_values()

        # Grid origin (local lat/lon origin) = midpoint of bottom edge
        mid_lat = (lb_lat + rb_lat) / 2
        mid_lon = (lb_lon + rb_lon) / 2

        # Update module-level origin for coord conversions
        global ORIGIN_LAT, ORIGIN_LON
        ORIGIN_LAT = mid_lat
        ORIGIN_LON = mid_lon
        self.origin_lat = mid_lat
        self.origin_lon = mid_lon

        self.grid_width_m  = width_m
        self.grid_height_m = height_m

        # px_per_m: fit the grid into a reasonable view size
        # We target ~800px wide max; compute px_per_m from that
        target_px = 800
        self.px_per_m = target_px / max(width_m, height_m)
        self.w_px = int(width_m  * self.px_per_m)
        self.h_px = int(height_m * self.px_per_m)

        # Center-bottom of scene
        self.center_x_px = self.w_px / 2
        self.center_y_px = self.h_px * 0.9

        self.lbl_grid.setText(f"Grid: {width_m:.0f}m × {height_m:.0f}m  |  Cell: {CELL_SIZE_M}m  |  Origin: {mid_lat:.6f}, {mid_lon:.6f}")

        # Clear items and redraw
        self.items.clear()
        self.scene.setSceneRect(0, 0, self.w_px, self.h_px)
        self.draw_grid()
        self.refresh_table()

    # ===== Drawing =====

    def draw_grid(self):
        self.scene.clear()
        self.scene.setSceneRect(0, 0, self.w_px, self.h_px)
        self.view.setScene(self.scene)

        # Border
        self.scene.addRect(0, 0, self.w_px, self.h_px, QPen(Qt.GlobalColor.black, 2))

        # Labels
        font = QFont("Arial", 10, QFont.Weight.Bold)
        t = self.scene.addText("NORTH →", font)
        t.setPos(self.center_x_px - 30, 4)
        t2 = self.scene.addText("↑ WEST", font)
        t2.setPos(4, self.center_y_px - 40)

        # Grid lines every CELL_SIZE_M
        grid_p = QPen(Qt.GlobalColor.lightGray, 0.5)
        cell_px = CELL_SIZE_M * self.px_per_m

        x = self.center_x_px
        while x <= self.w_px:
            self.scene.addLine(x, 0, x, self.h_px, grid_p); x += cell_px
        x = self.center_x_px - cell_px
        while x >= 0:
            self.scene.addLine(x, 0, x, self.h_px, grid_p); x -= cell_px

        y = self.center_y_px
        while y <= self.h_px:
            self.scene.addLine(0, y, self.w_px, y, grid_p); y += cell_px
        y = self.center_y_px - cell_px
        while y >= 0:
            self.scene.addLine(0, y, self.w_px, y, grid_p); y -= cell_px

        # Axis lines
        self.scene.addLine(self.center_x_px, 0, self.center_x_px, self.h_px,
                           QPen(Qt.GlobalColor.blue, 1, Qt.PenStyle.DashLine))
        self.scene.addLine(0, self.center_y_px, self.w_px, self.center_y_px,
                           QPen(Qt.GlobalColor.blue, 1, Qt.PenStyle.DashLine))

        # Re-add existing items to scene
        for item in self.items:
            self.scene.addItem(item)

    # ===== Item Management =====

    def handle_double_click(self, event):
        pos = self.view.mapToScene(event.pos())
        self.create_item(pos.x(), pos.y())

    def add_by_projection(self):
        try:
            t_lat, t_lon = calculate_projection(
                float(self.in_lat.text()), float(self.in_lon.text()),
                float(self.in_brg.text()), float(self.in_dist.text()))
            em, nm = latlon_to_meters(t_lat, t_lon)
            px = self.center_x_px + nm * self.px_per_m
            py = self.center_y_px - em * self.px_per_m
            self.create_item(px, py)
        except Exception as e:
            QMessageBox.warning(self, "Projection Error", str(e))

    def create_item(self, x, y, name=None):
        is_obj = self.type_combo.currentIndex() == 0
        prefix = "Obj" if is_obj else "WP"
        if name is None:
            name = f"{prefix}_{len(self.items)+1}"

        item = (MissionElement(x, y, name, self.refresh_table, self.point_size)
                if ("Obj" in name or is_obj)
                else Waypoint(x, y, name, self.refresh_table, self.point_size))
        self.scene.addItem(item)
        self.items.append(item)
        self.refresh_table()


    def apply_point_size(self):
        try:
            size = max(1, int(self.spin_size.text()))
        except ValueError:
            return
        self.point_size = size
        for item in self.items:
            item.set_size(size)

    def nudge_item(self):
        try:
            dw = float(self.nudge_w.text())  # West meters
            dn = float(self.nudge_n.text())  # North meters
        except ValueError:
            return
        # North → +x in scene; West → -y in scene (up)
        dx =  dn * self.px_per_m
        dy = -dw * self.px_per_m
        for item in self.scene.selectedItems():
            item.setPos(item.pos().x() + dx, item.pos().y() + dy)
        self.refresh_table()

    def delete_item(self):
        for item in self.scene.selectedItems():
            if item in self.items:
                self.items.remove(item)
            self.scene.removeItem(item)
        self.refresh_table()

    # ===== Table =====

    def refresh_table(self, _=None):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for item in self.items:
            r = self.table.rowCount()
            self.table.insertRow(r)

            name_cell = QTableWidgetItem(item.display_name)
            # Name column: editable
            self.table.setItem(r, 0, name_cell)

            type_cell = QTableWidgetItem("Obj" if isinstance(item, MissionElement) else "WP")
            type_cell.setFlags(type_cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 1, type_cell)

            lat_cell = QTableWidgetItem(f"{item.lat:.7f}")
            lat_cell.setFlags(lat_cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 2, lat_cell)

            lon_cell = QTableWidgetItem(f"{item.lon:.7f}")
            lon_cell.setFlags(lon_cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 3, lon_cell)

        self.table.blockSignals(False)

    def on_table_name_changed(self, table_item):
        """Called when user edits a cell in the table. Only col 0 is editable."""
        if table_item.column() != 0:
            return
        row = table_item.row()
        if row < 0 or row >= len(self.items):
            return
        new_name = table_item.text().strip()
        if new_name:
            self.items[row].update_label(new_name)

    def handle_selection(self):
        sel = self.scene.selectedItems()
        if sel and isinstance(sel[0], MapItem):
            self.lbl_delta.setText(f"Move Delta: {sel[0].get_displacement_m():.2f}m")

    # ===== JSON =====

    def format_json_output(self, filter_type=None):
        wp_list_strings = []
        counter = 1
        for item in self.items:
            is_obj = isinstance(item, MissionElement)
            if filter_type == "objects"   and not is_obj: continue
            if filter_type == "waypoints" and     is_obj: continue

            data = {
                "id":   counter,
                "name": item.display_name,
                "lat":  round(item.lat, 7),
                "lon":  round(item.lon, 7),
                "task": "UNKNOWN"
            }
            wp_list_strings.append(f"    {json.dumps(data)}")
            counter += 1

        output = (
            "{\n"
            '  "frame_id": "map",\n'
            f'  "count": {len(wp_list_strings)},\n'
            '  "waypoints": [\n'
            + ",\n".join(wp_list_strings) +
            "\n  ]\n}"
        )
        return output

    def copy_to_clipboard(self, filter_type):
        json_data = self.format_json_output(filter_type)
        QApplication.clipboard().setText(json_data)
        QMessageBox.information(self, "Copy", f"JSON for {filter_type} copied to clipboard.")

    def save_mission(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Mission", "mission.json", "JSON (*.json)")
        if path:
            with open(path, "w") as f:
                f.write(self.format_json_output())

    def load_mission(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Mission", "", "JSON (*.json)")
        if not path: return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.items.clear()
            self.draw_grid()
            for wp in data.get("waypoints", []):
                em, nm = latlon_to_meters(wp["lat"], wp["lon"])
                px = self.center_x_px + nm * self.px_per_m
                py = self.center_y_px - em * self.px_per_m
                self.type_combo.setCurrentIndex(0 if "Obj" in wp["name"] else 1)
                self.create_item(px, py, name=wp["name"])
            self.refresh_table()
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load file: {e}")


if __name__ == "__main__":
    app = QApplication([])
    ex = MainWindow()
    ex.resize(1400, 980)
    ex.show()
    app.exec()