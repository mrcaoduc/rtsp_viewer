import sys
import vlc
import math
import time
import socket
import urllib.parse
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QTextEdit, QDialog, QVBoxLayout, 
                             QGridLayout, QWidget, QLabel, QMessageBox, QComboBox, QHBoxLayout, QProgressBar)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal

class CustomLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_fullscreen = False
        self.original_size = (320, 240)
        self.original_pos = None
        
    def mouseDoubleClickEvent(self, event):
        if self.is_fullscreen:
            self.setMinimumSize(*self.original_size)
            self.setMaximumSize(16777215, 16777215)
            self.setGeometry(self.original_pos)
            self.is_fullscreen = False
        else:
            self.original_pos = self.geometry()
            self.setMinimumSize(0, 0)
            self.setMaximumSize(1920, 1080)
            self.setGeometry(self.window().geometry())
            self.is_fullscreen = True
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
    layout_ready = pyqtSignal()
    stream_configured = pyqtSignal(int, object, bool, str)
    finished = pyqtSignal()
    
    def __init__(self, urls, grid_size, vlc_instance, max_streams, parent=None):
        super().__init__(parent)
        self.urls = urls
        self.grid_size = grid_size
        self.vlc_instance = vlc_instance
        self.max_streams = max_streams
        self.players = []
        self.stream_status = []
        
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
            media.parse_with_options(vlc.MediaParseFlag.network, 10000)  # 10s timeout
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
            self.progress_update.emit("Preparing streams...")
            
            required_labels = min(self.grid_size * self.grid_size, self.max_streams)
            
            # Check URLs sequentially
            self.progress_update.emit("Checking URL connectivity...")
            url_status = {url: self.check_rtsp_url(url) and self.validate_media(url) for url in self.urls}
            
            self.layout_ready.emit()
            
            # Configure players sequentially
            for i in range(required_labels):
                self.progress_update.emit(f"Configuring stream {i+1}/{required_labels}...")
                
                player = self.vlc_instance.media_player_new()
                url = self.urls[i] if i < len(self.urls) else ''
                message = ""
                status = False
                
                if url and url_status.get(url, False):
                    media = self.vlc_instance.media_new(url)
                    media.add_option('avcodec-hw=auto')
                    media.add_option('no-audio')
                    media.add_option('rtsp-tcp')
                    media.add_option('no-video-title')
                    player.set_media(media)
                    status = True
                    message = f"Stream {i+1} ready"
                else:
                    message = "No Stream" if not url else "Unreachable or Invalid URL"
                
                self.players.append(player)
                self.stream_status.append(status)
                self.stream_configured.emit(i, player, status, message)
                self.msleep(200)
            
            self.progress_update.emit("Stream setup complete!")
            
        except Exception as e:
            self.progress_update.emit(f"Error: {str(e)}")
        finally:
            self.finished.emit()

class RTSPViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RTSP Video Viewer (PyQt) - Fixed Version")
        self.setGeometry(100, 100, 800, 600)
        
        self.rtsp_urls = []
        self.players = []
        self.labels = []
        self.stream_status = []
        self.max_streams = 8
        self.grid_size = 2
        self.vlc_instance = vlc.Instance('--no-xlib --verbose=2 --network-caching=300 --no-video-title-show '
                                         '--clock-jitter=0 --clock-synchro=0 --rtsp-frame-buffer-size=10000 '
                                         '--rtsp-timeout=10 --aout=dummy --no-audio')
        self.worker = None
        self.updating = False
        
        # Main widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        
        # Control layout
        self.control_layout = QHBoxLayout()
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
        self.main_layout.addLayout(self.grid_layout)
        
        # Start monitoring streams
        QTimer.singleShot(5000, self.monitor_streams)
        
    def open_input_dialog(self):
        if self.updating:
            QMessageBox.information(self, "Info", "Please wait for current operation to complete.")
            return
            
        dialog = InputDialog(self)
        if dialog.exec_():
            urls_text = dialog.text_edit.toPlainText()
            self.start_stream_update(urls_text)
            
    def change_grid_size(self, text):
        if self.updating:
            return
            
        try:
            new_grid_size = int(math.sqrt(int(text.split()[0])))
            if new_grid_size != self.grid_size:
                self.grid_size = new_grid_size
                print(f"Changed grid size to {self.grid_size}x{self.grid_size}")
                QTimer.singleShot(0, lambda: self.start_stream_update('\n'.join(self.rtsp_urls)))
        except Exception as e:
            print(f"Error changing grid size: {str(e)}")
    
    def start_stream_update(self, urls_text):
        if self.updating:
            return
            
        self.updating = True
        self.set_controls_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.central_widget.setUpdatesEnabled(False)
        
        # Parse URLs
        new_urls = [url.strip() for url in urls_text.strip().split('\n') if url.strip()]
        if len(new_urls) > self.max_streams:
            QMessageBox.warning(self, "Warning", f"Maximum {self.max_streams} streams allowed. Taking first {self.max_streams} URLs.")
            new_urls = new_urls[:self.max_streams]
        
        # Stop existing players
        self.stop_existing_players()
        
        # Start worker thread
        self.worker = StreamUpdateWorker(new_urls, self.grid_size, self.vlc_instance, self.max_streams, self)
        self.worker.progress_update.connect(self.update_status)
        self.worker.layout_ready.connect(self.prepare_layout)
        self.worker.stream_configured.connect(self.configure_stream)
        self.worker.finished.connect(self.stream_update_finished)
        self.worker.start()
        
        self.rtsp_urls = new_urls
    
    def stop_existing_players(self):
        for player in self.players:
            if player:
                try:
                    state = player.get_state()
                    if state not in (vlc.State.Stopped, vlc.State.Ended):
                        player.stop()
                        print("Player stopped")
                    time.sleep(2.0)
                    player.release()
                    print("Player released")
                except Exception as e:
                    print(f"Error stopping/releasing player: {str(e)}")
        self.players = []
        self.stream_status = []
    
    def prepare_layout(self):
        required_labels = min(self.grid_size * self.grid_size, self.max_streams)
        current_label_count = len(self.labels)
        
        if current_label_count < required_labels:
            for _ in range(required_labels - current_label_count):
                label = CustomLabel(self.central_widget)
                label.setStyleSheet("background-color: black; color: white; border: 1px solid gray;")
                label.setAlignment(Qt.AlignCenter)
                label.setMinimumSize(320, 240)
                label.setText("Initializing...")
                self.labels.append(label)
        elif current_label_count > required_labels:
            for label in self.labels[required_labels:]:
                label.deleteLater()
            self.labels = self.labels[:required_labels]
        
        self.update_grid_layout()
    
    def configure_stream(self, index, player, status, message):
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
            
            if index >= len(self.players):
                self.players.extend([None] * (index + 1 - len(self.players)))
                self.stream_status.extend([False] * (index + 1 - len(self.stream_status)))
            
            self.players[index] = player
            self.stream_status[index] = status
    
    def stream_update_finished(self):
        self.updating = False
        self.set_controls_enabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ready")
        self.central_widget.setUpdatesEnabled(True)
        
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
    
    def set_controls_enabled(self, enabled):
        self.input_button.setEnabled(enabled)
        self.grid_combo.setEnabled(enabled)
    
    def update_status(self, message):
        self.status_label.setText(message)
        
    def update_grid_layout(self):
        print("Updating grid layout")
        if not self.labels:
            return
            
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
            
        for i, label in enumerate(self.labels):
            row = i // self.grid_size
            col = i % self.grid_size
            self.grid_layout.addWidget(label, row, col)
        
        print("Grid layout updated")
        
    def monitor_streams(self):
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
    
    def restart_stream(self, index):
        if (index < len(self.players) and index < len(self.rtsp_urls) and 
            index < len(self.labels) and self.players[index]):
            try:
                player = self.players[index]
                player.set_hwnd(self.labels[index].winId())
                if player.play() != -1:
                    self.stream_status[index] = True
                    print(f"Restarted stream {index}")
                else:
                    self.labels[index].setText(f"Stream {index+1} Failed")
            except Exception as e:
                print(f"Error restarting stream {index}: {str(e)}")
                self.labels[index].setText(f"Restart Error: {str(e)}")
        
    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(3000)
            
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
            
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = RTSPViewer()
    viewer.show()
    sys.exit(app.exec_())