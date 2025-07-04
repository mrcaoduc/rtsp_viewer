import sys
import vlc
import math
import time
import socket
import urllib.parse
import json
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QTextEdit, QDialog, QVBoxLayout, 
                             QGridLayout, QWidget, QLabel, QMessageBox, QComboBox, QHBoxLayout, QProgressBar, 
                             QSizePolicy, QDesktopWidget, QLineEdit, QInputDialog, QMenu, QAction)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QRect
from PyQt5.QtGui import QResizeEvent

class CustomLabel(QLabel):
    def __init__(self, parent=None, camera_id=None):
        super().__init__(parent)
        self.is_fullscreen = False
        self.original_pos = None
        self.aspect_ratio = 4 / 3  # Default 4:3
        self.camera_id = camera_id
        self.setStyleSheet("background-color: black; color: white; border: 0px; margin: 0px; padding: 0px;")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setContentsMargins(0, 0, 0, 0)
        self.setAutoFillBackground(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
    
    def show_context_menu(self, pos):
        menu = QMenu(self)
        change_url_action = QAction("Change RTSP URL", self)
        change_url_action.triggered.connect(self.change_rtsp_url)
        menu.addAction(change_url_action)
        menu.exec_(self.mapToGlobal(pos))
    
    def change_rtsp_url(self):
        url, ok = QInputDialog.getText(self, "Change RTSP URL", "Enter new RTSP URL:", QLineEdit.Normal, "")
        if ok and url.strip():
            self.window().change_stream_url(self.camera_id, url.strip())
    
    def mouseDoubleClickEvent(self, event):
        screen = QDesktopWidget().screenGeometry()
        max_width, max_height = screen.width(), screen.height() - 50
        try:
            if self.is_fullscreen:
                self.setGeometry(self.original_pos)
                self.is_fullscreen = False
            else:
                self.original_pos = self.geometry()
                new_geometry = QRect(0, 0, min(self.window().width(), max_width), min(self.window().height(), max_height))
                self.setGeometry(new_geometry)
                self.is_fullscreen = True
        except Exception as e:
            print(f"Error in mouseDoubleClickEvent: {str(e)}")
        event.accept()

class InputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter RTSP Links")
        self.setFixedSize(400, 300)
        self.layout = QVBoxLayout()
        self.text_edit = QTextEdit()
        self.layout.addWidget(QLabel("RTSP URLs (one per line):"))
        self.layout.addWidget(self.text_edit)
        self.submit_button = QPushButton("Submit")
        self.submit_button.clicked.connect(self.accept)
        self.layout.addWidget(self.submit_button)
        self.setLayout(self.layout)

class StreamUpdateWorker(QThread):
    progress_update = pyqtSignal(str)
    stream_configured = pyqtSignal(int, object, bool, str)
    finished = pyqtSignal()
    
    def __init__(self, url, index, vlc_instance, parent=None):
        super().__init__(parent)
        self.url = url
        self.index = index
        self.vlc_instance = vlc_instance
    
    def check_rtsp_url(self, url):
        try:
            parsed_url = urllib.parse.urlparse(url)
            host = parsed_url.hostname
            port = parsed_url.port or 554
            with socket.create_connection((host, port), timeout=3):
                print(f"URL {url} is reachable")
                return True
        except Exception as e:
            print(f"URL {url} is unreachable: {str(e)}")
            return False
    
    def validate_media(self, url):
        try:
            media = self.vlc_instance.media_new(url)
            media.add_option('rtsp-tcp')
            media.parse_with_options(vlc.MediaParseFlag.network, 10000)
            state = media.get_state()
            parsed = media.is_parsed()
            media.release()
            if state == vlc.State.Error or not parsed:
                print(f"Invalid media for {url}: state={state}")
                return False
            print(f"Valid media for {url}")
            return True
        except Exception as e:
            print(f"Error validating media for {url}: {str(e)}")
            return False
    
    def run(self):
        try:
            self.progress_update.emit(f"Configuring stream {self.index + 1}...")
            player = self.vlc_instance.media_player_new()
            message = ""
            status = False
            
            if self.url and self.check_rtsp_url(self.url) and self.validate_media(self.url):
                media = self.vlc_instance.media_new(self.url)
                media.add_option('avcodec-hw=nvidia')
                media.add_option('no-audio')
                media.add_option('rtsp-tcp')
                media.add_option('no-video-title')
                media.add_option('ffmpeg-threads=2')
                media.add_option('avcodec-fast')
                player.set_media(media)
                status = True
                message = f"Stream {self.index + 1} ready"
            else:
                message = "No Stream" if not self.url else "Unreachable or Invalid URL"
            
            self.stream_configured.emit(self.index, player, status, message)
            self.progress_update.emit(f"Stream {self.index + 1} setup complete!")
        except Exception as e:
            self.progress_update.emit(f"Error: {str(e)}")
        finally:
            self.finished.emit()

class RTSPViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RTSP Video Viewer (VMS Prototype)")
        self.setGeometry(100, 100, 800, 600)
        
        self.rtsp_urls = []
        self.players = []
        self.labels = []
        self.stream_status = []
        self.max_streams = 8
        self.grid_size = 2
        self.vlc_instance = vlc.Instance('--no-xlib --verbose=2 --network-caching=2000 --rtsp-caching=2000 --live-caching=1500 '
                                         '--no-video-title-show --clock-jitter=0 --clock-synchro=0 '
                                         '--rtsp-frame-buffer-size=200000 --rtsp-timeout=15 --aout=dummy --no-audio')
        self.workers = []
        self.updating = False
        
        # Main widget and layout
        self.central_widget = QWidget()
        self.central_widget.setStyleSheet("background-color: black; margin: 0px; padding: 0px;")
        self.central_widget.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Control layout
        self.control_layout = QHBoxLayout()
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        self.control_layout.setSpacing(0)
        self.input_button = QPushButton("Add RTSP Links")
        self.input_button.clicked.connect(self.open_input_dialog)
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(["1 (1x1)", "4 (2x2)", "9 (3x3)"])
        self.grid_combo.currentTextChanged.connect(self.change_grid_size)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("Ready")
        
        self.control_layout.addWidget(QLabel("Grid Size:"))
        self.control_layout.addWidget(self.grid_combo)
        self.control_layout.addWidget(self.input_button)
        self.control_layout.addStretch()
        self.control_layout.addWidget(self.status_label)
        
        self.main_layout.addLayout(self.control_layout)
        self.main_layout.addWidget(self.progress_bar)
        
        # Grid layout for video streams
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(0)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addLayout(self.grid_layout)
        self.main_layout.setStretchFactor(self.grid_layout, 1)
        
        # Load saved configuration
        self.load_config()
        
        # Start monitoring streams
        QTimer.singleShot(5000, self.monitor_streams)
        
    def load_config(self):
        try:
            with open("vms_config.json", "r") as f:
                config = json.load(f)
                self.rtsp_urls = config.get("rtsp_urls", [])
                self.grid_size = config.get("grid_size", 2)
                self.grid_combo.setCurrentText(f"{self.grid_size * self.grid_size} ({self.grid_size}x{self.grid_size})")
                if self.rtsp_urls:
                    self.start_stream_update('\n'.join(self.rtsp_urls))
        except FileNotFoundError:
            print("No config file found")
        except Exception as e:
            print(f"Error loading config: {str(e)}")
    
    def save_config(self):
        try:
            config = {"rtsp_urls": self.rtsp_urls, "grid_size": self.grid_size}
            with open("vms_config.json", "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {str(e)}")
    
    def open_input_dialog(self):
        if self.updating:
            QMessageBox.information(self, "Info", "Please wait for current operation to complete.")
            return
            
        dialog = InputDialog(self)
        if dialog.exec_():
            urls_text = dialog.text_edit.toPlainText()
            self.start_stream_update(urls_text)
    
    def change_grid_size(self, text):
        try:
            if self.updating:
                return
            new_grid_size = int(math.sqrt(int(text.split()[0])))
            if new_grid_size != self.grid_size:
                self.grid_size = new_grid_size
                print(f"Changed grid size to {self.grid_size}x{self.grid_size}")
                self.update_grid_layout()
                self.save_config()
        except Exception as e:
            print(f"Error changing grid size: {str(e)}")
    
    def start_stream_update(self, urls_text):
        try:
            if self.updating:
                return
                
            self.updating = True
            self.set_controls_enabled(False)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            
            # Parse URLs
            new_urls = [url.strip() for url in urls_text.strip().split('\n') if url.strip()]
            if len(new_urls) > self.max_streams:
                QMessageBox.warning(self, "Warning", f"Maximum {self.max_streams} streams allowed. Taking first {self.max_streams} URLs.")
                new_urls = new_urls[:self.max_streams]
            
            # Stop existing players
            self.stop_existing_players()
            
            # Update labels and players
            required_labels = min(self.grid_size * self.grid_size, self.max_streams)
            current_label_count = len(self.labels)
            
            if current_label_count < required_labels:
                for i in range(current_label_count, required_labels):
                    label = CustomLabel(self.central_widget, camera_id=i)
                    label.setText("Initializing...")
                    self.labels.append(label)
                    self.players.append(None)
                    self.stream_status.append(False)
            elif current_label_count > required_labels:
                for label in self.labels[required_labels:]:
                    label.deleteLater()
                self.labels = self.labels[:required_labels]
                self.players = self.players[:required_labels]
                self.stream_status = self.stream_status[:required_labels]
            
            self.rtsp_urls = new_urls
            self.workers = [None] * required_labels
            
            for i in range(required_labels):
                url = self.rtsp_urls[i] if i < len(self.rtsp_urls) else ''
                worker = StreamUpdateWorker(url, i, self.vlc_instance, self)
                worker.progress_update.connect(self.update_status)
                worker.stream_configured.connect(self.configure_stream)
                worker.finished.connect(lambda idx=i: self.worker_finished(idx))
                self.workers[i] = worker
                worker.start()
            
            self.update_grid_layout()
            self.save_config()
        except Exception as e:
            print(f"Error in start_stream_update: {str(e)}")
    
    def change_stream_url(self, index, url):
        try:
            if index < len(self.labels) and index < len(self.players):
                if self.players[index]:
                    try:
                        state = self.players[index].get_state()
                        if state not in (vlc.State.Stopped, vlc.State.Ended):
                            self.players[index].stop()
                        self.players[index].release()
                    except Exception as e:
                        print(f"Error stopping player {index}: {str(e)}")
                
                self.rtsp_urls[index] = url
                worker = StreamUpdateWorker(url, index, self.vlc_instance, self)
                worker.progress_update.connect(self.update_status)
                worker.stream_configured.connect(self.configure_stream)
                worker.finished.connect(lambda: self.worker_finished(index))
                self.workers[index] = worker
                worker.start()
                self.save_config()
        except Exception as e:
            print(f"Error in change_stream_url: {str(e)}")
    
    def stop_existing_players(self):
        try:
            for worker in self.workers:
                if worker and worker.isRunning():
                    worker.terminate()
                    worker.wait(3000)
            
            for player in self.players:
                if player:
                    try:
                        state = player.get_state()
                        if state not in (vlc.State.Stopped, vlc.State.Ended):
                            player.stop()
                        player.release()
                    except Exception as e:
                        print(f"Error stopping/releasing player: {str(e)}")
            self.players = [None] * len(self.labels)
            self.stream_status = [False] * len(self.labels)
            self.workers = [None] * len(self.labels)
        except Exception as e:
            print(f"Error in stop_existing_players: {str(e)}")
    
    def configure_stream(self, index, player, status, message):
        try:
            if index < len(self.labels):
                self.labels[index].setText(message)
                
                if status and player:
                    for attempt in range(3):
                        try:
                            player.set_hwnd(self.labels[index].winId())
                            if player.play() == -1:
                                raise Exception("Failed to start player")
                            print(f"Started player {index} (attempt {attempt + 1})")
                            break
                        except Exception as e:
                            print(f"Error starting player {index} (attempt {attempt + 1}): {str(e)}")
                            if attempt == 2:
                                self.labels[index].setText(f"Stream Error: {str(e)}")
                                status = False
                            time.sleep(3.0)
                
                self.players[index] = player
                self.stream_status[index] = status
        except Exception as e:
            print(f"Error in configure_stream: {str(e)}")
    
    def worker_finished(self, index):
        try:
            if index < len(self.workers):
                self.workers[index] = None
                if all(worker is None or not worker.isRunning() for worker in self.workers):
                    self.updating = False
                    self.set_controls_enabled(True)
                    self.progress_bar.setVisible(False)
                    self.status_label.setText("Ready")
                    self.central_widget.setUpdatesEnabled(True)
        except Exception as e:
            print(f"Error in worker_finished: {str(e)}")
    
    def set_controls_enabled(self, enabled):
        try:
            self.input_button.setEnabled(enabled)
            self.grid_combo.setEnabled(enabled)
        except Exception as e:
            print(f"Error in set_controls_enabled: {str(e)}")
    
    def update_status(self, message):
        try:
            self.status_label.setText(message)
        except Exception as e:
            print(f"Error in update_status: {str(e)}")
        
    def update_grid_layout(self):
        print("Updating grid layout")
        try:
            if not self.labels:
                return
                
            for i in reversed(range(self.grid_layout.count())):
                item = self.grid_layout.itemAt(i)
                if item and item.widget():
                    item.widget().setParent(None)
            
            screen = QDesktopWidget().screenGeometry()
            max_width, max_height = screen.width(), screen.height() - 50
            window_size = self.central_widget.size()
            control_height = self.control_layout.sizeHint().height()
            grid_width = min(window_size.width(), max_width)
            grid_height = min(window_size.height() - control_height, max_height)
            
            # Calculate cell dimensions to fill grid exactly without rounding errors
            cell_width = grid_width / self.grid_size
            cell_height = grid_height / self.grid_size
            if self.labels:
                target_height = cell_height
                cell_height = min(cell_height, cell_width / self.labels[0].aspect_ratio)
                cell_width = cell_height * self.labels[0].aspect_ratio
            
            # Adjust to fill grid precisely
            adjusted_width = cell_width * self.grid_size
            adjusted_height = cell_height * self.grid_size
            if adjusted_width < grid_width:
                cell_width = grid_width / self.grid_size
                cell_height = cell_width / self.labels[0].aspect_ratio if self.labels else target_height
            if adjusted_height < grid_height:
                cell_height = grid_height / self.grid_size
                cell_width = cell_height * self.labels[0].aspect_ratio if self.labels else grid_width / self.grid_size
            
            for i, label in enumerate(self.labels):
                row = i // self.grid_size
                col = i % self.grid_size
                label_pos = QRect(int(col * cell_width), int(row * cell_height), int(cell_width), int(cell_height))
                label.setGeometry(label_pos)
                self.grid_layout.addWidget(label, row, col, 1, 1)
            
            print("Grid layout updated")
        except Exception as e:
            print(f"Error in update_grid_layout: {str(e)}")
        
    def resizeEvent(self, event: QResizeEvent):
        try:
            if not self.updating:
                self.update_grid_layout()
            super().resizeEvent(event)
        except Exception as e:
            print(f"Error in resizeEvent: {str(e)}")
    
    def monitor_streams(self):
        try:
            if self.updating:
                QTimer.singleShot(5000, self.monitor_streams)
                return
                
            for i, player in enumerate(self.players):
                if player and i < len(self.stream_status) and self.stream_status[i]:
                    try:
                        state = player.get_state()
                        if state in (vlc.State.Error, vlc.State.Ended):
                            print(f"Stream {i} failed: {state}")
                            self.stream_status[i] = False
                            if i < len(self.labels):
                                self.labels[i].setText("Stream Error - Restarting...")
                            QTimer.singleShot(1000, lambda idx=i: self.restart_stream(idx))
                    except Exception as e:
                        print(f"Error checking stream {i}: {str(e)}")
                        
            QTimer.singleShot(5000, self.monitor_streams)
        except Exception as e:
            print(f"Error in monitor_streams: {str(e)}")
    
    def restart_stream(self, index):
        try:
            if (index < len(self.players) and index < len(self.rtsp_urls) and 
                index < len(self.labels) and self.players[index]):
                player = self.players[index]
                player.set_hwnd(self.labels[index].winId())
                if player.play() != -1:
                    self.stream_status[index] = True
                    print(f"Restarted stream {index}")
                else:
                    self.labels[index].setText(f"Stream {index+1} Failed")
        except Exception as e:
            print(f"Error restarting stream {index}: {str(e)}")
            if index < len(self.labels):
                self.labels[index].setText(f"Restart Error: {str(e)}")
        
    def closeEvent(self, event):
        try:
            for worker in self.workers:
                if worker and worker.isRunning():
                    worker.terminate()
                    worker.wait(3000)
                
            for player in self.players:
                if player:
                    try:
                        state = player.get_state()
                        if state not in (vlc.State.Stopped, vlc.State.Ended):
                            player.stop()
                        player.release()
                    except Exception as e:
                        print(f"Error releasing player: {str(e)}")
            
            try:
                self.vlc_instance.release()
            except Exception as e:
                print(f"Error releasing VLC instance: {str(e)}")
            
            self.save_config()
            event.accept()
        except Exception as e:
            print(f"Error in closeEvent: {str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = RTSPViewer()
    viewer.show()
    sys.exit(app.exec_())