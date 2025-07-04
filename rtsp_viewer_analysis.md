# RTSP Viewer Code Analysis - Issues and Solutions

## Main Problem Identified

The application hangs when changing the grid layout because **heavy synchronous operations are being performed in the main GUI thread**. This violates a fundamental GUI programming principle: never block the main thread with long-running operations.

## Critical Issues

### 1. **Main Thread Blocking in `change_grid_size()`**
```python
def change_grid_size(self, text):
    with QMutexLocker(self.update_lock):  # ❌ Mutex in GUI thread
        self.grid_combo.setEnabled(False)
        self.input_button.setEnabled(False)
        try:
            self.grid_size = int(math.sqrt(int(text.split()[0])))
            print(f"Changed grid size to {self.grid_size}x{self.grid_size}")
            self.update_streams('\n'.join(self.rtsp_urls))  # ❌ Heavy operation in main thread
        finally:
            self.grid_combo.setEnabled(True)
            self.input_button.setEnabled(True)
```

**Problem**: `update_streams()` performs:
- VLC player stopping/starting (blocking operations)
- Network connectivity checks (2-second timeouts per URL)
- GUI updates while disabled
- All in the main thread!

### 2. **Synchronous Network Operations**
```python
def check_rtsp_url(self, url):
    try:
        # ... parsing logic ...
        with socket.create_connection((host, port), timeout=2):  # ❌ 2-second block per URL
            print(f"URL {url} is reachable")
            return True
    except Exception as e:
        print(f"URL {url} is unreachable: {str(e)}")
        return False
```

**Problem**: With multiple URLs, this can block the GUI for 2+ seconds per URL.

### 3. **Heavy VLC Operations in Main Thread**
```python
def update_streams(self, urls_text):
    with QMutexLocker(self.update_lock):  # ❌ Mutex lock in main thread
        # ... setup code ...
        
        # Stop and release existing players
        for player in self.players:
            if player:
                try:
                    player.stop()
                    time.sleep(1.0)  # ❌ 1-second sleep in main thread!
                    player.release()  # ❌ Potentially blocking
```

**Problem**: Stopping multiple VLC players + sleep calls = several seconds of GUI freeze.

### 4. **GUI Updates Disabled During Heavy Operations**
```python
self.central_widget.setUpdatesEnabled(False)  # ❌ GUI becomes unresponsive
# ... heavy operations ...
self.central_widget.setUpdatesEnabled(True)
```

**Problem**: Combined with blocking operations, this makes the app appear completely frozen.

## Root Cause

When user changes the grid size dropdown:
1. `change_grid_size()` is called in main GUI thread
2. It acquires a mutex lock
3. It calls `update_streams()` which:
   - Stops all VLC players (with 1-second sleeps)
   - Checks network connectivity for each URL (2-second timeouts)
   - Recreates players and starts them
4. All of this blocks the main thread for 5-15+ seconds
5. GUI becomes completely unresponsive

## Solutions

### 1. **Move Heavy Operations to Worker Thread**
```python
from PyQt5.QtCore import QThread, pyqtSignal

class StreamUpdateWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self, urls, grid_size, parent=None):
        super().__init__(parent)
        self.urls = urls
        self.grid_size = grid_size
    
    def run(self):
        # Perform all heavy operations here
        pass
```

### 2. **Asynchronous Network Checks**
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def check_rtsp_url_async(self, url):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(executor, self.check_rtsp_url, url)
```

### 3. **Progressive UI Updates**
```python
def change_grid_size(self, text):
    # Only do lightweight operations in main thread
    self.grid_combo.setEnabled(False)
    self.grid_size = int(math.sqrt(int(text.split()[0])))
    
    # Start worker thread for heavy operations
    self.start_stream_update_worker()
```

### 4. **Remove Mutex from GUI Thread**
The mutex should only be used for protecting shared data between threads, not in the main GUI thread signal handlers.

## Immediate Fix

The quickest fix is to use `QTimer.singleShot(0, ...)` to defer heavy operations:

```python
def change_grid_size(self, text):
    self.grid_combo.setEnabled(False)
    self.grid_size = int(math.sqrt(int(text.split()[0])))
    # Defer heavy work to next event loop iteration
    QTimer.singleShot(0, lambda: self.update_streams_deferred())
```

This would at least prevent the complete GUI freeze, though the proper solution is to use worker threads.