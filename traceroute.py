import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import subprocess
import json
import requests
import re # For regex to parse traceroute output
import sys # Đã thêm: Cần thiết để kiểm tra hệ điều hành (sys.platform)

# --- Cấu hình ---
# API endpoint cho dịch vụ GeoIP. Chúng ta sẽ sử dụng ip-api.com cho mục đích demo.
# Lưu ý: ip-api.com có giới hạn tốc độ nếu không có khóa API trả phí.
GEOIP_API_URL = "http://ip-api.com/json/"

# --- Hàm hỗ trợ ---

def get_location_from_ip(ip_address):
    """
    Lấy thông tin địa lý (thành phố, quốc gia) từ địa chỉ IP sử dụng một dịch vụ API.
    """
    try:
        response = requests.get(f"{GEOIP_API_URL}{ip_address}?fields=country,city,lat,lon")
        response.raise_for_status() # Gây ra lỗi HTTP cho các mã trạng thái xấu (4xx hoặc 5xx)
        data = response.json()
        if data and data.get("status") == "success":
            country = data.get("country", "Unknown")
            city = data.get("city", "Unknown")
            lat = data.get("lat")
            lon = data.get("lon")
            return f"{city}, {country}" if city != "Unknown" else country, (lat, lon)
        else:
            return "Không xác định", (None, None)
    except requests.exceptions.RequestException as e:
        print(f"Lỗi khi lấy thông tin địa lý cho {ip_address}: {e}")
        return "Lỗi GeoIP", (None, None)
    except json.JSONDecodeError:
        print(f"Lỗi giải mã JSON từ GeoIP API cho {ip_address}")
        return "Lỗi GeoIP", (None, None)

