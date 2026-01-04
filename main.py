import sys
import cv2
import numpy as np
import json
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QSplitter, QFrame, QComboBox, QListWidget, QRadioButton, QButtonGroup)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QRect, QSize, QPointF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QBrush, QAction, QPolygonF, QIcon
from warping import HomographyWarper, TPSWarper

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class ClickableImageLabel(QLabel):
    pointsChanged = pyqtSignal()
    
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.setMinimumSize(400, 300)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("border: 1px solid #3e3e42; background-color: #252526;")
        
        self.original_pixmap = None
        self.points = []  # List of (x, y) in original image coordinates
        self.lines = []   # List of ((x1, y1), (x2, y2))
        self.faces = []   # List of [(x,y), (x,y), (x,y), (x,y)] - 4 points
        self.input_mode = "POINT" # "POINT", "LINE", or "FACE"
        
        self.dragging_idx = -1
        self.dragging_line_idx = -1
        self.dragging_line_end = 0 # 0 for start, 1 for end
        
        self.current_line_start = None
        self.temp_line_end = None
        
        self.dragging_face_idx = -1
        self.dragging_face_corner = -1
        self.current_face_start = None
        self.temp_face_end = None
        
        # Zoom and Pan state
        self.zoom = 1.0
        self.pan_offset = QPoint(0, 0)
        self.last_mouse_pos = QPoint()
        self.panning = False
        
        self.setMouseTracking(True)

    def set_image(self, cv_img):
        height, width, channel = cv_img.shape
        bytes_per_line = 3 * width
        q_img = QImage(cv_img.data, width, height, bytes_per_line, QImage.Format.Format_BGR888)
        self.original_pixmap = QPixmap.fromImage(q_img)
        self.points = []
        self.lines = []
        self.faces = []
        self.reset_view()
        self.update()

    def reset_view(self):
        self.zoom = 1.0
        self.pan_offset = QPoint(0, 0)

    def update_display(self):
        # We don't use setPixmap here because we draw manually in paintEvent
        if not self.original_pixmap:
            self.setText(f"Click to load {self.title}")
        else:
            self.setText("")
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def get_base_scale(self):
        if not self.original_pixmap: return 1.0
        s = self.size()
        ps = self.original_pixmap.size()
        return min(s.width() / ps.width(), s.height() / ps.height())

    def get_transform(self):
        # Transform from Image coordinates to Screen coordinates
        base_scale = self.get_base_scale()
        total_scale = base_scale * self.zoom
        
        # Center of label
        lc = QPointF(self.width() / 2.0, self.height() / 2.0)
        
        # Center of image in image coordinates
        ic = QPointF(self.original_pixmap.width() / 2.0, self.original_pixmap.height() / 2.0)
        
        from PyQt6.QtGui import QTransform
        t = QTransform()
        t.translate(lc.x(), lc.y())
        t.translate(self.pan_offset.x(), self.pan_offset.y())
        t.scale(total_scale, total_scale)
        t.translate(-ic.x(), -ic.y())
        return t

    def screen_to_image(self, pos):
        if not self.original_pixmap: return None
        transform = self.get_transform()
        inv, success = transform.inverted()
        if not success: return None
        
        img_pos = inv.map(QPointF(pos))
        # Clamp to image bounds
        ix = int(max(0, min(self.original_pixmap.width() - 1, img_pos.x())))
        iy = int(max(0, min(self.original_pixmap.height() - 1, img_pos.y())))
        return (ix, iy)

    def image_to_screen(self, img_x, img_y):
        if not self.original_pixmap: return QPoint()
        transform = self.get_transform()
        screen_pos = transform.map(QPointF(img_x, img_y))
        return screen_pos.toPoint()

    def wheelEvent(self, event):
        if not self.original_pixmap: return
        
        delta = event.angleDelta().y()
        zoom_step = 1.15
        
        old_zoom = self.zoom
        if delta > 0:
            self.zoom *= zoom_step
        else:
            self.zoom /= zoom_step
            
        # Clamp zoom
        self.zoom = max(0.1, min(self.zoom, 50.0))
        
        # Adjust pan to zoom relative to mouse cursor
        if old_zoom != self.zoom:
            mouse_pos = event.position()
            lc = QPointF(self.width() / 2.0, self.height() / 2.0)
            
            # Pan_new = P - lc - (P - Pan_old - lc) * (zoom_new / zoom_old)
            ratio = self.zoom / old_zoom
            new_pan = mouse_pos - lc - (mouse_pos - QPointF(self.pan_offset) - lc) * ratio
            self.pan_offset = new_pan.toPoint()
            self.update()

    def mousePressEvent(self, event):
        if not self.original_pixmap: return
        
        if event.button() == Qt.MouseButton.MiddleButton:
            self.panning = True
            self.last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        img_pos = self.screen_to_image(event.position().toPoint())
        if img_pos:
            if event.button() == Qt.MouseButton.LeftButton:
                if self.input_mode == "POINT":
                    # Check if clicking near existing point to move it
                    for i, (px, py) in enumerate(self.points):
                        screen_pt = self.image_to_screen(px, py)
                        if (screen_pt - event.position().toPoint()).manhattanLength() < 15:
                            self.dragging_idx = i
                            return
                    
                    # Otherwise add new point
                    self.points.append(img_pos)
                    self.pointsChanged.emit()
                    self.update()
                elif self.input_mode == "LINE":
                    # Check if clicking near existing line endpoint
                    for i, (start, end) in enumerate(self.lines):
                        s_pos = self.image_to_screen(*start)
                        e_pos = self.image_to_screen(*end)
                        
                        click_pt = event.position().toPoint()
                        
                        if (s_pos - click_pt).manhattanLength() < 15:
                            self.dragging_line_idx = i
                            self.dragging_line_end = 0
                            return
                        if (e_pos - click_pt).manhattanLength() < 15:
                            self.dragging_line_idx = i
                            self.dragging_line_end = 1
                            return

                    # Start drawing new line
                    self.current_line_start = img_pos
                    self.temp_line_end = img_pos
                    self.update()
                
                elif self.input_mode == "FACE":
                    # Check if clicking near existing face corner
                    for i, pts in enumerate(self.faces):
                         for j, (fx, fy) in enumerate(pts):
                              screen_pt = self.image_to_screen(fx, fy)
                              click_pt = event.position().toPoint()
                              if (screen_pt - click_pt).manhattanLength() < 15:
                                   self.dragging_face_idx = i
                                   self.dragging_face_corner = j
                                   return
                    
                    # Start drawing new face (Box drag)
                    self.current_face_start = img_pos
                    self.temp_face_end = img_pos
                    self.update()

            elif event.button() == Qt.MouseButton.RightButton:
                if self.input_mode == "POINT" and self.points:
                    self.points.pop()
                    self.pointsChanged.emit()
                    self.update()
                elif self.input_mode == "LINE" and self.lines:
                    self.lines.pop()
                    self.pointsChanged.emit()
                    self.update()
                elif self.input_mode == "FACE" and self.faces:
                    self.faces.pop()
                    self.pointsChanged.emit()
                    self.update()

    def mouseMoveEvent(self, event):
        if self.panning:
            delta = event.position().toPoint() - self.last_mouse_pos
            self.pan_offset += delta
            self.last_mouse_pos = event.position().toPoint()
            self.update()
            return

        if self.dragging_idx != -1:
            if self.dragging_idx >= len(self.points):
                self.dragging_idx = -1
                return
            img_pos = self.screen_to_image(event.position().toPoint())
            if img_pos:
                self.points[self.dragging_idx] = img_pos
                self.pointsChanged.emit()
                self.update()
        elif self.dragging_line_idx != -1:
            if self.dragging_line_idx >= len(self.lines):
                self.dragging_line_idx = -1
                return
            img_pos = self.screen_to_image(event.position().toPoint())
            if img_pos:
                old_line = self.lines[self.dragging_line_idx]
                if self.dragging_line_end == 0:
                    self.lines[self.dragging_line_idx] = (img_pos, old_line[1])
                else:
                    self.lines[self.dragging_line_idx] = (old_line[0], img_pos)
                self.pointsChanged.emit()
                self.update()
        elif self.dragging_face_idx != -1:
             if self.dragging_face_idx >= len(self.faces):
                 self.dragging_face_idx = -1
                 return
             img_pos = self.screen_to_image(event.position().toPoint())
             if img_pos:
                 face_pts = list(self.faces[self.dragging_face_idx]) 
                 face_pts[self.dragging_face_corner] = img_pos
                 self.faces[self.dragging_face_idx] = face_pts
                 
                 self.pointsChanged.emit()
                 self.update()
                 
        elif self.current_line_start is not None:
             img_pos = self.screen_to_image(event.position().toPoint())
             if img_pos:
                 self.temp_line_end = img_pos
                 self.update()
        elif self.current_face_start is not None:
             img_pos = self.screen_to_image(event.position().toPoint())
             if img_pos:
                 self.temp_face_end = img_pos
                 self.update()

    def mouseReleaseEvent(self, event):
        self.dragging_idx = -1
        self.dragging_line_idx = -1
        self.dragging_face_idx = -1
        
        if self.current_line_start is not None and event.button() == Qt.MouseButton.LeftButton:
             if self.temp_line_end is not None:
                 # Finalize line
                 self.lines.append((self.current_line_start, self.temp_line_end))
                 self.current_line_start = None
                 self.temp_line_end = None
                 self.pointsChanged.emit()
                 self.update()

        if self.current_face_start is not None and event.button() == Qt.MouseButton.LeftButton:
             if self.temp_face_end is not None:
                 # Create 4 points from rect (TL, TR, BR, BL)
                 x1, y1 = self.current_face_start
                 x2, y2 = self.temp_face_end
                 
                 # Normalize so x1<x2, y1<y2 NOT NECESSARY but helpful for winding
                 # We will just take them as corners of a generic rect
                 # TL, TR, BR, BL
                 # Let's enforce winding: TL -> TR -> BR -> BL
                 
                 min_x, max_x = min(x1, x2), max(x1, x2)
                 min_y, max_y = min(y1, y2), max(y1, y2)
                 
                 p1 = (min_x, min_y) # TL
                 p2 = (max_x, min_y) # TR
                 p3 = (max_x, max_y) # BR
                 p4 = (min_x, max_y) # BL
                 
                 self.faces.append([p1, p2, p3, p4])
                 
                 self.current_face_start = None
                 self.temp_face_end = None
                 self.pointsChanged.emit()
                 self.update()
        
        if event.button() == Qt.MouseButton.MiddleButton:
            self.panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        if not self.original_pixmap:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"Click to load {self.title}")
            return
            
        # Draw Image with transform
        transform = self.get_transform()
        painter.setTransform(transform)
        painter.drawPixmap(0, 0, self.original_pixmap)
        
        # Reset transform for drawing markers so they stay same size?
        # Actually, it's better to keep marker size consistent in screen space
        painter.resetTransform()
        
        colors = [Qt.GlobalColor.red, Qt.GlobalColor.green, Qt.GlobalColor.blue, 
                  Qt.GlobalColor.yellow, Qt.GlobalColor.magenta, Qt.GlobalColor.cyan]
        
        for i, (px, py) in enumerate(self.points):
            screen_pos = self.image_to_screen(px, py)
            color = colors[i % len(colors)]
            
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(screen_pos, 6, 6)
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawText(screen_pos + QPoint(8, 8), str(i + 1))

        # Draw Lines
        for i, (start, end) in enumerate(self.lines):
             s_pos = self.image_to_screen(*start)
             e_pos = self.image_to_screen(*end)
             
             painter.setPen(QPen(Qt.GlobalColor.cyan, 3))
             painter.drawLine(s_pos, e_pos)
             painter.setBrush(QBrush(Qt.GlobalColor.cyan))
             painter.drawEllipse(s_pos, 4, 4)
             painter.drawEllipse(e_pos, 4, 4)
             
             mid = (s_pos + e_pos) / 2
             painter.setPen(QPen(Qt.GlobalColor.white, 1))
             painter.drawText(mid, f"L{i+1}")

        # Draw temp line
        if self.current_line_start and self.temp_line_end:
             s_pos = self.image_to_screen(*self.current_line_start)
             e_pos = self.image_to_screen(*self.temp_line_end)
             painter.setPen(QPen(Qt.GlobalColor.yellow, 2, Qt.PenStyle.DashLine))
             painter.drawLine(s_pos, e_pos)
             
        # Draw Faces
        for i, pts in enumerate(self.faces):
             poly_pts = [self.image_to_screen(*p) for p in pts]
             
             # Fill
             painter.setPen(Qt.PenStyle.NoPen)
             painter.setBrush(QColor(0, 255, 0, 50))
             painter.drawPolygon(QPolygonF([QPointF(p) for p in poly_pts]))
             
             # Outline
             painter.setPen(QPen(Qt.GlobalColor.green, 2))
             painter.setBrush(Qt.BrushStyle.NoBrush)
             painter.drawPolygon(QPolygonF([QPointF(p) for p in poly_pts]))
             
             # Corners
             for j, p in enumerate(poly_pts):
                 painter.setBrush(Qt.GlobalColor.green)
                 painter.drawEllipse(p, 4, 4)
                 
             # Center Label
             center = QPointF(0,0)
             for p in poly_pts: center += QPointF(p)
             center /= 4.0
             painter.setPen(Qt.GlobalColor.white)
             painter.drawText(center.toPoint(), f"F{i+1}")
             
        # Draw Temp Face Box
        if self.current_face_start and self.temp_face_end:
             s = self.image_to_screen(*self.current_face_start)
             e = self.image_to_screen(*self.temp_face_end)
             rect = QRect(s, e).normalized()
             painter.setPen(QPen(Qt.GlobalColor.yellow, 2, Qt.PenStyle.DashLine))
             painter.setBrush(Qt.BrushStyle.NoBrush)
             painter.drawRect(rect)

