import json
import math
from typing import List, Tuple
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPen, QBrush, QFont, QPainter
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGraphicsView, QGraphicsScene,
    QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsTextItem, 
    QFileDialog, QMessageBox, QLineEdit, QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView
)

# ===== Competition Constants (Nathan Benderson Park) =====
ORIGIN_LAT = 27.375634
ORIGIN_LON = -82.452487
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
    true_brg = (270 + west_brg) % 360
    phi1, lam1 = math.radians(user_lat), math.radians(user_lon)
    theta, delta = math.radians(true_brg), dist / R_EARTH
    phi2 = math.asin(math.sin(phi1)*math.cos(delta) + math.cos(phi1)*math.sin(delta)*math.cos(theta))
    lam2 = lam1 + math.atan2(math.sin(theta)*math.sin(delta)*math.cos(phi1), math.cos(delta)-math.sin(phi1)*math.sin(phi2))
    return math.degrees(phi2), math.degrees(lam2)

# ===== Graphics Items =====

class MapItem:
    def setup_base(self, label_prefix):
        self.label_prefix = label_prefix
        self.label = QGraphicsTextItem("", self)
        self.label.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        self.label.setDefaultTextColor(Qt.GlobalColor.black)
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
    def __init__(self, x, y, on_move):
        super().__init__(-6, -6, 12, 12)
        self.setBrush(QBrush(Qt.GlobalColor.green))
        self.setPos(x, y)
        self.on_move = on_move
        self.setup_base("O")
        self.update_coords()
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable | self.GraphicsItemFlag.ItemIsSelectable | self.GraphicsItemFlag.ItemSendsGeometryChanges)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged: 
            self.update_coords()
            self.on_move(self)
        return super().itemChange(change, value)

class Waypoint(QGraphicsEllipseItem, MapItem):
    def __init__(self, x, y, on_move):
        super().__init__(-5, -5, 10, 10)
        self.setBrush(QBrush(Qt.GlobalColor.red))
        self.setPos(x, y)
        self.on_move = on_move
        self.setup_base("W")
        self.update_coords()
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable | self.GraphicsItemFlag.ItemIsSelectable | self.GraphicsItemFlag.ItemSendsGeometryChanges)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged: 
            self.update_coords()
            self.on_move(self)
        return super().itemChange(change, value)

