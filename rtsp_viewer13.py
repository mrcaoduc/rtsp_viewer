import sys
import vlc
import math
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QTextEdit, QDialog, QVBoxLayout, 
                             QGridLayout, QWidget, QLabel, QMessageBox, QComboBox, QHBoxLayout)
from PyQt5.QtCore import Qt, QTimer

class CustomLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_fullscreen = False
        self.original_size = (320, 240)
        self.original_pos = None
        
    def mouseDoubleClickEvent(self, event):
        if self.is_fullscreen:
            self.setMinimumSize(*self.original_size)
            self.setMaximumSize(16777215, 16777215)  # Reset max size
            self.setGeometry(self.original_pos)
            self.is_fullscreen = False
        else:
            self.original_pos = self.geometry()
            self.setMinimumSize(0, 0)
            self.setMaximumSize(1920, 1080)  # Adjust to screen size
            self.setGeometry(self.window().geometry())
            self.is_fullscreen = True
        event.accept()

class InputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter RTSP Links and Grid Size")
        self.setFixedSize(400, 350)
        self.layout = QVBoxLayout()
        
        self.text_edit = QTextEdit()
        self.layout.addWidget(QLabel("RTSP URLs (one per line):"))
        self.layout.addWidget(self.text_edit)
        
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(["1 (1x1)", "4 (2x2)", "9 (3x3)", "16 (4x4)"])
        self.layout.addWidget(QLabel("Select number of windows:"))
        self.layout.addWidget(self.grid_combo)
        
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
        self.max_streams = 8  # Maximum 8 streams
        self.grid_size = 2  # Default 2x2 grid
        self.vlc_instance = vlc.Instance('--no-xlib --verbose=2 --network-caching=3000 --no-video-title-show '
                                         '--clock-jitter=0 --clock-synchro=0 --rtsp-frame-buffer-size=300000')
        
        # Main widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        
        # Input button
        self.input_button = QPushButton("Add RTSP Links")
        self.input_button.clicked.connect(self.open_input_dialog)
        self.main_layout.addWidget(self.input_button)
        
        # Grid layout for video streams
        self.grid_layout = QGridLayout()
        self.main_layout.addLayout(self.grid_layout)
        
        # Start monitoring streams
        QTimer.singleShot(5000, self.monitor_streams)
        
    def open_input_dialog(self):
        dialog = InputDialog(self)
        if dialog.exec_():
            urls_text = dialog.text_edit.toPlainText()
            grid_choice = int(dialog.grid_combo.currentText().split()[0])
            self.grid_size = int(math.sqrt(grid_choice))
            self.update_streams(urls_text)
            
    def update_streams(self, urls_text):
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
                    time.sleep(0.2)  # Wait for clean stop
                    player.release()
                except Exception as e:
                    print(f"Error releasing player: {str(e)}")
        for label in self.labels:
            label.deleteLater()
        self.players = []
        self.labels = []
        self.stream_status = []
        
        # Create new VLC players and labels
        start_time = time.time()
        for i in range(min(len(new_urls), self.grid_size * self.grid_size)):
            player = self.vlc_instance.media_player_new()
            media = self.vlc_instance.media_new(new_urls[i] if i < len(new_urls) else '')
            media.add_option('avcodec-hw=auto')  # Auto hardware decoding
            media.add_option('no-audio')  # Disable audio
            media.add_option('rtsp-tcp')  # Force TCP
            player.set_media(media)
            
            # Create label
            label = CustomLabel(self.central_widget)
            label.setStyleSheet("background-color: black;")
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumSize(320, 240)
            self.labels.append(label)
            self.players.append(player)
            self.stream_status.append(True if i < len(new_urls) else False)
            
            # Start player if URL exists
            if i < len(new_urls):
                self.start_player(player, label, i)
            else:
                label.setText("No Stream")
                
        self.rtsp_urls = new_urls
        self.update_grid_layout()
        print(f"Stream initialization took {time.time() - start_time:.2f} seconds")
        
    def start_player(self, player, label, index):
        try:
            player.set_hwnd(label.winId())  # Windows-specific
            if player.play() == -1:
                raise Exception("Failed to start player")
            print(f"Started player {index} for {self.rtsp_urls[index]}")
        except Exception as e:
            print(f"Error starting player {index}: {str(e)}")
            self.stream_status[index] = False
            label.setText(f"Stream Error: {str(e)}")
            
    def update_grid_layout(self):
        if not self.labels:
            print("No streams or windows configured")
            QMessageBox.warning(self, "Warning", "No streams or windows configured")
            return
            
        # Clear existing grid
        for i in reversed(range(self.grid_layout.count())):
            self.grid_layout.itemAt(i).widget().deleteLater()
            
        # Place labels in grid
        for i, label in enumerate(self.labels):
            row = i // self.grid_size
            col = i % self.grid_size
            self.grid_layout.addWidget(label, row, col)
            
    def monitor_streams(self):
        for i, player in enumerate(self.players):
            if player and self.stream_status[i]:
                state = player.get_state()
                if state == vlc.State.Error or state == vlc.State.Ended:
                    print(f"Stream {i} failed: {state}")
                    self.stream_status[i] = False
                    self.labels[i].setText("Stream Error")
                elif state == vlc.State.Playing:
                    print(f"Stream {i} is playing")
                else:
                    print(f"Stream {i} state: {state}")
        self.central_widget.setUpdatesEnabled(True)
        QApplication.processEvents()
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