class ComparisonSlider(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.img1 = None # Historical (Base)
        self.img2 = None # Modern (Warped)
        self.slider_pos = 0.5
        self.dragging = False
        self.mode = "Slide" # "Slide", "Ghost", "Diff"
        self.setMinimumHeight(400)
        self.setMouseTracking(True)

    def set_images(self, img1, img2):
        self.img1 = img1
        self.img2 = img2
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def mousePressEvent(self, event):
        if self.mode == "Slide":
            self.dragging = True
            self.update_slider(event.position().x())

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.update_slider(event.position().x())

    def mouseReleaseEvent(self, event):
        self.dragging = False

    def update_slider(self, x):
        self.slider_pos = max(0.0, min(1.0, x / self.width()))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.img1 is None or self.img2 is None:
            painter.fillRect(self.rect(), QColor(30, 30, 30))
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Pending Alignment (Need 4+ points)")
            return

        # Prepare images to fit
        rect = self.rect()
        h1, w1 = self.img1.shape[:2]
        # We assume img2 is already warped to img1's dimensions
        
        # Convert CV images to QImage
        q_img1 = QImage(self.img1.data, w1, h1, 3 * w1, QImage.Format.Format_BGR888)
        q_img2 = QImage(self.img2.data, w1, h1, 3 * w1, QImage.Format.Format_BGR888)
        
        pix1 = QPixmap.fromImage(q_img1).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pix2 = QPixmap.fromImage(q_img2).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        target_rect = pix1.rect()
        target_rect.moveCenter(self.rect().center())

        if self.mode == "Slide":
            painter.drawPixmap(target_rect, pix1)
            
            # Clip and draw second image
            slider_clip_x = int(self.slider_pos * self.width())
            clip_rect = QRect(0, 0, slider_clip_x, self.height())
            
            painter.setClipRect(clip_rect)
            painter.drawPixmap(target_rect, pix2)
            painter.setClipping(False)
            
            # Draw slider line
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.drawLine(slider_clip_x, 0, slider_clip_x, self.height())
            
        elif self.mode == "Ghost":
            painter.drawPixmap(target_rect, pix1)
            painter.setOpacity(0.5)
            painter.drawPixmap(target_rect, pix2)
            painter.setOpacity(1.0)
            
        elif self.mode == "Diff":
            # Simple diff for visualization
            diff = cv2.absdiff(self.img1, self.img2)
            q_diff = QImage(diff.data, w1, h1, 3 * w1, QImage.Format.Format_BGR888)
            pix_diff = QPixmap.fromImage(q_diff).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(target_rect, pix_diff)

class ImageAlignmentApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Historical Image Aligner")
        self.resize(1200, 900)
        
        
        # Set Icon
        icon_path = resource_path("icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.cv_img1 = None
        self.cv_img2 = None
        self.warped_img2 = None
        
        self.img1_path = None
        self.img2_path = None
        
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Header / Load buttons
        top_ctrl = QHBoxLayout()
        
        # Project Controls
        self.btn_load_proj = QPushButton("Load Project")
        self.btn_save_proj = QPushButton("Save Project")
        self.btn_load_proj.clicked.connect(self.load_project)
        self.btn_save_proj.clicked.connect(self.save_project)
        top_ctrl.addWidget(self.btn_load_proj)
        top_ctrl.addWidget(self.btn_save_proj)
        
        # Separator or spacer
        top_ctrl.addSpacing(20)
        
        self.btn_load1 = QPushButton("Load Historical (A)")
        self.btn_load2 = QPushButton("Load Modern (B)")
        self.btn_load1.clicked.connect(lambda: self.load_image(1))
        self.btn_load2.clicked.connect(lambda: self.load_image(2))
        top_ctrl.addWidget(self.btn_load1)
        top_ctrl.addWidget(self.btn_load2)
        
        self.btn_save = QPushButton("Save Warped Result")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save_result)

        top_ctrl.addWidget(self.btn_save)

        # Warp Method Selector
        self.warp_combo = QComboBox()
        self.warp_combo.addItems(["Perspective (Rigid)", "TPS (Elastic)"])
        self.warp_combo.currentTextChanged.connect(lambda _: self.run_warp())
        top_ctrl.addWidget(QLabel("Warp Method:"))
        top_ctrl.addWidget(self.warp_combo)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Slide", "Ghost", "Diff"])
        self.mode_combo.currentTextChanged.connect(self.change_mode)
        top_ctrl.addWidget(QLabel("View Mode:"))
        top_ctrl.addWidget(self.mode_combo)
        
        main_layout.addLayout(top_ctrl)
        
        # Input Panes
        input_pane_layout = QHBoxLayout()
        input_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.pane1 = ClickableImageLabel("Historical Image")
        self.pane2 = ClickableImageLabel("Modern Image")
        self.pane1.pointsChanged.connect(self.sync_points)
        self.pane2.pointsChanged.connect(self.sync_points)
        input_splitter.addWidget(self.pane1)
        input_splitter.addWidget(self.pane2)
        
        input_splitter.addWidget(self.pane2)

        # Input Mode Selector (Points vs Lines)
        mode_panel = QFrame()
        mode_layout = QHBoxLayout(mode_panel)
        mode_layout.setContentsMargins(0, 5, 0, 5)
        
        self.btn_mode_point = QRadioButton("Points [•]")
        self.btn_mode_line = QRadioButton("Lines [/]")
        self.btn_mode_face = QRadioButton("Faces [□]")
        self.btn_mode_point.setChecked(True)
        
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.btn_mode_point)
        self.mode_group.addButton(self.btn_mode_line)
        self.mode_group.addButton(self.btn_mode_face)
        
        self.mode_group.buttonClicked.connect(self.change_input_mode)
        
        mode_layout.addWidget(QLabel("Input Tool:"))
        mode_layout.addWidget(self.btn_mode_point)
        mode_layout.addWidget(self.btn_mode_line)
        mode_layout.addWidget(self.btn_mode_face)
        mode_layout.addStretch()
        
        # Point List Panel
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(5, 0, 5, 0)
        list_layout.addWidget(QLabel("Point Pairs:"))
        self.point_list = QListWidget()
        self.point_list.setMinimumWidth(200)
        list_layout.addWidget(self.point_list)
        self.btn_delete_pt = QPushButton("Delete Selected Pair")
        self.btn_delete_pt.clicked.connect(self.delete_selected_points)
        list_layout.addWidget(self.btn_delete_pt)
        
        self.btn_clear_pts = QPushButton("Clear All Points")
        self.btn_clear_pts.clicked.connect(self.clear_all_points)
        list_layout.addWidget(self.btn_clear_pts)
        
        input_pane_layout.addWidget(input_splitter, 1)
        
        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0,0,0,0)
        side_layout.addWidget(mode_panel)
        side_layout.addWidget(list_panel)
        
        input_pane_layout.addWidget(side_panel, 0)
        
        # Comparison View
        self.comparison_view = ComparisonSlider()
        
        vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        container = QWidget()
        container.setLayout(input_pane_layout)
        vertical_splitter.addWidget(container)
        vertical_splitter.addWidget(self.comparison_view)
        vertical_splitter.setStretchFactor(0, 1)
        vertical_splitter.setStretchFactor(1, 2)
        
        main_layout.addWidget(vertical_splitter)
        
        self.statusBar().showMessage("Load images to begin. Right-click to undo points. Drag to move.")

    def load_image(self, idx):
        path, _ = QFileDialog.getOpenFileName(self, "Open Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.tiff)")
        if path:
            img = cv2.imread(path)
            if img is not None:
                if idx == 1:
                    self.cv_img1 = img
                    self.img1_path = path
                    self.pane1.set_image(img)
                else:
                    self.cv_img2 = img
                    self.img2_path = path
                    self.pane2.set_image(img)
                self.run_warp()

    def change_mode(self, mode):
        self.comparison_view.set_mode(mode)

    def change_input_mode(self):
        if self.btn_mode_point.isChecked():
            mode = "POINT"
        elif self.btn_mode_line.isChecked():
            mode = "LINE"
        else:
            mode = "FACE"
            
        self.pane1.input_mode = mode
        self.pane2.input_mode = mode
        self.statusBar().showMessage(f"Switched to {mode} mode.")

    def sync_points(self):
        # Update point list
        self.point_list.clear()
        
        pts1 = self.pane1.points
        pts2 = self.pane2.points
        
        # List Points
        max_pts = max(len(pts1), len(pts2))
        for i in range(max_pts):
            p1_str = f"({pts1[i][0]}, {pts1[i][1]})" if i < len(pts1) else "---"
            p2_str = f"({pts2[i][0]}, {pts2[i][1]})" if i < len(pts2) else "---"
            self.point_list.addItem(f"Pt {i+1}: {p1_str} -> {p2_str}")
            
        # List Lines
        lns1 = self.pane1.lines
        lns2 = self.pane2.lines
        max_lns = max(len(lns1), len(lns2))
        for i in range(max_lns):
            l1_str = "Line" if i < len(lns1) else "---"
            l2_str = "Line" if i < len(lns2) else "---"
        for i in range(max_lns):
            l1_str = "Line" if i < len(lns1) else "---"
            l2_str = "Line" if i < len(lns2) else "---"
            self.point_list.addItem(f"Ln {i+1}: {l1_str} -> {l2_str}")
            
        # List Faces
        fcs1 = self.pane1.faces
        fcs2 = self.pane2.faces
        max_fcs = max(len(fcs1), len(fcs2))
        for i in range(max_fcs):
            f1_str = "Face" if i < len(fcs1) else "---"
            f2_str = "Face" if i < len(fcs2) else "---"
            self.point_list.addItem(f"F {i+1}: {f1_str} -> {f2_str}")
            
        self.run_warp()

    def delete_selected_points(self):
        idx = self.point_list.currentRow()
        if idx == -1: return
            
        # Determine if Point or Line based on index
        pts1 = self.pane1.points
        pts2 = self.pane2.points
        max_pts = max(len(pts1), len(pts2))
        
        lns1 = self.pane1.lines
        lns2 = self.pane2.lines
        max_lns = max(len(lns1), len(lns2))
        
        if idx < max_pts:
            # It's a Point
            if idx < len(self.pane1.points):
                self.pane1.points.pop(idx)
            if idx < len(self.pane2.points):
                self.pane2.points.pop(idx)
        elif idx < max_pts + max_lns:
            # It's a Line
            line_idx = idx - max_pts
            if line_idx < len(self.pane1.lines):
                self.pane1.lines.pop(line_idx)
            if line_idx < len(self.pane2.lines):
                self.pane2.lines.pop(line_idx)
        else:
            # It's a Face
            face_idx = idx - max_pts - max_lns
            if face_idx < len(self.pane1.faces):
                self.pane1.faces.pop(face_idx)
            if face_idx < len(self.pane2.faces):
                self.pane2.faces.pop(face_idx)
                
        self.pane1.update()
        self.pane2.update()
        self.sync_points()

    def clear_all_points(self):
        self.pane1.points = []
        self.pane2.points = []
        self.pane1.lines = []
        self.pane2.lines = []
        self.pane1.faces = []
        self.pane2.faces = []
        self.pane1.update()
        self.pane2.update()
        self.sync_points()
        self.statusBar().showMessage("All points, lines, and faces cleared.")

    def run_warp(self):
        # Collect all points: Explicit Points + Line Endpoints
        pts1 = list(self.pane1.points)
        pts2 = list(self.pane2.points)
        
        # Add line endpoints (Start -> Start, End -> End)
        # We assume lines are drawn in same direction loosely
        n_lines = min(len(self.pane1.lines), len(self.pane2.lines))
        for i in range(n_lines):
            l1_start, l1_end = self.pane1.lines[i]
            l2_start, l2_end = self.pane2.lines[i]
            
            pts1.append(l1_start)
            pts1.append(l1_end)
            pts2.append(l2_start)
            pts2.append(l2_end)

        # Add face corners (4 points per face)
        n_faces = min(len(self.pane1.faces), len(self.pane2.faces))
        for i in range(n_faces):
            # p1..p4
            for j in range(4):
                pts1.append(self.pane1.faces[i][j])
                pts2.append(self.pane2.faces[i][j])
        
        # We need same number of points and at least 4
        n = min(len(pts1), len(pts2))
        if n >= 4 and self.cv_img1 is not None and self.cv_img2 is not None:
            # Prepare points in (N, 2) format for Warpers
            # Pts are typically list of tuples or list of lists, convert to numpy
            src_pts = np.array(pts2[:n], dtype=np.float32)
            dst_pts = np.array(pts1[:n], dtype=np.float32)
            
            method = self.warp_combo.currentText()
            warper = None
            
            if "TPS" in method:
                warper = TPSWarper()
            else:
                warper = HomographyWarper()
                
            h, w = self.cv_img1.shape[:2]
            
            self.statusBar().showMessage("Warping...")
            self.warped_img2 = warper.warp(self.cv_img2, src_pts, dst_pts, (w, h))

            if self.warped_img2 is not None:
                self.comparison_view.set_images(self.cv_img1, self.warped_img2)
                self.btn_save.setEnabled(True)
                self.statusBar().showMessage(f"Alignment calculated using {n} constraints ({method}).")
            else:
                self.btn_save.setEnabled(False)
                self.statusBar().showMessage("Warping calculation failed.")
        else:
            self.btn_save.setEnabled(False)
            self.comparison_view.set_images(self.cv_img1, None)
            if self.cv_img1 is not None and self.cv_img2 is not None:
                self.statusBar().showMessage(f"Select at least 4 constraints. ({len(pts1)}/{len(pts2)} selected)")

    def save_result(self):
        if self.warped_img2 is not None:
            path, _ = QFileDialog.getSaveFileName(self, "Export Warped Image", "warped_result.png", "PNG Images (*.png);;JPG Images (*.jpg);;All Files (*)")
            if path:
                cv2.imwrite(path, self.warped_img2)
                self.statusBar().showMessage(f"Exported to {path}")

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "project.json", "JSON Files (*.json)")
        if not path:
            return
            
        data = {
            "img1_path": self.img1_path,
            "img2_path": self.img2_path,
            "pane1": {
                "points": self.pane1.points,
                "lines": self.pane1.lines,
                "faces": self.pane1.faces
            },
            "pane2": {
                "points": self.pane2.points,
                "lines": self.pane2.lines,
                "faces": self.pane2.faces
            },
            "warp_method": self.warp_combo.currentIndex()
        }
        
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=4)
            self.statusBar().showMessage(f"Project saved to {path}")
        except Exception as e:
            self.statusBar().showMessage(f"Error saving project: {e}")

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Project", "", "JSON Files (*.json)")
        if not path:
            return
            
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                
            # Load Images
            if data.get("img1_path") and os.path.exists(data.get("img1_path")):
                self.img1_path = data["img1_path"]
                self.cv_img1 = cv2.imread(self.img1_path)
                self.pane1.set_image(self.cv_img1)
            
            if data.get("img2_path") and os.path.exists(data.get("img2_path")):
                self.img2_path = data["img2_path"]
                self.cv_img2 = cv2.imread(self.img2_path)
                self.pane2.set_image(self.cv_img2)
                
            # Restore Data
            # JSON loads lists as lists. We need to convert back to appropriate types if needed (tuples vs lists).
            # Python lists are fine for our logic, but let's be careful about tuple vs list if downstream expects tuple.
            # Points: list of (x,y)
            # Lines: list of ((x1,y1), (x2,y2))
            # Faces: list of [(x,y)...]
            
            # Helper to convert list of lists to list of tuples/points
            def to_tuples(lst):
                return [tuple(x) for x in lst]
                
            def to_lines(lst):
                return [(tuple(start), tuple(end)) for start, end in lst]
                
            def to_faces(lst):
                # Faces are list of 4 tuples
                return [[tuple(p) for p in face] for face in lst]

            if "pane1" in data:
                self.pane1.points = to_tuples(data["pane1"].get("points", []))
                self.pane1.lines = to_lines(data["pane1"].get("lines", []))
                self.pane1.faces = to_faces(data["pane1"].get("faces", []))
                self.pane1.update()
                
            if "pane2" in data:
                self.pane2.points = to_tuples(data["pane2"].get("points", []))
                self.pane2.lines = to_lines(data["pane2"].get("lines", []))
                self.pane2.faces = to_faces(data["pane2"].get("faces", []))
                self.pane2.update()
                
            self.warp_combo.setCurrentIndex(data.get("warp_method", 0))
                
            self.sync_points()
            self.statusBar().showMessage(f"Project loaded from {path}")
            
        except Exception as e:
            self.statusBar().showMessage(f"Error loading project: {e}")
            print(e)


