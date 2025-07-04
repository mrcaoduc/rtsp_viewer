from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import json
import datetime
import base64
import os
import uuid

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'static/snapshots'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

event_log = []
error_log = []

# --- CẤU HÌNH RTSP URL TĨNH (THỦ CÔNG) ---
# Quan trọng: Cập nhật dictionary này với các link RTSP thực tế của từng kênh (ch_name) hoặc thiết bị (device_name) của bạn.
# Key nên khớp với ch_name hoặc device_name mà AI Box gửi.
RTSP_LINKS = {
    "Entrance": "rtsp://admin:cdi12345@192.168.11.49:5554/live/ch1", # Thay IP và thông tin đăng nhập của bạn
    "ExitGate": "rtsp://admin:cdi12345@192.168.11.49:5554/live/ch2",
    # Thêm các cặp key-value khác ở đây cho các camera khác của bạn
}

@app.route('/')
def serve_index():
    return render_template('index2.html')

@app.route('/Apis/AIBirdge/Event/lpr_kr/default.aspx', methods=['POST'])
def handle_event():
    if request.mimetype == 'multipart/form-data':
        try:
            event_json_str = request.form.get('event_json')

            if event_json_str:
                event_data = json.loads(event_json_str)
                event_data['received_at'] = datetime.datetime.now().isoformat()

                # GÁN RTSP URL TĨNH DỰA TRÊN CH_NAME HOẶC DEVICE_NAME
                device_name = event_data.get('device_name')
                ch_name = event_data.get('ch_name')
                event_data['rtsp_url_static'] = None

                if ch_name and ch_name in RTSP_LINKS:
                    event_data['rtsp_url_static'] = RTSP_LINKS[ch_name]
                elif device_name and device_name in RTSP_LINKS:
                    event_data['rtsp_url_static'] = RTSP_LINKS[device_name]
                else:
                    print(f"  Warning: No static RTSP link found for device '{device_name}' or channel '{ch_name}'")

                # Xử lý Attach Snapshot (Base64)
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

                # Xử lý ảnh chụp từng đối tượng (nếu có và AI Box gửi)
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

                event_log.append(event_data)

                # Cắt bớt event_log để không tốn quá nhiều bộ nhớ (giữ 500 sự kiện gần nhất)
                if len(event_log) > 500:
                    event_log = event_log[-500:]

                print(f"--- New Event Received at: {event_data['received_at']} ---")
                print(f"Device: {event_data.get('device_name')}, Channel: {ch_name}, Event: {event_data.get('event_name')}")
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

@app.route('/Apis/AIBirdge/Error/default.aspx', methods=['POST'])
def handle_error():
    error_data_raw = request.get_data(as_text=True)
    error_info = {
        "raw_error_data": error_data_raw,
        "received_at": datetime.datetime.now().isoformat()
    }
    error_log.append(error_info)
    if len(error_log) > 100: # Cắt bớt log lỗi
        error_log = error_log[-100:]

    print(f"--- Error Data Received at: {error_info['received_at']} ---")
    print(error_data_raw)
    print("------------------------------------")
    return jsonify({"status": "success", "message": "Error data received"}), 200

@app.route('/api/events', methods=['GET'])
def get_events():
    return jsonify(event_log[-50:][::-1]) # 50 sự kiện gần nhất cho bảng

# --- API MỚI CHO THÔNG TIN HIỂN THỊ BÊN PHẢI ---
@app.route('/api/latest_lpr_info', methods=['GET'])
def get_latest_lpr_info():
    latest_event = None
    latest_lp_text = "N/A"
    latest_snapshot_url = None
    latest_rtsp_url = None
    latest_device_time = "N/A"

    # Duyệt từ sự kiện mới nhất để tìm LPR hợp lệ
    for event in reversed(event_log): # Duyệt ngược từ cuối danh sách (mới nhất)
        if event.get('event_type') in ['LPR-JP', 'License Plate Detected', 'LPR']: # Thêm các loại event LPR của bạn
            latest_event = event
            latest_rtsp_url = event.get('rtsp_url_static') # Lấy RTSP đã gán
            latest_device_time = event.get('date_time')
            latest_snapshot_url = event.get('attach_snapshot_web_url')

            if event.get('objects'):
                # Tìm biển số đầu tiên trong objects
                for obj in event['objects']:
                    if obj.get('lp_text'):
                        latest_lp_text = obj['lp_text']
                        # Nếu có ảnh riêng của đối tượng, ưu tiên hiển thị
                        if obj.get('object_capture_image_web_url'):
                            latest_snapshot_url = obj['object_capture_image_web_url']
                        break # Chỉ lấy biển số đầu tiên
            break # Đã tìm thấy sự kiện LPR gần nhất, dừng tìm kiếm

    return jsonify({
        "last_lp_text": latest_lp_text,
        "last_snapshot_url": latest_snapshot_url,
        "live_cam_rtsp_url": latest_rtsp_url, # RTSP URL của sự kiện gần nhất
        "last_event_device_time": latest_device_time,
        "channel_name": latest_event.get('ch_name') if latest_event else "N/A" # Tên kênh để hiển thị trên Live Cam
    })

@app.route('/api/errors', methods=['GET'])
def get_errors():
    return jsonify(error_log[-50:][::-1])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)