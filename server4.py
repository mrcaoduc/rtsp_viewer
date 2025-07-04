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

# --- Cấu hình thư mục tải lên ---
UPLOAD_FOLDER = 'static/uploads' # Đổi thư mục chung để chứa cả ảnh và video
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Đảm bảo thư mục 'static/images' tồn tại cho các hình ảnh mặc định/placeholder ---
# Đây là nơi bạn sẽ đặt 'black_camera.gif'
STATIC_IMAGES_FOLDER = 'static/images'
if not os.path.exists(STATIC_IMAGES_FOLDER):
    os.makedirs(STATIC_IMAGES_FOLDER)
    # Tùy chọn: tạo một tệp black_camera.gif rỗng nếu nó chưa có
    # Hoặc đảm bảo bạn đặt tệp của mình vào đây thủ công
    # Ví dụ đơn giản để tạo một tệp placeholder nếu không có
    try:
        if not os.path.exists(os.path.join(STATIC_IMAGES_FOLDER, 'black_camera.gif')):
            # Tạo một hình ảnh GIF 1x1 pixel đen làm placeholder
            # Đây chỉ là ví dụ. Bạn nên đặt tệp .gif thật vào đây.
            # Base64 của GIF 1x1 đen
            gif_1x1_black_b64 = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
            with open(os.path.join(STATIC_IMAGES_FOLDER, 'black_camera.gif'), 'wb') as f:
                f.write(base64.b64decode(gif_1x1_black_b64))
            print(f"Created a placeholder black_camera.gif in {STATIC_IMAGES_FOLDER}")
    except Exception as e:
        print(f"Could not create placeholder black_camera.gif: {e}")


event_log = []
error_log = []

# --- CẤU HÌNH CAMERA ---
CAMERA_CONFIGS = {
    "Entrance": {
        "rtsp_url": "rtsp://admin:cdi12345@192.168.11.49:5554/live/ch1",
        "webrtc_url": "ws://192.168.11.221:8889/cam5",
        "snapshot_url": "http://admin:cdi12345@192.168.11.49/cgi-bin/snapshot.cgi"
    },
    "ExitGate": {
        "rtsp_url": "rtsp://admin:cdi12345@192.168.11.49:5554/live/ch2",
        "webrtc_url": "ws://192.168.11.221:8889/cam6",
        "snapshot_url": "http://admin:cdi12345@192.168.11.49/cgi-bin/snapshot.cgi?channel=2"
    },
}

DEFAULT_LIVE_CAM_KEY = "Entrance"

# --- Định tuyến cho các tệp tĩnh (static files) ---
# Flask mặc định phục vụ các tệp từ thư mục 'static'
# Vì vậy, nếu bạn đặt 'black_camera.gif' vào 'static/images/',
# nó sẽ tự động được phục vụ tại '/static/images/black_camera.gif'.
# Trong mã HTML frontend, bạn phải điều chỉnh đường dẫn thành '/static/images/black_camera.gif'
# hoặc tạo một route alias như sau để tương thích với '/images/...'

@app.route('/images/<path:filename>')
def serve_images(filename):
    """Phục vụ các tệp từ thư mục static/images dưới đường dẫn /images/."""
    # os.path.abspath(app.root_path) trả về đường dẫn thư mục gốc của ứng dụng Flask
    # Trong trường hợp này, nó sẽ là F:\APIWeb\
    # Sau đó nối thêm 'static/images' để có đường dẫn tuyệt đối đến thư mục chứa ảnh
    full_path_to_images = os.path.join(app.root_path, 'static', 'images')
    return send_from_directory(full_path_to_images, filename)

@app.route('/')
def serve_index():
    return render_template('index4.html')

