import sys
import vlc
import math
import time
import socket
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QTextEdit, QDialog, QVBoxLayout, 
                             QGridLayout, QWidget, QLabel, QMessageBox, QComboBox, QHBoxLayout)
from PyQt5.QtCore import Qt, QTimer, QMutex, QMutexLocker

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

class RTSPViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RTSP Video Viewer (PyQt)")
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
        self.update_lock = QMutex()
        
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
        self.control_layout.addWidget(QLabel("Grid Size:"))
        self.control_layout.addWidget(self.grid_combo)
        self.control_layout.addWidget(self.input_button)
        self.main_layout.addLayout(self.control_layout)
        
        # Grid layout for video streams
        self.grid_layout = QGridLayout()
        self.main_layout.addLayout(self.grid_layout)
        
        # Start monitoring streams
        QTimer.singleShot(5000, self.monitor_streams)
        
    def open_input_dialog(self):
        self.input_button.setEnabled(False)
        dialog = InputDialog(self)
        if dialog.exec_():
            urls_text = dialog.text_edit.toPlainText()
            self.update_streams(urls_text)
        self.input_button.setEnabled(True)
            
    def change_grid_size(self, text):
        # Removed QMutexLocker to prevent deadlock when calling update_streams from within the same thread.
        self.grid_combo.setEnabled(False)
        self.input_button.setEnabled(False)
        try:
            self.grid_size = int(math.sqrt(int(text.split()[0])))
            print(f"Changed grid size to {self.grid_size}x{self.grid_size}")
            # Safe to call without taking the same mutex; update_streams still protects its critical section.
            self.update_streams('\n'.join(self.rtsp_urls))
        finally:
            self.grid_combo.setEnabled(True)
            self.input_button.setEnabled(True)
        
    def check_rtsp_url(self, url):
        try:
            host = url.split('@')[1].split(':')[0] if '@' in url else url.split('//')[1].split(':')[0]
            port = int(url.split(':')[2].split('/')[0]) if len(url.split(':')) > 2 else 554
            with socket.create_connection((host, port), timeout=2):
                print(f"URL {url} is reachable")
                return True
        except Exception as e:
            print(f"URL {url} is unreachable: {str(e)}")
            return False
        
    def update_streams(self, urls_text):
        with QMutexLocker(self.update_lock):
            print("Starting update_streams")
            self.central_widget.setUpdatesEnabled(False)  # Pause GUI rendering
            new_urls = [url.strip() for url in urls_text.strip().split('\n') if url.strip()]
            if len(new_urls) > self.max_streams:
                QMessageBox.warning(self, "Warning", f"Maximum {self.max_streams} streams allowed. Taking first {self.max_streams} URLs.")
                new_urls = new_urls[:self.max_streams]
            print("URLs:", new_urls)
            
            # Stop and release existing players
            for player in self.players:
                if player:
                    try:
                        player.stop()
                        time.sleep(1.0)  # Increased wait time
                        player.release()
                        print("Player stopped and released")
                    except Exception as e:
                        print(f"Error releasing player: {str(e)}")
            self.players = []
            self.stream_status = []
            
            # Reuse or create labels
            required_labels = min(self.grid_size * self.grid_size, self.max_streams)
            current_label_count = len(self.labels)
            if current_label_count < required_labels:
                for _ in range(required_labels - current_label_count):
                    label = CustomLabel(self.central_widget)
                    label.setStyleSheet("background-color: black;")
                    label.setAlignment(Qt.AlignCenter)
                    label.setMinimumSize(320, 240)
                    self.labels.append(label)
            elif current_label_count > required_labels:
                for label in self.labels[required_labels:]:
                    label.deleteLater()
                self.labels = self.labels[:required_labels]
            
            # Create new VLC players
            start_time = time.time()
            for i in range(required_labels):
                print(f"Configuring stream {i}")
                player = self.vlc_instance.media_player_new()
                media = self.vlc_instance.media_new(new_urls[i] if i < len(new_urls) else '')
                media.add_option('avcodec-hw=auto')
                media.add_option('no-audio')
                media.add_option('rtsp-tcp')
                player.set_media(media)
                
                self.players.append(player)
                self.stream_status.append(True if i < len(new_urls) else False)
                
                # Start player if URL exists and is reachable
                if i < len(new_urls) and self.check_rtsp_url(new_urls[i]):
                    for attempt in range(2):
                        try:
                            player.set_hwnd(self.labels[i].winId())
                            if player.play() == -1:
                                raise Exception("Failed to start player")
                            print(f"Started player {i} for {new_urls[i]} (attempt {attempt + 1})")
                            break
                        except Exception as e:
                            print(f"Error starting player {i} (attempt {attempt + 1}): {str(e)}")
                            if attempt == 1:
                                self.stream_status[i] = False
                                self.labels[i].setText(f"Stream Error: {str(e)}")
                            time.sleep(1)
                else:
                    self.labels[i].setText("No Stream" if i >= len(new_urls) else "Unreachable URL")
                    self.stream_status[i] = False
                
            self.rtsp_urls = new_urls
            self.update_grid_layout()
            print(f"Stream initialization took {time.time() - start_time:.2f} seconds")
            self.central_widget.setUpdatesEnabled(True)  # Resume GUI rendering
        
    def update_grid_layout(self):
        print("Starting update_grid_layout")
        if not self.labels:
            print("No streams or windows configured")
            QMessageBox.warning(self, "Warning", "No streams or windows configured")
            return
            
        # Clear existing grid
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            widget.setParent(None)
            self.grid_layout.removeItem(self.grid_layout.itemAt(i))
            
        # Place labels in grid
        for i, label in enumerate(self.labels):
            row = i // self.grid_size
            col = i % self.grid_size
            self.grid_layout.addWidget(label, row, col)
        print("Finished update_grid_layout")
        
    def monitor_streams(self):
        for i, player in enumerate(self.players):
            if player and self.stream_status[i]:
                state = player.get_state()
                if state == vlc.State.Error or state == vlc.State.Ended:
                    print(f"Stream {i} failed: {state}")
                    self.stream_status[i] = False
                    self.labels[i].setText("Stream Error")
                    if i < len(self.rtsp_urls) and self.check_rtsp_url(self.rtsp_urls[i]):
                        for attempt in range(2):
                            try:
                                player.set_hwnd(self.labels[i].winId())
                                if player.play() == -1:
                                    raise Exception("Failed to start player")
                                print(f"Restarted player {i} for {self.rtsp_urls[i]} (attempt {attempt + 1})")
                                self.stream_status[i] = True
                                break
                            except Exception as e:
                                print(f"Error restarting player {i} (attempt {attempt + 1}): {str(e)}")
                                if attempt == 1:
                                    self.stream_status[i] = False
                                    self.labels[i].setText(f"Stream Error: {str(e)}")
                                time.sleep(1)
                elif state == vlc.State.Playing:
                    print(f"Stream {i} is playing")
                else:
                    print(f"Stream {i} state: {state}")
        QTimer.singleShot(5000, self.monitor_streams)
        
    def closeEvent(self, event):
        for player in self.players:
            if player:
                try:
                    player.stop()
                    player.release()
                except Exception as e:
                    print(f"Error releasing player: {str(e)}")
        self.vlc_instance.release()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = RTSPViewer()
    viewer.show()
    sys.exit(app.exec_())