def perform_traceroute(target_host, max_hops=30):
    """
    Thực hiện traceroute đến máy chủ đích và phân tích đầu ra.
    Sử dụng lệnh 'tracert' trên Windows hoặc 'traceroute' trên Unix/Linux/macOS.
    """
    hops_data = []
    platform_cmd = []
    if sys.platform.startswith('win'):
        platform_cmd = ["tracert", "-d", "-h", str(max_hops), target_host] # -d to not resolve hostnames
    else: # Linux, macOS, etc.
        platform_cmd = ["traceroute", "-n", "-m", str(max_hops), target_host] # -n to not resolve hostnames

    try:
        process = subprocess.Popen(platform_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in process.stdout:
            line = line.strip()
            if not line or "Tracing route to" in line or "over a maximum of" in line or "***" in line or "Request timed out." in line:
                continue

            # Phân tích dòng đầu ra của traceroute
            hop_match = None
            if sys.platform.startswith('win'):
                # Ví dụ: 1 <1 ms <1 ms <1 ms 192.168.1.1
                # Ví dụ: 2 10 ms 12 ms 11 ms 192.168.1.1
                # Ví dụ: 10 * * * Request timed out.
                match_pattern = re.compile(r'^\s*(\d+)\s+((?:\*|\d+\s*ms\s*){1,3})\s+([\d.a-zA-Z-]+)')
                hop_match = match_pattern.match(line)
                if hop_match:
                    hop_num = int(hop_match.group(1))
                    rtt_str = hop_match.group(2).strip()
                    ip_or_hostname = hop_match.group(3).strip()

                    # Lấy IP nếu hostname được cung cấp
                    ip_address = ip_or_hostname
                    hostname = ip_or_hostname
                    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                        try:
                            ip_address = socket.gethostbyname(hostname)
                        except socket.gaierror:
                            ip_address = "Không phân giải"

                    # Phân tích RTT: chỉ lấy RTT đầu tiên làm đại diện
                    rtt_values = re.findall(r'(\d+)\s*ms', rtt_str)
                    rtt = f"{rtt_values[0]} ms" if rtt_values else "N/A" # Lấy RTT đầu tiên

                    hops_data.append({
                        "hop": hop_num,
                        "ip": ip_address,
                        "hostname": hostname,
                        "rtt": rtt,
                        "location": "Đang tìm...",
                        "coords": (None, None)
                    })

            else: # Unix/Linux/macOS traceroute output
                # Ví dụ: 1 192.168.1.1 0.772 ms 0.589 ms 0.528 ms
                # Ví dụ: 2 router.example.com (10.0.0.1) 1.234 ms
                # Example with no hostname: 3 172.16.0.1 1.234 ms
                match_pattern = re.compile(r'^\s*(\d+)\s+([\d.]+|[a-zA-Z0-9.-]+\s+\(([\d.]+)\))\s+((?:\d+\.\d+\s*ms\s*)*)')
                hop_match = match_pattern.match(line)

                if hop_match:
                    hop_num = int(hop_match.group(1))
                    first_part = hop_match.group(2) # e.g., "router.example.com (10.0.0.1)" or "192.168.1.1"
                    ip_address = ""
                    hostname = ""

                    # Extract IP and hostname
                    ip_match = re.search(r'\(([\d.]+)\)', first_part)
                    if ip_match:
                        ip_address = ip_match.group(1)
                        hostname = first_part.split('(')[0].strip()
                    else:
                        ip_address = first_part
                        try:
                            hostname = socket.gethostbyaddr(ip_address)[0]
                        except socket.herror:
                            hostname = "Không phân giải"

                    rtt_str = hop_match.group(4).strip()
                    rtt = rtt_str.split(' ')[0] if rtt_str else "N/A" # Lấy RTT đầu tiên

                    if ip_address != "Không phân giải" and ip_address != "*": # Bỏ qua các hop không có IP
                        hops_data.append({
                            "hop": hop_num,
                            "ip": ip_address,
                            "hostname": hostname,
                            "rtt": rtt,
                            "location": "Đang tìm...",
                            "coords": (None, None)
                        })
        process.wait()
    except FileNotFoundError:
        raise RuntimeError(f"Lệnh '{platform_cmd[0]}' không tìm thấy. "
                           f"Đảm bảo 'tracert' (Windows) hoặc 'traceroute' (Linux/macOS) đã được cài đặt và có trong PATH.")
    except Exception as e:
        raise RuntimeError(f"Lỗi khi thực hiện traceroute: {e}")
    return hops_data

# --- Giao diện người dùng Tkinter ---

class TracerouteApp:
    def __init__(self, master):
        self.master = master
        master.title("Traceroute Visualizer")
        master.geometry("800x600")
        master.resizable(True, True)

        self.create_widgets()
        self.master.grid_rowconfigure(2, weight=1)
        self.master.grid_columnconfigure(0, weight=1)

    def create_widgets(self):
        # Khung nhập liệu
        input_frame = ttk.Frame(self.master, padding="10")
        input_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E))

        ttk.Label(input_frame, text="Nhập đích (IP/Hostname):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.target_entry = ttk.Entry(input_frame, width=40)
        self.target_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
        self.target_entry.bind("<Return>", lambda event: self.start_traceroute())
        input_frame.grid_columnconfigure(1, weight=1)

        self.start_button = ttk.Button(input_frame, text="Bắt đầu Traceroute", command=self.start_traceroute)
        self.start_button.grid(row=0, column=2, padx=5, pady=5)

        # Thanh trạng thái
        self.status_label = ttk.Label(self.master, text="Sẵn sàng.", relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Khu vực hiển thị kết quả (Treeview)
        self.results_tree = ttk.Treeview(self.master, columns=("hop", "ip", "hostname", "rtt", "location"), show="headings")
        self.results_tree.heading("hop", text="Hop", anchor=tk.W)
        self.results_tree.heading("ip", text="IP", anchor=tk.W)
        self.results_tree.heading("hostname", text="Hostname", anchor=tk.W)
        self.results_tree.heading("rtt", text="RTT", anchor=tk.W)
        self.results_tree.heading("location", text="Vị trí", anchor=tk.W)

        self.results_tree.column("hop", width=50, stretch=tk.NO)
        self.results_tree.column("ip", width=120, stretch=tk.NO)
        self.results_tree.column("hostname", width=180, stretch=tk.YES)
        self.results_tree.column("rtt", width=80, stretch=tk.NO)
        self.results_tree.column("location", width=150, stretch=tk.YES)

        self.results_tree.grid(row=2, column=0, columnspan=2, sticky=(tk.N, tk.S, tk.W, tk.E), padx=10, pady=10)

        # Thanh cuộn cho Treeview
        scrollbar = ttk.Scrollbar(self.master, orient=tk.VERTICAL, command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=2, sticky=(tk.N, tk.S), padx=(0,10), pady=10)


    def update_status(self, message, is_error=False):
        """Cập nhật thanh trạng thái của GUI."""
        self.status_label.config(text=message)
        if is_error:
            self.status_label.config(foreground="red")
        else:
            self.status_label.config(foreground="black")

    def start_traceroute(self):
        target_host = self.target_entry.get().strip()
        if not target_host:
            self.update_status("Vui lòng nhập IP hoặc Hostname đích.", is_error=True)
            return

        self.clear_results()
        self.update_status("Đang thực hiện traceroute... Vui lòng chờ.")
        self.start_button.config(state=tk.DISABLED) # Vô hiệu hóa nút

        # Chạy traceroute trong một luồng riêng biệt để không chặn GUI
        threading.Thread(target=self._run_traceroute_thread, args=(target_host,)).start()

    def _run_traceroute_thread(self, target_host):
        try:
            hops = perform_traceroute(target_host)
            self.master.after(0, self._update_results_initial, hops) # Cập nhật kết quả ban đầu trên GUI

            # Sau đó, tìm kiếm GeoIP cho từng hop trong một luồng riêng biệt hoặc tuần tự
            # để tránh bị rate-limit nếu dùng API miễn phí.
            for i, hop in enumerate(hops):
                if hop["ip"] not in ["*", "Không phân giải", "Lỗi GeoIP"]: # Bỏ qua các hop không có IP hợp lệ
                    location, coords = get_location_from_ip(hop["ip"])
                    hop["location"] = location
                    hop["coords"] = coords
                    self.master.after(0, self._update_single_hop_result, i, hop) # Cập nhật từng hop

            self.master.after(0, self.update_status, f"Traceroute hoàn tất đến {target_host}!")
        except RuntimeError as e:
            self.master.after(0, self.update_status, f"Lỗi: {e}", is_error=True)
        except Exception as e:
            self.master.after(0, self.update_status, f"Đã xảy ra lỗi không mong muốn: {e}", is_error=True)
        finally:
            # Sửa lỗi: Gói config vào lambda để truyền đúng đối số
            self.master.after(0, lambda: self.start_button.config(state=tk.NORMAL)) # Kích hoạt lại nút

    def clear_results(self):
        """Xóa tất cả các hàng trong Treeview."""
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)

    def _update_results_initial(self, hops):
        """Cập nhật các hop ban đầu vào Treeview."""
        self.clear_results()
        for hop in hops:
            self.results_tree.insert("", tk.END, values=(hop["hop"], hop["ip"], hop["hostname"], hop["rtt"], hop["location"]))

    def _update_single_hop_result(self, index, updated_hop):
        """Cập nhật một hàng cụ thể trong Treeview với thông tin vị trí."""
        # Cách đơn giản: Xóa và chèn lại, hoặc tìm item ID và cập nhật
        # Tìm item ID dựa trên giá trị hop number. Cần một cách đáng tin cậy hơn nếu hop number không duy nhất.
        # Với traceroute, hop number là duy nhất và tăng dần.
        for item_id in self.results_tree.get_children():
            values = self.results_tree.item(item_id, 'values')
            if int(values[0]) == updated_hop["hop"]:
                self.results_tree.item(item_id, values=(
                    updated_hop["hop"],
                    updated_hop["ip"],
                    updated_hop["hostname"],
                    updated_hop["rtt"],
                    updated_hop["location"]
                ))
                break

# --- Hàm chính để chạy ứng dụng ---
if __name__ == "__main__":
    # Yêu cầu cài đặt các thư viện cần thiết
    # messagebox.showinfo("Yêu cầu", "Để ứng dụng hoạt động, bạn cần cài đặt Scapy và requests:\npip install scapy requests")
    
    # Kiểm tra sự tồn tại của lệnh traceroute/tracert
    try:
        if sys.platform.startswith('win'):
            subprocess.check_call(["where", "tracert"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            subprocess.check_call(["which", "traceroute"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        messagebox.showerror("Lỗi Cài đặt", "Lệnh 'tracert' (Windows) hoặc 'traceroute' (Linux/macOS) không tìm thấy. Vui lòng cài đặt nó trên hệ thống của bạn và đảm bảo nó có trong PATH.")
        sys.exit(1)
    except FileNotFoundError:
         messagebox.showerror("Lỗi Cài đặt", "Lệnh 'tracert' (Windows) hoặc 'traceroute' (Linux/macOS) không tìm thấy. Vui lòng cài đặt nó trên hệ thống của bạn và đảm bảo nó có trong PATH.")
         sys.exit(1)

    root = tk.Tk()
    app = TracerouteApp(root)
    root.mainloop()
