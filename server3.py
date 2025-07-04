from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import json
import datetime
import base64
import os
import uuid
import requests

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'static/snapshots'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- KHỞI TẠO BIẾN TOÀN CỤC ---
event_log = []
error_log = []

# --- CẤU HÌNH CAMERA: BAO GỒM RTSP VÀ WEBRTC URL ---
# Quan trọng: Cập nhật dictionary này với link RTSP và ĐẶC BIỆT là WEBRTC URL thực tế.
# Key (ví dụ: "Entrance") nên khớp với ch_name hoặc device_name mà AI Box gửi.
CAMERA_CONFIGS = {
    "Entrance": {
        "rtsp_url": "rtsp://admin:cdi12345@192.168.11.49:5554/live/ch1", # Giữ nguyên RTSP cũ
        "webrtc_url": "ws://127.0.0.1:8889/cam5", # ĐÃ CẬP NHẬT WEBRTC URL THỰC TẾ CỦA BẠN
        "snapshot_url": "http://admin:cdi12345@192.168.11.49/cgi-bin/snapshot.cgi"
    },
    "ExitGate": {
        "rtsp_url": "rtsp://admin:cdi12345@192.168.11.49:5554/live/ch2", # Giữ nguyên RTSP cũ
        "webrtc_url": "ws://127.0.0.1:8889/cam6", # ĐÃ CẬP NHẬT WEBRTC URL THỰC TẾ CỦA BẠN
        "snapshot_url": "http://admin:cdi12345@192.168.11.49/cgi-bin/snapshot.cgi?channel=2"
    },
    # Thêm các cấu hình khác cho các camera/kênh của bạn
}

@app.route('/')
def serve_index():
    return render_template('index2.html')

@app.route('/Apis/AIBirdge/Event/lpr_kr/default.aspx', methods=['POST'])
def handle_event():
    # Sử dụng từ khóa 'global' để chỉ rõ rằng chúng ta đang thao tác với biến toàn cục
    global event_log 
    if request.mimetype == 'multipart/form-data':
        try:
            event_json_str = request.form.get('event_json')

            if event_json_str:
                event_data = json.loads(event_json_str)
                event_data['received_at'] = datetime.datetime.now().isoformat()

                device_name = event_data.get('device_name')
                ch_name = event_data.get('ch_name')
                event_data['rtsp_url_static'] = None
                event_data['webrtc_url_static'] = None
                event_data['snapshot_live_url_static'] = None

                config_key = None
                if ch_name and ch_name in CAMERA_CONFIGS:
                    config_key = ch_name
                elif device_name and device_name in CAMERA_CONFIGS:
                    config_key = device_name
                
                if config_key:
                    event_data['rtsp_url_static'] = CAMERA_CONFIGS[config_key].get('rtsp_url')
                    event_data['webrtc_url_static'] = CAMERA_CONFIGS[config_key].get('webrtc_url')
                    # Nếu vẫn muốn dùng snapshot proxy:
                    if CAMERA_CONFIGS[config_key].get('snapshot_url'):
                        event_data['snapshot_live_url_static'] = f'/api/camera_snapshot_proxy/{config_key}'
                else:
                    print(f"  Warning: No camera configuration found for device '{device_name}' or channel '{ch_name}'")

                attach_snapshot_b64 = event_data.get('Attach Snapshot')
                if attach_snapshot_b64:
                    try:
                        if ',' in attach_snapshot_b64:
                            header, base64_data = attach_snapshot_b64.split(',', 1)
                        else:
                            base64_data = attach_snapshot_b64

                        image_data = base64.b64decode(base64_data)
                        filename = f"snapshot_{uuid.uuid4()}.jpg"
                        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        with open(filepath, 'wb') as f:
                            f.write(image_data)
                        event_data['attach_snapshot_web_url'] = f'/static/snapshots/{filename}'
                        print(f"  Attach Snapshot Saved: {event_data['attach_snapshot_web_url']}")
                    except Exception as e:
                        print(f"  !!! Error saving Attach Snapshot: {e}")
                        event_data['attach_snapshot_web_url'] = None

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
                            obj['object_capture_image_web_url'] = f'/static/snapshots/{obj_filename}'
                            print(f"  Object Capture Image Saved: {obj['object_capture_image_web_url']}")
                        except Exception as e:
                            print(f"  !!! Error saving object capture image: {e}")
                            obj['object_capture_image_web_url'] = None

                event_log.append(event_data) # Thêm vào biến toàn cục

                if len(event_log) > 500:
                    event_log = event_log[-500:]

                print(f"--- New Event Received at: {event_data['received_at']} ---")
                print(f"Device: {event_data.get('device_name')}, Channel: {ch_name}, Event: {event_data.get('event_name')}")
                if event_data.get('rtsp_url_static'):
                    print(f"  Static RTSP URL: {event_data['rtsp_url_static']}")
                if event_data.get('webrtc_url_static'):
                    print(f"  WebRTC URL: {event_data['webrtc_url_static']}")
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
            # global event_log # Không cần ở đây vì không sửa đổi event_log
            global error_log # Khai báo global cho error_log nếu sửa đổi nó
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

