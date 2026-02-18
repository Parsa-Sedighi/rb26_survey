import json
import math
from typing import List, Tuple
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPen, QBrush, QDoubleValidator
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGraphicsView, QGraphicsScene,
    QGraphicsEllipseItem, QGraphicsLineItem,
    QFileDialog, QMessageBox, QLineEdit
)

# Constants
GRID_SIZE_M = 100.0
PX_PER_M = 8.0
W_PX = H_PX = int(GRID_SIZE_M * PX_PER_M)
R_EARTH = 6371000.0 

# ===== Math Engine =====

def get_meters_per_deg(lat):
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat))
    return m_lat, m_lon

def latlon_to_local_xy(origin_lat, origin_lon, target_lat, target_lon):
    m_lat, m_lon = get_meters_per_deg(origin_lat)
    dy = (target_lat - origin_lat) * m_lat
    dx = (target_lon - origin_lon) * m_lon
    return dx, dy

def local_xy_to_latlon(origin_lat, origin_lon, x_m, y_m):
    m_lat, m_lon = get_meters_per_deg(origin_lat)
    t_lat = origin_lat + (y_m / m_lat)
    t_lon = origin_lon + (x_m / m_lon)
    return t_lat, t_lon

def calculate_forward_geodesic(lat1, lon1, bearing, distance):
    φ1, λ1 = math.radians(lat1), math.radians(lon1)
    θ, δ = math.radians(bearing), distance / R_EARTH
    φ2 = math.asin(math.sin(φ1) * math.cos(δ) + math.cos(φ1) * math.sin(δ) * math.cos(θ))
    λ2 = λ1 + math.atan2(math.sin(θ) * math.sin(δ) * math.cos(φ1), math.cos(δ) - math.sin(φ1) * math.sin(φ2))
    return math.degrees(φ2), math.degrees(λ2)

# ===== UI Components =====

class WaypointGraphic(QGraphicsEllipseItem):
    """A waypoint that can be dragged to fine-tune estimations."""
    def __init__(self, wp_id, x_px, y_px, parent_ui):
        super().__init__(-5, -5, 10, 10)
        self.wp_id = wp_id
        self.parent_ui = parent_ui
        self.setPos(x_px, y_px)
        self.setBrush(QBrush(Qt.GlobalColor.red))
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable | self.GraphicsItemFlag.ItemSendsGeometryChanges)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged:
            self.parent_ui.update_waypoint_coords(self.wp_id, self.pos())
        return super().itemChange(change, value)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboBoat Pre-Water Surveyor")
        self.scene = QGraphicsScene(0, 0, W_PX, H_PX)
        self.view = QGraphicsView(self.scene)
        
        self.waypoints_data = [] # List of dicts

        # UI Layout
        self.origin_lat = QLineEdit(placeholderText="Origin Lat")
        self.origin_lon = QLineEdit(placeholderText="Origin Lon")
        self.my_lat = QLineEdit(placeholderText="Surveyor Lat")
        self.my_lon = QLineEdit(placeholderText="Surveyor Lon")
        self.bearing = QLineEdit(placeholderText="Brg (°)")
        self.dist = QLineEdit(placeholderText="Dist (m)")

        btn_set_origin = QPushButton("Set Origin to Me")
        btn_project = QPushButton("Add Projected Waypoint")
        btn_save = QPushButton("Save Mission JSON")
        btn_clear = QPushButton("Clear")

        btn_set_origin.clicked.connect(self.set_origin_to_me)
        btn_project.clicked.connect(self.add_waypoint)
        btn_save.clicked.connect(self.save_json)
        btn_clear.clicked.connect(self.clear_all)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(self.view)
        
        top = QHBoxLayout()
        top.addWidget(QLabel("Origin:"))
        top.addWidget(self.origin_lat); top.addWidget(self.origin_lon)
        top.addWidget(btn_set_origin)
        layout.addLayout(top)

        mid = QHBoxLayout()
        mid.addWidget(QLabel("Obs:"))
        mid.addWidget(self.my_lat); mid.addWidget(self.my_lon)
        mid.addWidget(self.bearing); mid.addWidget(self.dist)
        mid.addWidget(btn_project)
        layout.addLayout(mid)

        bot = QHBoxLayout()
        bot.addStretch(); bot.addWidget(btn_save); bot.addWidget(btn_clear)
        layout.addLayout(bot)

        self.setCentralWidget(root)
        self.draw_grid()

    def set_origin_to_me(self):
        self.origin_lat.setText(self.my_lat.text())
        self.origin_lon.setText(self.my_lon.text())

    def m_to_px(self, x, y):
        return (W_PX/2) + (x * PX_PER_M), (H_PX/2) - (y * PX_PER_M)

    def px_to_m(self, px_x, px_y):
        return (px_x - W_PX/2) / PX_PER_M, (H_PX/2 - px_y) / PX_PER_M

    def draw_grid(self):
        self.scene.clear()
        self.scene.addRect(0, 0, W_PX, H_PX, QPen(Qt.GlobalColor.black, 2))
        for i in range(1, 20):
            s = i * 5 * PX_PER_M
            self.scene.addLine(s, 0, s, H_PX, QPen(Qt.GlobalColor.lightGray, 1))
            self.scene.addLine(0, s, W_PX, s, QPen(Qt.GlobalColor.lightGray, 1))
        self.scene.addLine(W_PX/2, 0, W_PX/2, H_PX, QPen(Qt.GlobalColor.blue, 2))
        self.scene.addLine(0, H_PX/2, W_PX, H_PX/2, QPen(Qt.GlobalColor.blue, 2))

    def add_waypoint(self):
        try:
            o_lat, o_lon = float(self.origin_lat.text()), float(self.origin_lon.text())
            m_lat, m_lon = float(self.my_lat.text()), float(self.my_lon.text())
            brg, dst = float(self.bearing.text()), float(self.dist.text())

            t_lat, t_lon = calculate_forward_geodesic(m_lat, m_lon, brg, dst)
            tx, ty = latlon_to_local_xy(o_lat, o_lon, t_lat, t_lon)
            px, py = self.m_to_px(tx, ty)

            wp_id = len(self.waypoints_data)
            wp_item = WaypointGraphic(wp_id, px, py, self)
            self.scene.addItem(wp_item)
            
            self.waypoints_data.append({"lat": t_lat, "lon": t_lon, "x": tx, "y": ty})
        except:
            QMessageBox.critical(self, "Error", "Invalid inputs")

    def update_waypoint_coords(self, wp_id, pos):
        o_lat, o_lon = float(self.origin_lat.text()), float(self.origin_lon.text())
        mx, my = self.px_to_m(pos.x(), pos.y())
        t_lat, t_lon = local_xy_to_latlon(o_lat, o_lon, mx, my)
        self.waypoints_data[wp_id] = {"lat": t_lat, "lon": t_lon, "x": mx, "y": my}

    def save_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save", "waypoints.json", "JSON (*.json)")
        if path:
            data = {"origin": {"lat": self.origin_lat.text(), "lon": self.origin_lon.text()}, "points": self.waypoints_data}
            with open(path, "w") as f: json.dump(data, f, indent=4)

    def clear_all(self):
        self.waypoints_data = []
        self.draw_grid()

if __name__ == "__main__":
    app = QApplication([])
    win = MainWindow(); win.show(); app.exec()