@app.route('/Apis/AIBirdge/Event/lpr_kr/default.aspx', methods=['POST'])
def handle_event():
    global event_log
    global error_log
    
    if request.mimetype == 'multipart/form-data':
        try:
            event_json_str = request.form.get('event_json')
            event_data = {} # Khởi tạo event_data mặc định

            if event_json_str:
                event_data = json.loads(event_json_str)
            else:
                # Nếu không có event_json, vẫn tạo một dict cơ bản
                event_data['event_name'] = 'Unknown Event'
                event_data['device_name'] = 'Unknown Device'
                event_data['ch_name'] = 'N/A'

            event_data['received_at'] = datetime.datetime.now().isoformat()

            device_name = event_data.get('device_name')
            ch_name = event_data.get('ch_name')
            
            event_data['rtsp_url_static'] = None
            event_data['webrtc_url_static'] = None
            event_data['snapshot_live_url_static'] = None
            event_data['attached_video_web_url'] = None # Thêm trường cho video
            event_data['attached_file_snapshot_web_url'] = None # Thêm trường cho snapshot dạng file

            config_key = None
            if ch_name and ch_name in CAMERA_CONFIGS:
                config_key = ch_name
            elif device_name and device_name in CAMERA_CONFIGS:
                config_key = device_name
            
            if config_key:
                event_data['rtsp_url_static'] = CAMERA_CONFIGS[config_key].get('rtsp_url')
                event_data['webrtc_url_static'] = CAMERA_CONFIGS[config_key].get('webrtc_url')
                if CAMERA_CONFIGS[config_key].get('snapshot_url'):
                    # Sử dụng proxy để lấy snapshot từ camera
                    event_data['snapshot_live_url_static'] = f'/api/camera_snapshot_proxy/{config_key}'
            else:
                print(f"  Warning: No camera configuration found for device '{device_name}' or channel '{ch_name}'")

            # --- Xử lý Attach Snapshot (Base64 trong JSON) - Ưu tiên cái này nếu có ---
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
                    event_data['attach_snapshot_web_url'] = f'/static/uploads/{filename}' # Cập nhật đường dẫn
                    print(f"  Attach Snapshot (Base64) Saved: {event_data['attach_snapshot_web_url']}")
                except Exception as e:
                    print(f"  !!! Error saving Attach Snapshot (Base64): {e}")
                    event_data['attach_snapshot_web_url'] = None

            # --- Xử lý Attach Snapshot (File trực tiếp) ---
            attach_file_snapshot = request.files.get('attach_snapshot') # Giả sử tên trường là 'attach_snapshot'
            if attach_file_snapshot and attach_file_snapshot.filename != '':
                try:
                    filename = f"file_snapshot_{uuid.uuid4()}{os.path.splitext(attach_file_snapshot.filename)[1]}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    attach_file_snapshot.save(filepath)
                    event_data['attached_file_snapshot_web_url'] = f'/static/uploads/{filename}'
                    print(f"  Attach Snapshot (File) Saved: {event_data['attached_file_snapshot_web_url']}")
                except Exception as e:
                    print(f"  !!! Error saving Attach Snapshot (File): {e}")
                    event_data['attached_file_snapshot_web_url'] = None

            # --- Xử lý Attach Video Clip (File trực tiếp) ---
            attach_video_clip = request.files.get('attach_video_clip') # Giả sử tên trường là 'attach_video_clip'
            if attach_video_clip and attach_video_clip.filename != '':
                try:
                    filename = f"video_clip_{uuid.uuid4()}{os.path.splitext(attach_video_clip.filename)[1]}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    attach_video_clip.save(filepath)
                    event_data['attached_video_web_url'] = f'/static/uploads/{filename}'
                    print(f"  Attach Video Clip Saved: {event_data['attached_video_web_url']}")
                except Exception as e:
                    print(f"  !!! Error saving Attach Video Clip: {e}")
                    event_data['attached_video_web_url'] = None

            # --- Xử lý ảnh chụp từng đối tượng (Base64) ---
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
                        obj['object_capture_image_web_url'] = f'/static/uploads/{obj_filename}' # Cập nhật đường dẫn
                        print(f"  Object Capture Image Saved: {obj['object_capture_image_web_url']}")
                    except Exception as e:
                        print(f"  !!! Error saving object capture image: {e}")
                        obj['object_capture_image_web_url'] = None

            event_log.append(event_data)

            if len(event_log) > 500:
                event_log = event_log[-500:]

            print(f"--- New Event Received at: {event_data['received_at']} ---")
            print(f"Device: {event_data.get('device_name')}, Channel: {ch_name}, Event: {event_data.get('event_name')}")
            if event_data.get('rtsp_url_static'):
                print(f"  Static RTSP URL: {event_data['rtsp_url_static']}")
            if event_data.get('webrtc_url_static'):
                print(f"  WebRTC URL: {event_data['webrtc_url_static']}")
            if event_data.get('attach_snapshot_web_url'):
                print(f"  Attach Snapshot (Base64) URL: {event_data['attach_snapshot_web_url']}")
            if event_data.get('attached_file_snapshot_web_url'):
                print(f"  Attach Snapshot (File) URL: {event_data['attached_file_snapshot_web_url']}")
            if event_data.get('attached_video_web_url'):
                print(f"  Attach Video Clip URL: {event_data['attached_video_web_url']}")
            if event_data.get('objects'):
                for obj in event_data['objects']:
                    print(f"  LP Text: {obj.get('lp_text')}, Group: {obj.get('group')}")
                    if obj.get('object_capture_image_web_url'):
                        print(f"    Object Snapshot URL: {obj['object_capture_image_web_url']}")
            print("---------------------------------------")

            return jsonify({"status": "success", "message": "Event received and processed"}), 200
        except json.JSONDecodeError:
            return jsonify({"status": "error", "message": "Invalid JSON format in 'event_json'"}), 400
        except Exception as e:
            error_info = {
                "error_type": str(type(e)),
                "message": str(e),
                "received_at": datetime.datetime.now().isoformat(),
                "request_data": request.form.to_dict() # Ghi lại dữ liệu form để gỡ lỗi
            }
            error_log.append(error_info)
            print(f"!!! Error processing event: {str(e)} !!!")
            return jsonify({"status": "error", "message": f"An internal error occurred: {str(e)}"}), 500
    else:
        return jsonify({"status": "error", "message": "Content-Type must be multipart/form-data"}), 415

