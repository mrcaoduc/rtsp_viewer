import sys
import vlc
import math
import time
import socket
from concurrent.futures import ThreadPoolExecutor
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
    """Worker thread for heavy stream operations"""
    progress_update = pyqtSignal(str)
    layout_ready = pyqtSignal()
    stream_configured = pyqtSignal(int, object, bool, str)  # index, player, status, message
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
        """Check if RTSP URL is reachable"""
        try:
            host = url.split('@')[1].split(':')[0] if '@' in url else url.split('//')[1].split(':')[0]
            port = int(url.split(':')[2].split('/')[0]) if len(url.split(':')) > 2 else 554
            with socket.create_connection((host, port), timeout=2):
                return True
        except Exception:
            return False
    
    def run(self):
        """Perform heavy stream setup operations in background thread"""
        try:
            self.progress_update.emit("Preparing streams...")
            
            # Prepare required number of streams
            required_labels = min(self.grid_size * self.grid_size, self.max_streams)
            
            # Check URLs in parallel using ThreadPoolExecutor
            url_status = {}
            if self.urls:
                self.progress_update.emit("Checking URL connectivity...")
                with ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_url = {executor.submit(self.check_rtsp_url, url): url for url in self.urls}
                    for future in future_to_url:
                        url = future_to_url[future]
                        try:
                            url_status[url] = future.result()
                        except Exception:
                            url_status[url] = False
            
            # Signal that layout can be updated
            self.layout_ready.emit()
            
            # Create and configure players
            for i in range(required_labels):
                self.progress_update.emit(f"Configuring stream {i+1}/{required_labels}...")
                
                player = self.vlc_instance.media_player_new()
                url = self.urls[i] if i < len(self.urls) else ''
                message = ""
                status = False
                
                if url:
                    media = self.vlc_instance.media_new(url)
                    media.add_option('avcodec-hw=auto')
                    media.add_option('no-audio')
                    media.add_option('rtsp-tcp')
                    player.set_media(media)
                    
                    if url_status.get(url, False):
                        status = True
                        message = f"Stream {i+1} ready"
                    else:
                        message = "Unreachable URL"
                else:
                    message = "No Stream"
                
                self.players.append(player)
                self.stream_status.append(status)
                
                # Emit signal for each configured stream
                self.stream_configured.emit(i, player, status, message)
                
                # Small delay to prevent overwhelming the GUI
                self.msleep(100)
            
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
        self.vlc_instance = vlc.Instance('--no-xlib --verbose=2 --network-caching=150 --no-video-title-show '
                                         '--clock-jitter=0 --clock-synchro=0 --rtsp-frame-buffer-size=15000 '
                                         '--rtsp-timeout=5')
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
        
        # Progress bar for operations
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
        """Handle grid size change without blocking GUI"""
        if self.updating:
            return
            
        try:
            new_grid_size = int(math.sqrt(int(text.split()[0])))
            if new_grid_size != self.grid_size:
                self.grid_size = new_grid_size
                print(f"Changed grid size to {self.grid_size}x{self.grid_size}")
                # Use QTimer to defer heavy operation to next event loop iteration
                QTimer.singleShot(0, lambda: self.start_stream_update('\n'.join(self.rtsp_urls)))
        except Exception as e:
            print(f"Error changing grid size: {e}")
    
    def start_stream_update(self, urls_text):
        """Start stream update in background thread"""
        if self.updating:
            return
            
        self.updating = True
        self.set_controls_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
        # Parse URLs
        new_urls = [url.strip() for url in urls_text.strip().split('\n') if url.strip()]
        if len(new_urls) > self.max_streams:
            QMessageBox.warning(self, "Warning", f"Maximum {self.max_streams} streams allowed. Taking first {self.max_streams} URLs.")
            new_urls = new_urls[:self.max_streams]
        
        # Stop existing players gracefully
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
        """Stop existing players without blocking GUI"""
        for player in self.players:
            if player:
                try:
                    player.stop()
                    # Don't call release() immediately, let it stop gracefully
                    QTimer.singleShot(500, lambda p=player: self.release_player(p))
                except Exception as e:
                    print(f"Error stopping player: {e}")
        self.players = []
        self.stream_status = []
    
    def release_player(self, player):
        """Release player after delay"""
        try:
            player.release()
        except Exception as e:
            print(f"Error releasing player: {e}")
    
    def prepare_layout(self):
        """Prepare layout for new streams (called from worker thread)"""
        # This runs in main thread due to Qt's signal-slot mechanism
        required_labels = min(self.grid_size * self.grid_size, self.max_streams)
        current_label_count = len(self.labels)
        
        # Adjust number of labels
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
        """Configure individual stream (called from worker thread)"""
        # This runs in main thread due to Qt's signal-slot mechanism
        if index < len(self.labels):
            self.labels[index].setText(message)
            
            if status and player:
                try:
                    player.set_hwnd(self.labels[index].winId())
                    result = player.play()
                    if result == -1:
                        self.labels[index].setText(f"Stream {index+1} Error")
                        status = False
                    else:
                        print(f"Started player {index}")
                except Exception as e:
                    print(f"Error starting player {index}: {e}")
                    self.labels[index].setText(f"Stream Error: {str(e)}")
                    status = False
            
            # Update internal state
            if index >= len(self.players):
                self.players.extend([None] * (index + 1 - len(self.players)))
                self.stream_status.extend([False] * (index + 1 - len(self.stream_status)))
            
            self.players[index] = player
            self.stream_status[index] = status
    
    def stream_update_finished(self):
        """Called when stream update is complete"""
        self.updating = False
        self.set_controls_enabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ready")
        
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
    
    def set_controls_enabled(self, enabled):
        """Enable/disable controls during operations"""
        self.input_button.setEnabled(enabled)
        self.grid_combo.setEnabled(enabled)
    
    def update_status(self, message):
        """Update status label"""
        self.status_label.setText(message)
        
    def update_grid_layout(self):
        """Update grid layout with current labels"""
        print("Updating grid layout")
        if not self.labels:
            return
            
        # Clear existing grid
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
            
        # Place labels in grid
        for i, label in enumerate(self.labels):
            row = i // self.grid_size
            col = i % self.grid_size
            self.grid_layout.addWidget(label, row, col)
        
        print("Grid layout updated")
        
    def monitor_streams(self):
        """Monitor stream status and restart failed streams"""
        if self.updating:
            QTimer.singleShot(5000, self.monitor_streams)
            return
            
        for i, player in enumerate(self.players):
            if player and i < len(self.stream_status) and self.stream_status[i]:
                try:
                    state = player.get_state()
                    if state == vlc.State.Error or state == vlc.State.Ended:
                        print(f"Stream {i} failed: {state}")
                        self.stream_status[i] = False
                        if i < len(self.labels):
                            self.labels[i].setText("Stream Error - Restarting...")
                        
                        # Attempt restart without blocking GUI
                        QTimer.singleShot(1000, lambda idx=i: self.restart_stream(idx))
                        
                except Exception as e:
                    print(f"Error checking stream {i}: {e}")
                    
        QTimer.singleShot(5000, self.monitor_streams)
    
    def restart_stream(self, index):
        """Restart a failed stream"""
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
                print(f"Error restarting stream {index}: {e}")
                self.labels[index].setText(f"Restart Error: {str(e)}")
        
    def closeEvent(self, event):
        """Clean shutdown"""
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(3000)  # Wait up to 3 seconds
            
        for player in self.players:
            if player:
                try:
                    player.stop()
                    player.release()
                except Exception as e:
                    print(f"Error releasing player: {e}")
        
        try:
            self.vlc_instance.release()
        except Exception as e:
            print(f"Error releasing VLC instance: {e}")
            
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = RTSPViewer()
    viewer.show()
    sys.exit(app.exec_())