@app.route('/Apis/AIBirdge/Error/default.aspx', methods=['POST'])
def handle_error():
    global error_log # Sử dụng từ khóa 'global' cho error_log
    error_data_raw = request.get_data(as_text=True)
    error_info = {
        "raw_error_data": error_data_raw,
        "received_at": datetime.datetime.now().isoformat()
    }
    error_log.append(error_info)
    if len(error_log) > 100:
        error_log = error_log[-100:]

    print(f"--- Error Data Received at: {error_info['received_at']} ---")
    print(error_data_raw)
    print("------------------------------------")
    return jsonify({"status": "success", "message": "Error data received"}), 200

@app.route('/api/events', methods=['GET'])
def get_events():
    # Không cần global ở đây vì chỉ đọc biến
    return jsonify(event_log[-50:][::-1])

@app.route('/api/latest_lpr_info', methods=['GET'])
def get_latest_lpr_info():
    # Không cần global ở đây vì chỉ đọc biến
    latest_event = None
    latest_lp_text = "N/A"
    latest_snapshot_url = None
    latest_rtsp_url = None
    latest_webrtc_url = None
    latest_device_time = "N/A"
    channel_name_for_live_cam = "N/A"

    for event in reversed(event_log):
        if event.get('event_type') in ['LPR-JP', 'License Plate Detected', 'LPR']:
            latest_event = event
            latest_rtsp_url = event.get('rtsp_url_static')
            latest_webrtc_url = event.get('webrtc_url_static')
            latest_device_time = event.get('date_time')
            latest_snapshot_url = event.get('attach_snapshot_web_url')
            channel_name_for_live_cam = event.get('ch_name') or event.get('device_name') or "N/A"

            if event.get('objects'):
                for obj in event['objects']:
                    if obj.get('lp_text'):
                        latest_lp_text = obj['lp_text']
                        if obj.get('object_capture_image_web_url'):
                            latest_snapshot_url = obj['object_capture_image_web_url']
                        break
            break

    return jsonify({
        "last_lp_text": latest_lp_text,
        "last_snapshot_url": latest_snapshot_url,
        "live_cam_rtsp_url": latest_rtsp_url,
        "live_cam_webrtc_url": latest_webrtc_url,
        "last_event_device_time": latest_device_time,
        "channel_name": channel_name_for_live_cam
    })

@app.route('/api/camera_snapshot_proxy/<camera_key>', methods=['GET'])
def get_camera_snapshot_proxy(camera_key):
    config = CAMERA_CONFIGS.get(camera_key)
    if not config or not config.get('snapshot_url'):
        return send_from_directory('static', 'no_signal.jpg'), 404
    
    snapshot_url = config['snapshot_url']
    try:
        response = requests.get(snapshot_url, stream=True, timeout=3)
        response.raise_for_status()
        return response.content, response.status_code, {'Content-Type': response.headers.get('Content-Type', 'image/jpeg')}
    except requests.exceptions.RequestException as e:
        print(f"Error fetching snapshot from {camera_key} ({snapshot_url}): {e}")
        return send_from_directory('static', 'no_signal.jpg'), 500

@app.route('/api/errors', methods=['GET'])
def get_errors():
    # Không cần global ở đây vì chỉ đọc biến
    return jsonify(error_log[-50:][::-1])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)