@app.route('/Apis/AIBirdge/Error/default.aspx', methods=['POST'])
def handle_error():
    global error_log
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
    return jsonify(event_log[-50:][::-1])

@app.route('/api/latest_lpr_info', methods=['GET'])
def get_latest_lpr_info():
    latest_event = None
    latest_lp_text = "N/A"
    latest_snapshot_url = None
    latest_video_url = None # Thêm trường cho video
    latest_rtsp_url = None
    latest_webrtc_url = None # Sẽ được trả về nhưng không dùng cho MJPEG
    latest_device_time = "N/A"
    channel_name_for_live_cam = "N/A"

    # Thông tin cần thiết cho MJPEG live stream:
    # device_type (ví dụ: 'ai-bridge'), device_link_url (IP camera), device_credentials (Base64 encoded)
    mjpeg_live_cam_info = {
        "device_type": None,
        "device_link_url": None,
        "device_credentials": None,
        "camera_no": None,
        "device_https": "http" # Giả định HTTP, bạn có thể thay đổi nếu camera dùng HTTPS
    }

    # Cố gắng lấy thông tin cấu hình từ DEFAULT_LIVE_CAM_KEY
    if DEFAULT_LIVE_CAM_KEY in CAMERA_CONFIGS:
        default_config = CAMERA_CONFIGS[DEFAULT_LIVE_CAM_KEY]
        # Lấy IP/hostname từ snapshot_url nếu có
        if default_config.get('snapshot_url'):
            try:
                # Phân tích URL để lấy host (IP hoặc hostname) và thông tin xác thực
                # Lưu ý: requests.utils.urlparse không phân tích được user:pass trong HTTP/HTTPS URL
                # nên ta phải xử lý thủ công hoặc lấy từ nguồn khác
                parsed_url = requests.utils.urlparse(default_config['snapshot_url'])
                
                # Tách username:password khỏi netloc nếu có
                netloc_parts = parsed_url.netloc.split('@')
                auth_str = None
                host_port = netloc_parts[-1]

                if len(netloc_parts) > 1:
                    auth_str = netloc_parts[0] # admin:cdi12345

                mjpeg_live_cam_info["device_link_url"] = host_port.split(':')[0] # Chỉ lấy host/IP
                if ':' in host_port: # Có cổng
                    mjpeg_live_cam_info["device_https"] = "https" if parsed_url.scheme == "https" else "http"
                else: # Không có cổng, giả định http
                    mjpeg_live_cam_info["device_https"] = "https" if parsed_url.scheme == "https" else "http"

                if auth_str:
                    mjpeg_live_cam_info["device_credentials"] = base64.b64encode(auth_str.encode()).decode()
                
                # Cố gắng suy luận device_type và camera_no từ snapshot_url
                if "/api/snapshot/jpeg/" in default_config['snapshot_url']:
                    mjpeg_live_cam_info["device_type"] = "ai-bridge"
                    # Tìm ch= parameter
                    if 'ch=' in default_config['snapshot_url']:
                        mjpeg_live_cam_info["camera_no"] = default_config['snapshot_url'].split('ch=')[-1].split('&')[0]
                elif "/cgi-bin/snapshot.cgi" in default_config['snapshot_url']:
                    mjpeg_live_cam_info["device_type"] = "pro-e"
                    # Tìm channel= parameter
                    if 'channel=' in default_config['snapshot_url']:
                        mjpeg_live_cam_info["camera_no"] = default_config['snapshot_url'].split('channel=')[-1].split('&')[0]
                    else: # Nếu không có channel, giả định ch1
                        mjpeg_live_cam_info["camera_no"] = "1"

            except Exception as e:
                print(f"Error parsing snapshot_url for MJPEG live cam info: {e}")
                # Đặt lại về None nếu có lỗi phân tích
                mjpeg_live_cam_info["device_link_url"] = None
                mjpeg_live_cam_info["device_credentials"] = None
                mjpeg_live_cam_info["device_type"] = None
                mjpeg_live_cam_info["camera_no"] = None

        latest_webrtc_url = default_config.get('webrtc_url') # Giữ nguyên webrtc_url cho mục đích API
        channel_name_for_live_cam = DEFAULT_LIVE_CAM_KEY


    for event in reversed(event_log):
        if event.get('event_type') in ['LPR-JP', 'License Plate Detected', 'LPR', 'Vehicle Detected', 'Motion Detected']: # Thêm các loại sự kiện khác nếu cần
            latest_event = event
            latest_rtsp_url = event.get('rtsp_url_static')
            
            # Ở đây không cần cập nhật webrtc_url từ event, vì frontend sẽ lấy từ default config
            # (hoặc bạn có thể thêm logic phức tạp hơn nếu muốn live cam thay đổi theo event)

            latest_device_time = event.get('date_time')
            
            # Ưu tiên snapshot từ Base64, sau đó là từ file trực tiếp
            latest_snapshot_url = event.get('attach_snapshot_web_url') or event.get('attached_file_snapshot_web_url')
            latest_video_url = event.get('attached_video_web_url') # Lấy URL video
            
            # Nếu có sự kiện LPR, cập nhật tên kênh cho live cam dựa trên sự kiện đó
            event_camera_key = event.get('ch_name') or event.get('device_name')
            if event_camera_key:
                channel_name_for_live_cam = event_camera_key
                # Tùy chọn: Nếu bạn muốn live cam chuyển sang kênh của sự kiện mới nhất
                # khi có sự kiện, bạn sẽ cập nhật mjpeg_live_cam_info ở đây.
                # Tuy nhiên, yêu cầu ban đầu là giữ nguyên khung web và chỉ xử lý luồng hiển thị video,
                # nên live cam sẽ mặc định theo DEFAULT_LIVE_CAM_KEY.

            if event.get('objects'):
                for obj in event['objects']:
                    if obj.get('lp_text'):
                        latest_lp_text = obj['lp_text']
                        if obj.get('object_capture_image_web_url'):
                            latest_snapshot_url = obj['object_capture_image_web_url'] # Snapshot của đối tượng có thể ghi đè
                        break # Chỉ lấy biển số xe đầu tiên
            break # Lấy sự kiện LPR mới nhất và thoát vòng lặp
    
    return jsonify({
        "last_lp_text": latest_lp_text,
        "last_snapshot_url": latest_snapshot_url,
        "last_video_url": latest_video_url, # Trả về URL video
        "live_cam_rtsp_url": latest_rtsp_url, # Vẫn trả về nhưng frontend sẽ không dùng cho MJPEG
        "live_cam_webrtc_url": latest_webrtc_url, # Vẫn trả về nhưng frontend sẽ không dùng cho MJPEG
        "last_event_device_time": latest_device_time,
        "channel_name": channel_name_for_live_cam,
        # Thêm thông tin MJPEG cho frontend
        "live_cam_mjpeg_config": mjpeg_live_cam_info if mjpeg_live_cam_info["device_link_url"] else None
    })

