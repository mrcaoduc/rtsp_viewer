import websocket

def on_open(ws):
    print("✅ WebSocket connection opened")

def on_error(ws, error):
    print("❌ Error:", error)

def on_close(ws, close_status_code, close_msg):
    print("🔒 Connection closed")

def on_message(ws, message):
    print("📩 Message received:", message)

if __name__ == "__main__":
    ws_url = "ws://192.168.11.221:8889/cam5"  # <-- Đổi URL này đúng với WebSocket server của bạn

    try:
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_error=on_error,
            on_close=on_close,
            on_message=on_message
        )
        ws.run_forever()
    except Exception as e:
        print("❌ Error:", e)