# -----------------------------
# Modern Dark Theme Stylesheet
# -----------------------------
DARK_THEME_QSS = """
/* Global Application Defaults */
QWidget {
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', sans-serif;
    font-size: 14px;
}

/* Main Window Background */
QMainWindow, QDialog {
    background-color: #1e1e1e;
}

/* Tooltips */
QToolTip {
    background-color: #2d2d30;
    color: #f1f1f1;
    border: 1px solid #3e3e42;
    padding: 4px;
}

/* Buttons */
QPushButton {
    background-color: #333333;
    border: 1px solid #3e3e42;
    border-radius: 4px;
    padding: 6px 12px;
    min-width: 80px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #3e3e42;
    border-color: #555555;
}
QPushButton:pressed {
    background-color: #252526;
    border-color: #007acc;
}
QPushButton:disabled {
    background-color: #252526;
    color: #666666;
    border-color: #333333;
}

/* Primary Action Buttons (if we want to style specific ones, we can use ObjectName, 
   but for now let's make all buttons decent) */

/* Line Edits & Scroll Areas */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: #252526;
    border: 1px solid #3e3e42;
    color: #e0e0e0;
    border-radius: 3px;
    padding: 4px;
}
QLineEdit:focus {
    border: 1px solid #007acc;
}


/* ComboBox */
QComboBox {
    background-color: #252526;
    border: 1px solid #3e3e42;
    border-radius: 4px;
    padding: 4px 8px;
    min-width: 6em;
}
QComboBox:hover {
    border-color: #555555;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
    background: transparent;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid #e0e0e0;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background-color: #252526;
    color: #e0e0e0;
    selection-background-color: #3e3e42;
    selection-color: #ffffff;
    border: 1px solid #3e3e42;
}

/* List Widget */
QListWidget {
    background-color: #252526;
    border: 1px solid #3e3e42;
    border-radius: 4px;
    outline: none;
}
QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #2d2d30;
}
QListWidget::item:selected {
    background-color: #3e3e42; /* Selection Color */
    color: #ffffff;
    border-left: 3px solid #007acc;
}
QListWidget::item:hover {
    background-color: #2d2d30;
}

/* Group Boxes & Frames */
QGroupBox {
    border: 1px solid #3e3e42;
    border-radius: 4px;
    margin-top: 1.5em;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top center;
    padding: 0 5px;
    color: #aaaaaa;
}

/* Scrollbars - The 'Premium' feel often comes from custom scrollbars */
QScrollBar:vertical {
    background-color: #1e1e1e;
    width: 12px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background-color: #424242;
    min-height: 20px;
    border-radius: 6px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background-color: #686868;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Splitter */
QSplitter::handle {
    background-color: #2d2d30;
    width: 2px;
}
QSplitter::handle:hover {
    background-color: #007acc;
}

/* Status Bar */
QStatusBar {
    background-color: #007acc;
    color: #ffffff;
    font-weight: bold;
}
"""

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME_QSS) # Apply Theme
    window = ImageAlignmentApp()
    window.show()
    sys.exit(app.exec())