@app.route('/api/camera_snapshot_proxy/<camera_key>', methods=['GET'])
def get_camera_snapshot_proxy(camera_key):
    config = CAMERA_CONFIGS.get(camera_key)
    if not config or not config.get('snapshot_url'):
        # Nếu không có cấu hình hoặc URL snapshot, trả về placeholder từ static/images
        return send_from_directory('static/images', 'no_signal.jpg', mimetype='image/jpeg'), 404
    
    snapshot_url = config['snapshot_url']
    try:
        # Tách user:pass khỏi URL nếu có để thêm vào headers Auth
        parsed_url = requests.utils.urlparse(snapshot_url)
        auth = None
        clean_url = snapshot_url

        if '@' in parsed_url.netloc:
            auth_str, host_port = parsed_url.netloc.split('@', 1)
            username, password = auth_str.split(':', 1)
            auth = (username, password)
            clean_url = f"{parsed_url.scheme}://{host_port}{parsed_url.path}{'?' + parsed_url.query if parsed_url.query else ''}"
        
        response = requests.get(clean_url, auth=auth, stream=True, timeout=3)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # Trả về nội dung ảnh và loại MIME
        content_type = response.headers.get('Content-Type', 'image/jpeg')
        return response.content, response.status_code, {'Content-Type': content_type}
    except requests.exceptions.Timeout:
        print(f"Error fetching snapshot from {camera_key} ({snapshot_url}): Request timed out.")
        # Trả về ảnh "no_signal.jpg" hoặc ảnh báo lỗi khác nếu timeout
        return send_from_directory('static/images', 'no_signal.jpg', mimetype='image/jpeg'), 504 # Gateway Timeout
    except requests.exceptions.RequestException as e:
        print(f"Error fetching snapshot from {camera_key} ({snapshot_url}): {e}")
        # Trả về ảnh "no_signal.jpg" hoặc ảnh báo lỗi khác khi có lỗi request
        return send_from_directory('static/images', 'no_signal.jpg', mimetype='image/jpeg'), 500

@app.route('/api/errors', methods=['GET'])
def get_errors():
    return jsonify(error_log[-50:][::-1])

if __name__ == '__main__':
    # Đặt `static_folder` để Flask biết thư mục chứa tệp tĩnh
    # Mặc định là 'static', nên không cần thay đổi nếu cấu trúc của bạn là F:\APIWeb\static\...
    # Nhưng nếu bạn muốn phục vụ từ F:\APIWeb\image\ trực tiếp dưới '/images/', bạn cần setup như sau:
    # app = Flask(__name__, static_folder='static') # Đây là mặc định
    # Nếu muốn thêm thư mục image phục vụ dưới /images/
    # Thì route serve_images phía trên đã xử lý rồi.
    
    app.run(host='0.0.0.0', port=5000, debug=True)