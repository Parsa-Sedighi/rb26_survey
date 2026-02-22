import json
import math
from typing import List, Tuple
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPen, QBrush, QFont, QPainter
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGraphicsView, QGraphicsScene,
    QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsTextItem, 
    QFileDialog, QMessageBox, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView
)

# ===== Competition Constants (Nathan Benderson Park) =====
ORIGIN_LAT = 27.374831        
ORIGIN_LON = -82.452441       
GRID_SIZE_M = 100.0
PX_PER_M = 8.0
W_PX = H_PX = int(GRID_SIZE_M * PX_PER_M)
R_EARTH = 6371000.0 

# Origin anchored at 90% Y for forward visibility (West is UP)
CENTER_X_PX = W_PX / 2
CENTER_Y_PX = H_PX * 0.9 

# ===== Math Engine =====

def latlon_to_meters(lat, lon):
    m_lat, m_lon = 111320.0, 111320.0 * math.cos(math.radians(ORIGIN_LAT))
    return (lon - ORIGIN_LON) * m_lon, (lat - ORIGIN_LAT) * m_lat

def meters_to_latlon(east_m, north_m):
    m_lat, m_lon = 111320.0, 111320.0 * math.cos(math.radians(ORIGIN_LAT))
    return ORIGIN_LAT + (north_m / m_lat), ORIGIN_LON + (east_m / m_lon)

def calculate_projection(user_lat, user_lon, west_brg, dist):
    # 0 deg = West. True North is 270 deg from this perspective
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

    def update_coords(self):
        nm = (self.pos().x() - CENTER_X_PX)/PX_PER_M
        em = (self.pos().y() - CENTER_Y_PX)/PX_PER_M
        self.lat, self.lon = meters_to_latlon(em, nm)

    def get_displacement_m(self):
        dx = (self.pos().x() - self.start_pos.x()) / PX_PER_M
        dy = (self.pos().y() - self.start_pos.y()) / PX_PER_M
        return math.sqrt(dx**2 + dy**2)

class MissionElement(QGraphicsRectItem, MapItem):
    def __init__(self, x, y, name, on_move):
        super().__init__(-6, -6, 12, 12)
        self.setBrush(QBrush(Qt.GlobalColor.green))
        self.setPos(x, y); self.on_move = on_move
        self.setup_base(name); self.update_coords()
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable | self.GraphicsItemFlag.ItemIsSelectable | self.GraphicsItemFlag.ItemSendsGeometryChanges)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged: 
            self.update_coords(); self.on_move(self)
        return super().itemChange(change, value)

class Waypoint(QGraphicsEllipseItem, MapItem):
    def __init__(self, x, y, name, on_move):
        super().__init__(-5, -5, 10, 10)
        self.setBrush(QBrush(Qt.GlobalColor.red))
        self.setPos(x, y); self.on_move = on_move
        self.setup_base(name); self.update_coords()
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable | self.GraphicsItemFlag.ItemIsSelectable | self.GraphicsItemFlag.ItemSendsGeometryChanges)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged: 
            self.update_coords(); self.on_move(self)
        return super().itemChange(change, value)

