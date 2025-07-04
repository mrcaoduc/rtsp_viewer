#server.py
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS # Dùng để cho phép frontend truy cập
import json
import datetime

app = Flask(__name__)
CORS(app) # Kích hoạt CORS cho phép frontend (thường chạy trên cổng khác) truy cập

# Danh sách để lưu trữ các sự kiện nhận được (trong bộ nhớ)
# Trong môi trường thực tế, bạn sẽ dùng cơ sở dữ liệu
event_log = []
error_log = []

# Thêm endpoint để phục vụ file index.html
@app.route('/')
def serve_index():
    return render_template('index.html')

# Endpoint chính để nhận dữ liệu sự kiện
@app.route('/Apis/AIBirdge/Event/lpr_kr/default.aspx', methods=['POST'])
def handle_event():
    if request.mimetype == 'multipart/form-data':
        try:
            event_json_str = request.form.get('event_json')

            if event_json_str:
                event_data = json.loads(event_json_str)
                event_data['received_at'] = datetime.datetime.now().isoformat() # Thêm thời gian nhận
                event_log.append(event_data) # Lưu vào log

                print(f"--- Sự kiện mới nhận lúc: {event_data['received_at']} ---")
                print(f"Device: {event_data.get('device_name')}, Event: {event_data.get('event_name')}")
                if event_data.get('objects'):
                    for obj in event_data['objects']:
                        print(f"  LP Text: {obj.get('lp_text')}, Group: {obj.get('group')}")
                print("---------------------------------------")

                return jsonify({"status": "success", "message": "Event received and processed"}), 200
            else:
                return jsonify({"status": "error", "message": "Missing 'event_json' field"}), 400
        except json.JSONDecodeError:
            return jsonify({"status": "error", "message": "Invalid JSON format in 'event_json'"}), 400
        except Exception as e:
            # Ghi lại lỗi nếu có vấn đề trong quá trình xử lý
            error_info = {
                "error_type": str(type(e)),
                "message": str(e),
                "received_at": datetime.datetime.now().isoformat(),
                "request_data": request.form.to_dict() # Lưu lại dữ liệu yêu cầu để debug
            }
            error_log.append(error_info)
            print(f"!!! Lỗi xử lý sự kiện: {str(e)} !!!")
            return jsonify({"status": "error", "message": f"An internal error occurred: {str(e)}"}), 500
    else:
        return jsonify({"status": "error", "message": "Content-Type must be multipart/form-data"}), 415

# Endpoint cho lỗi từ AI Box
@app.route('/Apis/AIBirdge/Error/default.aspx', methods=['POST'])
def handle_error():
    error_data_raw = request.get_data(as_text=True) # Lấy dữ liệu thô
    error_info = {
        "raw_error_data": error_data_raw,
        "received_at": datetime.datetime.now().isoformat()
    }
    error_log.append(error_info) # Lưu vào log lỗi

    print(f"--- Dữ liệu Lỗi Nhận được lúc: {error_info['received_at']} ---")
    print(error_data_raw)
    print("------------------------------------")
    return jsonify({"status": "success", "message": "Error data received"}), 200

# API để lấy danh sách sự kiện cho frontend
@app.route('/api/events', methods=['GET'])
def get_events():
    # Trả về các sự kiện mới nhất, ví dụ 50 sự kiện gần nhất
    return jsonify(event_log[-50:][::-1]) # Trả về đảo ngược để hiển thị mới nhất trước

# API để lấy danh sách lỗi cho frontend
@app.route('/api/errors', methods=['GET'])
def get_errors():
    # Trả về các lỗi mới nhất
    return jsonify(error_log[-50:][::-1])

if __name__ == '__main__':
    # Chạy server Flask
    app.run(host='0.0.0.0', port=5000, debug=True) # debug=True để tự động tải lại khi thay đổi code