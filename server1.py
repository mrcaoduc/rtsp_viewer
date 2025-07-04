from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import json
import datetime
import base64
import os
import uuid # To generate unique file names

app = Flask(__name__)
CORS(app)

# Configure the folder to store captured images
UPLOAD_FOLDER = 'static/snapshots' # Changed from 'captures' to 'snapshots' for clarity
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

event_log = []
error_log = []

# --- CẤU HÌNH RTSP URL TĨNH (THỦ CÔNG) ---
# Bạn sẽ cần cập nhật dictionary này với các link RTSP thực tế của từng thiết bị/kênh.
# Key có thể là device_name hoặc ch_name để dễ mapping.
# Ví dụ: { "Camera_001": "rtsp://admin:password@192.168.1.10:554/stream1" }
RTSP_LINKS = {
    "Gate_Entrance": "rtsp://admin:cdi12345@192.168.11.49:8445/live/ch1",
    "Gate_Exit": "rtsp://admin:cdi12345@192.168.11.49:8445/live/ch2",
    # Thêm các cặp key-value khác ở đây nếu bạn có nhiều thiết bị/kênh
}

# Add endpoint to serve index1.html
@app.route('/')
def serve_index():
    return render_template('index1.html')

# Main endpoint to receive event data
@app.route('/Apis/AIBirdge/Event/lpr_kr/default.aspx', methods=['POST'])
def handle_event():
    if request.mimetype == 'multipart/form-data':
        try:
            event_json_str = request.form.get('event_json')

            if event_json_str:
                event_data = json.loads(event_json_str)
                event_data['received_at'] = datetime.datetime.now().isoformat()

                # --- GÁN RTSP URL TĨNH DỰA TRÊN DEVICE/CHANNEL NAME ---
                # Cố gắng tìm RTSP link dựa trên device_name hoặc ch_name
                device_name = event_data.get('device_name')
                ch_name = event_data.get('ch_name')
                event_data['rtsp_url_static'] = None # Mặc định là None

                if device_name and device_name in RTSP_LINKS:
                    event_data['rtsp_url_static'] = RTSP_LINKS[device_name]
                elif ch_name and ch_name in RTSP_LINKS:
                    event_data['rtsp_url_static'] = RTSP_LINKS[ch_name]
                else:
                    print(f"  Warning: No static RTSP link found for device '{device_name}' or channel '{ch_name}'")


                # --- Xử lý Attach Snapshot (Base64) ---
                # Giả định AI Box gửi trường "Attach Snapshot" với dữ liệu base64
                attach_snapshot_b64 = event_data.get('Attach Snapshot') # Tên trường chính xác như AI Box gửi
                if attach_snapshot_b64:
                    try:
                        # Handle potential "data:image/jpeg;base64," prefix
                        if ',' in attach_snapshot_b64:
                            header, base64_data = attach_snapshot_b64.split(',', 1)
                        else:
                            base64_data = attach_snapshot_b64

                        image_data = base64.b64decode(base64_data)
                        filename = f"snapshot_{uuid.uuid4()}.jpg" # Unique file name for snapshot
                        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        with open(filepath, 'wb') as f:
                            f.write(image_data)
                        # Store the web URL of the saved image for frontend
                        event_data['attach_snapshot_web_url'] = f'/static/snapshots/{filename}'
                        print(f"  Attach Snapshot Saved: {event_data['attach_snapshot_web_url']}")
                    except Exception as e:
                        print(f"  !!! Error saving Attach Snapshot: {e}")
                        event_data['attach_snapshot_web_url'] = None # Set to None on error


                # --- Xử lý ảnh chụp từng đối tượng (Nếu có và AI Box gửi) ---
                # Giả định AI Box có thể gửi 'object_capture_image_data' trong mỗi object
                # (Phần này giữ nguyên như trước, nếu AI Box không gửi thì sẽ là None)
                objects = event_data.get('objects', [])
                for obj in objects:
                    object_capture_b64 = obj.get('object_capture_image_data')
                    if object_capture_b64:
                        try:
                            if ',' in object_capture_b64:
                                header, base64_data = object_capture_b64.split(',', 1)
                            else:
                                base64_data = object_capture_b64

                            obj_image_data = base64.b64decode(base64_data)
                            obj_filename = f"{uuid.uuid4()}_obj.jpg"
                            obj_filepath = os.path.join(app.config['UPLOAD_FOLDER'], obj_filename)
                            with open(obj_filepath, 'wb') as f:
                                f.write(obj_image_data)
                            obj['object_capture_image_web_url'] = f'/static/snapshots/{obj_filename}' # Update folder name
                            print(f"  Object Capture Image Saved: {obj['object_capture_image_web_url']}")
                        except Exception as e:
                            print(f"  !!! Error saving object capture image: {e}")
                            obj['object_capture_image_web_url'] = None


                event_log.append(event_data)

                print(f"--- New Event Received at: {event_data['received_at']} ---")
                print(f"Device: {event_data.get('device_name')}, Event: {event_data.get('event_name')}")
                if event_data.get('rtsp_url_static'):
                    print(f"  Static RTSP URL: {event_data['rtsp_url_static']}")
                if event_data.get('attach_snapshot_web_url'):
                    print(f"  Attach Snapshot URL: {event_data['attach_snapshot_web_url']}")
                if event_data.get('objects'):
                    for obj in event_data['objects']:
                        print(f"  LP Text: {obj.get('lp_text')}, Group: {obj.get('group')}")
                        if obj.get('object_capture_image_web_url'):
                            print(f"    Object Snapshot URL: {obj['object_capture_image_web_url']}")
                print("---------------------------------------")

                return jsonify({"status": "success", "message": "Event received and processed"}), 200
            else:
                return jsonify({"status": "error", "message": "Missing 'event_json' field"}), 400
        except json.JSONDecodeError:
            return jsonify({"status": "error", "message": "Invalid JSON format in 'event_json'"}), 400
        except Exception as e:
            error_info = {
                "error_type": str(type(e)),
                "message": str(e),
                "received_at": datetime.datetime.now().isoformat(),
                "request_data": request.form.to_dict()
            }
            error_log.append(error_info)
            print(f"!!! Error processing event: {str(e)} !!!")
            return jsonify({"status": "error", "message": f"An internal error occurred: {str(e)}"}), 500
    else:
        return jsonify({"status": "error", "message": "Content-Type must be multipart/form-data"}), 415

# Endpoint for errors from AI Box (unchanged)
@app.route('/Apis/AIBirdge/Error/default.aspx', methods=['POST'])
def handle_error():
    error_data_raw = request.get_data(as_text=True)
    error_info = {
        "raw_error_data": error_data_raw,
        "received_at": datetime.datetime.now().isoformat()
    }
    error_log.append(error_info)

    print(f"--- Error Data Received at: {error_info['received_at']} ---")
    print(error_data_raw)
    print("------------------------------------")
    return jsonify({"status": "success", "message": "Error data received"}), 200

# API to get event list for frontend (unchanged)
@app.route('/api/events', methods=['GET'])
def get_events():
    return jsonify(event_log[-50:][::-1])

# API to get error list for frontend (unchanged)
@app.route('/api/errors', methods=['GET'])
def get_errors():
    return jsonify(error_log[-50:][::-1])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)