# ===== Main App =====

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboBoat 2026 | Surveyor v17.1")
        self.scene = QGraphicsScene(0, 0, W_PX, H_PX)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.items = [] 

        central_widget = QWidget(); main_h_layout = QHBoxLayout(central_widget)
        left_layout = QVBoxLayout(); left_layout.addWidget(self.view)

        # Placement Controls
        c_lay = QHBoxLayout()
        self.type_combo = QComboBox(); self.type_combo.addItems(["Object (Green)", "Waypoint (Red)"])
        self.in_lat = QLineEdit(placeholderText="Obs Lat"); self.in_lon = QLineEdit(placeholderText="Obs Lon")
        self.in_brg = QLineEdit(placeholderText="Brg (0=W)"); self.in_dist = QLineEdit(placeholderText="Dist (m)")
        btn_proj = QPushButton("🚀 Project")
        btn_proj.clicked.connect(self.add_by_projection)
        c_lay.addWidget(self.type_combo); c_lay.addWidget(self.in_lat); c_lay.addWidget(self.in_lon)
        c_lay.addWidget(self.in_brg); c_lay.addWidget(self.in_dist); c_lay.addWidget(btn_proj)
        left_layout.addLayout(c_lay)

        # Edit/Nudge Controls
        edit_lay = QHBoxLayout()
        self.lbl_delta = QLabel("Move Delta: 0.00m")
        self.nudge_w = QLineEdit("0.0"); self.nudge_w.setFixedWidth(40)
        self.nudge_n = QLineEdit("0.0"); self.nudge_n.setFixedWidth(40)
        btn_nudge = QPushButton("Move")
        btn_nudge.clicked.connect(self.nudge_item)
        btn_del = QPushButton("❌ Delete"); btn_del.clicked.connect(self.delete_item)
        btn_save = QPushButton("💾 Save JSON"); btn_save.clicked.connect(self.save_mission)
        
        edit_lay.addWidget(self.lbl_delta); edit_lay.addSpacing(10)
        edit_lay.addWidget(QLabel("W:")); edit_lay.addWidget(self.nudge_w)
        edit_lay.addWidget(QLabel("N:")); edit_lay.addWidget(self.nudge_n)
        edit_lay.addWidget(btn_nudge); edit_lay.addStretch(); edit_lay.addWidget(btn_del); edit_lay.addWidget(btn_save)
        left_layout.addLayout(edit_lay)

        # Right Panel
        right_panel = QVBoxLayout()
        h_lay = QHBoxLayout(); h_lay.addWidget(QLabel("<b>WAYPOINT LIST</b>"))
        btn_copy = QPushButton("📋 Copy JSON"); btn_copy.clicked.connect(self.copy_json_to_clipboard)
        h_lay.addWidget(btn_copy); right_panel.addLayout(h_lay)
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["ID", "Type", "Lat", "Lon"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        right_panel.addWidget(self.table)

        main_h_layout.addLayout(left_layout, 7); main_h_layout.addLayout(right_panel, 3)
        self.setCentralWidget(central_widget); self.draw_grid()
        self.view.mouseDoubleClickEvent = self.handle_double_click
        self.scene.selectionChanged.connect(self.handle_selection)

    def draw_grid(self):
        self.scene.clear()
        self.scene.addRect(0, 0, W_PX, H_PX, QPen(Qt.GlobalColor.black, 2))
        font = QFont("Arial", 12, QFont.Weight.Bold)
        self.scene.addText("WEST (FRONT)", font).setPos(CENTER_X_PX-60, 10)
        
        grid_p = QPen(Qt.GlobalColor.lightGray, 0.5)
        for i in range(-20, 20):
            x = CENTER_X_PX + (i * 5 * PX_PER_M)
            y = CENTER_Y_PX + (i * 5 * PX_PER_M)
            if 0 <= x <= W_PX: self.scene.addLine(x, 0, x, H_PX, grid_p)
            if 0 <= y <= H_PX: self.scene.addLine(0, y, W_PX, y, grid_p)

        self.scene.addLine(CENTER_X_PX, 0, CENTER_X_PX, H_PX, QPen(Qt.GlobalColor.blue, 1, Qt.PenStyle.DashLine))
        self.scene.addLine(0, CENTER_Y_PX, W_PX, CENTER_Y_PX, QPen(Qt.GlobalColor.blue, 1, Qt.PenStyle.DashLine))

    def handle_double_click(self, event):
        pos = self.view.mapToScene(event.pos()); self.create_item(pos.x(), pos.y())

    def add_by_projection(self):
        try:
            t_lat, t_lon = calculate_projection(float(self.in_lat.text()), float(self.in_lon.text()), float(self.in_brg.text()), float(self.in_dist.text()))
            em, nm = latlon_to_meters(t_lat, t_lon)
            self.create_item(CENTER_X_PX + (nm * PX_PER_M), CENTER_Y_PX + (em * PX_PER_M))
        except: pass

    def create_item(self, x, y):
        prefix = "Obj" if self.type_combo.currentIndex() == 0 else "WP"
        name = f"{prefix}_{len(self.items)+1}"
        item = MissionElement(x, y, name, self.refresh_table) if prefix == "Obj" else Waypoint(x, y, name, self.refresh_table)
        self.scene.addItem(item); self.items.append(item); self.refresh_table()

    def nudge_item(self):
        for item in self.scene.selectedItems():
            dy, dx = -float(self.nudge_w.text()) * PX_PER_M, float(self.nudge_n.text()) * PX_PER_M
            item.setPos(item.pos().x() + dx, item.pos().y() + dy)
        self.refresh_table()

    def delete_item(self):
        for item in self.scene.selectedItems():
            if item in self.items: self.items.remove(item)
            self.scene.removeItem(item)
        self.refresh_table()

    def refresh_table(self, _=None):
        self.table.setRowCount(0)
        for i, item in enumerate(self.items):
            prefix = "Obj" if isinstance(item, MissionElement) else "WP"
            item.display_name = f"{prefix}_{i+1}"
            item.label.setPlainText(item.display_name)
            r = self.table.rowCount(); self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(item.display_name))
            self.table.setItem(r, 1, QTableWidgetItem(prefix))
            self.table.setItem(r, 2, QTableWidgetItem(f"{item.lat:.7f}")); self.table.setItem(r, 3, QTableWidgetItem(f"{item.lon:.7f}"))

    def handle_selection(self):
        sel = self.scene.selectedItems()
        if sel and isinstance(sel[0], MapItem):
            self.lbl_delta.setText(f"Move Delta: {sel[0].get_displacement_m():.2f}m")

    def format_json_output(self):
        """Formats JSON so that each waypoint object {} is on its own single line."""
        wp_list_strings = []
        for i, item in enumerate(self.items):
            data = {
                "id": i + 1,
                "name": item.display_name,
                "lat": round(item.lat, 7),
                "lon": round(item.lon, 7),
                "task": "UNKNOWN"
            }
            # json.dumps without indent creates the single line for the object
            wp_list_strings.append(f"    {json.dumps(data)}")
        
        # Construct the final string manually
        output = "{\n"
        output += '  "frame_id": "map",\n'
        output += '  "waypoints": [\n'
        output += ",\n".join(wp_list_strings)
        output += "\n  ]\n}"
        return output

    def copy_json_to_clipboard(self):
        json_text = self.format_json_output()
        QApplication.clipboard().setText(json_text)
        QMessageBox.information(self, "Copy", "JSON structure copied to clipboard.")

    def save_mission(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Mission", "mission.json", "JSON (*.json)")
        if path:
            json_text = self.format_json_output()
            with open(path, "w") as f:
                f.write(json_text)

if __name__ == "__main__":
    app = QApplication([]); ex = MainWindow(); ex.resize(1350, 950); ex.show(); app.exec()