# ===== Main App =====

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboBoat 2026 | Surveyor & Precision Planner")
        self.scene = QGraphicsScene(0, 0, W_PX, H_PX)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        self.elements = []
        self.waypoints = []

        central_widget = QWidget()
        main_h_layout = QHBoxLayout(central_widget)
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.view)

        # Mode Selector
        mode_lay = QHBoxLayout()
        self.btn_survey = QPushButton("Mode 1: Survey Objects")
        self.btn_edit = QPushButton("Mode 2: Path Planning")
        self.btn_survey.clicked.connect(lambda: self.switch_mode(0))
        self.btn_edit.clicked.connect(lambda: self.switch_mode(1))
        mode_lay.addWidget(self.btn_survey); mode_lay.addWidget(self.btn_edit)
        left_layout.addLayout(mode_lay)

        self.panel_stack = QStackedWidget()
        
        # --- Mode 1: Survey Panel ---
        survey_w = QWidget(); s_lay = QHBoxLayout(survey_w)
        self.in_lat = QLineEdit(); self.in_lon = QLineEdit()
        self.in_brg = QLineEdit(placeholderText="Brg (0=W)"); self.in_dist = QLineEdit(placeholderText="Dist (m)")
        btn_proj = QPushButton("🚀 Project")
        btn_proj.clicked.connect(self.add_surveyed_element_by_input)
        btn_del_survey = QPushButton("❌ Delete")
        btn_del_survey.clicked.connect(self.delete_selected_item)
        
        s_lay.addWidget(QLabel("Obs:")); s_lay.addWidget(self.in_lat); s_lay.addWidget(self.in_lon)
        s_lay.addWidget(self.in_brg); s_lay.addWidget(self.in_dist); s_lay.addWidget(btn_proj); s_lay.addWidget(btn_del_survey)

        # --- Mode 2: Edit Panel ---
        edit_w = QWidget(); e_vlay = QVBoxLayout(edit_w)
        e_hlay1 = QHBoxLayout()
        self.lbl_move_delta = QLabel("Move Delta: 0.00m")
        self.nudge_up = QLineEdit("0.0"); self.nudge_up.setFixedWidth(40)
        self.nudge_right = QLineEdit("0.0"); self.nudge_right.setFixedWidth(40)
        btn_nudge = QPushButton("Move")
        btn_nudge.clicked.connect(self.nudge_selected_item)
        btn_del_edit = QPushButton("❌ Delete")
        btn_del_edit.clicked.connect(self.delete_selected_item)
        btn_save = QPushButton("💾 Save JSON")
        btn_save.clicked.connect(self.save_mission)
        
        e_hlay1.addWidget(self.lbl_move_delta); e_hlay1.addSpacing(10)
        e_hlay1.addWidget(QLabel("W:")); e_hlay1.addWidget(self.nudge_up)
        e_hlay1.addWidget(QLabel("N:")); e_hlay1.addWidget(self.nudge_right)
        e_hlay1.addWidget(btn_nudge); e_hlay1.addStretch(); e_hlay1.addWidget(btn_del_edit); e_hlay1.addWidget(btn_save)
        e_vlay.addLayout(e_hlay1)

        self.panel_stack.addWidget(survey_w); self.panel_stack.addWidget(edit_w)
        left_layout.addWidget(self.panel_stack)

        # Right Side Data Table
        right_panel = QVBoxLayout()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Type", "Latitude", "Longitude"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        right_panel.addWidget(QLabel("<b>COORDINATE LIST</b>")); right_panel.addWidget(self.table)

        main_h_layout.addLayout(left_layout, 7); main_h_layout.addLayout(right_panel, 3)

        self.setCentralWidget(central_widget)
        self.draw_grid()
        self.switch_mode(0)
        self.view.mouseDoubleClickEvent = self.handle_map_double_click
        self.scene.selectionChanged.connect(self.handle_selection_event)

    def switch_mode(self, index):
        self.panel_stack.setCurrentIndex(index)
        is_edit = (index == 1)
        for item in self.elements + self.waypoints:
            item.setFlag(item.GraphicsItemFlag.ItemIsMovable, is_edit)

    def draw_grid(self):
        self.scene.clear()
        self.scene.addRect(0, 0, W_PX, H_PX, QPen(Qt.GlobalColor.black, 2))
        font = QFont("Arial", 12, QFont.Weight.Bold)
        self.scene.addText("WEST (FRONT)", font).setPos(CENTER_X_PX-60, 10)
        grid_p = QPen(Qt.GlobalColor.lightGray, 0.5)
        for i in range(-20, 20):
            x, y = CENTER_X_PX + (i*5*PX_PER_M), CENTER_Y_PX + (i*5*PX_PER_M)
            if 0 <= x <= W_PX: self.scene.addLine(x, 0, x, H_PX, grid_p)
            if 0 <= y <= H_PX: self.scene.addLine(0, y, W_PX, y, grid_p)
        self.scene.addLine(CENTER_X_PX, 0, CENTER_X_PX, H_PX, QPen(Qt.GlobalColor.blue, 1, Qt.PenStyle.DashLine))
        self.scene.addLine(0, CENTER_Y_PX, W_PX, CENTER_Y_PX, QPen(Qt.GlobalColor.blue, 1, Qt.PenStyle.DashLine))

    def handle_map_double_click(self, event):
        pos = self.view.mapToScene(event.pos())
        if self.panel_stack.currentIndex() == 0:
            obj = MissionElement(pos.x(), pos.y(), self.refresh_table_data)
            self.scene.addItem(obj); self.elements.append(obj)
        else:
            wp = Waypoint(pos.x(), pos.y(), self.refresh_table_data)
            self.scene.addItem(wp); self.waypoints.append(wp)
        self.refresh_table_data()

    def delete_selected_item(self):
        selected = self.scene.selectedItems()
        if not selected: return
        for item in selected:
            if isinstance(item, MissionElement): self.elements.remove(item)
            elif isinstance(item, Waypoint): self.waypoints.remove(item)
            self.scene.removeItem(item)
        self.refresh_table_data()

    def nudge_selected_item(self):
        selected = self.scene.selectedItems()
        if not selected: return
        try:
            dy_px, dx_px = -float(self.in_lat.text()) * PX_PER_M, float(self.in_lon.text()) * PX_PER_M
            for item in selected: item.setPos(item.pos().x() + dx_px, item.pos().y() + dy_px)
            self.refresh_table_data()
        except: pass

    def add_surveyed_element_by_input(self):
        try:
            t_lat, t_lon = calculate_projection(float(self.in_lat.text()), float(self.in_lon.text()), float(self.in_brg.text()), float(self.in_dist.text()))
            em, nm = latlon_to_meters(t_lat, t_lon)
            px, py = CENTER_X_PX + (nm * PX_PER_M), CENTER_Y_PX + (em * PX_PER_M)
            obj = MissionElement(px, py, self.refresh_table_data)
            self.scene.addItem(obj); self.elements.append(obj)
            self.refresh_table_data()
        except: pass

    def refresh_table_data(self, item=None):
        self.table.setRowCount(0)
        for i, e in enumerate(self.elements):
            e.label.setPlainText(f"O{i+1}")
            self.add_table_row(f"O{i+1}", "Object", e.lat, e.lon)
        for i, w in enumerate(self.waypoints):
            w.label.setPlainText(f"W{i+1}")
            self.add_table_row(f"W{i+1}", "Waypoint", w.lat, w.lon)

    def add_table_row(self, id_str, type_str, lat, lon):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(id_str)); self.table.setItem(row, 1, QTableWidgetItem(type_str))
        self.table.setItem(row, 2, QTableWidgetItem(f"{lat:.7f}")); self.table.setItem(row, 3, QTableWidgetItem(f"{lon:.7f}"))

    def handle_selection_event(self):
        selected = self.scene.selectedItems()
        if selected and self.panel_stack.currentIndex() == 1:
            item = selected[0]
            if isinstance(item, MapItem): self.lbl_move_delta.setText(f"Move Delta: {item.get_displacement_m():.2f}m")

    def save_mission(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Mission", "mission.json", "JSON (*.json)")
        if path:
            data = {"origin": {"lat": ORIGIN_LAT, "lon": ORIGIN_LON}, 
                    "objects": [{"id": f"O{i+1}", "lat": e.lat, "lon": e.lon} for i, e in enumerate(self.elements)],
                    "path_waypoints": [{"id": f"W{i+1}", "lat": w.lat, "lon": w.lon} for i, w in enumerate(self.waypoints)]}
            with open(path, "w") as f: json.dump(data, f, indent=4)

if __name__ == "__main__":
    app = QApplication([]); ex = MainWindow(); ex.resize(1350, 950); ex.show(); app.exec()