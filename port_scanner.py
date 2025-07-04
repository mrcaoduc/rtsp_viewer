import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import asyncio
import socket
import ipaddress
from collections import deque # For managing concurrent tasks
import time

# Scapy for advanced scanning (SYN, UDP)
# NOTE: Scapy requires Administrator/Root privileges for raw socket operations.
try:
    from scapy.all import *
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False
    print("Cảnh báo: Thư viện Scapy không tìm thấy. Quét SYN và UDP sẽ không khả dụng.")
    print("Vui lòng cài đặt: pip install scapy")
except Exception as e:
    SCAPY_AVAILABLE = False
    print(f"Cảnh báo: Lỗi khi tải Scapy: {e}. Quét SYN và UDP sẽ không khả dụng.")


# --- Cấu hình ---
DEFAULT_IP_START = "127.0.0.1"
DEFAULT_IP_END = "127.0.0.1"
DEFAULT_PORT_START = 1
DEFAULT_PORT_END = 1024
DEFAULT_TIMEOUT = 1.0 # seconds

# --- Hàng đợi cho các tác vụ asyncio để tránh lỗi khi đóng ứng dụng ---
# Dùng để giữ các tác vụ đang chạy khi tắt ứng dụng
active_tasks = deque()

# --- Các hàm quét lõi ---

async def tcp_connect_scan(ip, port, timeout):
    """
    Thực hiện quét TCP Connect. Mở một kết nối TCP đầy đủ.
    Trả về: (ip, port, status, banner, rtt)
    """
    status = "Lọc/Timeout"
    banner = ""
    rtt = "N/A"
    try:
        start_time = time.time()
        # Tạo kết nối TCP
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        end_time = time.time()
        rtt = f"{int((end_time - start_time) * 1000)} ms"

        # Cố gắng lấy banner
        try:
            writer.write(b"GET / HTTP/1.0\r\n\r\n") # Thử probe HTTP
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=1) # Đọc tối đa 1KB banner
            banner = data.decode(errors='ignore').strip().split('\n')[0] # Lấy dòng đầu tiên
        except asyncio.TimeoutError:
            banner = "Không phản hồi banner"
        except Exception:
            banner = "Không lấy được banner" # Không phải HTTP hoặc lỗi khác

        status = "Mở"
        writer.close()
        await writer.wait_closed()
    except asyncio.TimeoutError:
        status = "Lọc/Timeout"
    except ConnectionRefusedError:
        status = "Đóng"
    except Exception as e:
        status = f"Lỗi: {e}"
    return ip, port, status, banner, rtt # Đã sửa: Trả về ip và port

async def tcp_syn_scan(ip, port, timeout):
    """
    Thực hiện quét TCP SYN (stealth scan) bằng Scapy.
    Yêu cầu quyền quản trị/root.
    Trả về: (ip, port, status, banner, rtt)
    """
    if not SCAPY_AVAILABLE:
        return ip, port, "N/A (Scapy không có)", "", "N/A" # Đã sửa: Trả về ip và port

    status = "Lọc/Timeout"
    banner = ""
    rtt = "N/A"
    try:
        # Tạo gói SYN
        ip_layer = IP(dst=ip)
        tcp_layer = TCP(dport=port, flags="S") # SYN flag
        packet = ip_layer / tcp_layer

        start_time = time.time()
        # Gửi gói SYN và đợi phản hồi
        # sr1: gửi 1 gói, nhận 1 phản hồi
        # timeout: thời gian chờ phản hồi
        # verbose=0: không in đầu ra của Scapy ra console
        ans, unans = sr(packet, timeout=timeout, verbose=0, retry=0)
        end_time = time.time()
        rtt = f"{int((end_time - start_time) * 1000)} ms" if ans else "N/A"

        if ans:
            # ans là một danh sách các cặp (gói đã gửi, gói đã nhận)
            received_packet = ans[0][1] # Lấy gói đã nhận

            if received_packet.haslayer(TCP) and received_packet.getlayer(TCP).flags == 0x12: # SYN-ACK
                status = "Mở"
                # Cố gắng banner grabbing bằng connect scan tạm thời (nếu port mở)
                # Đây là một bước phụ để có thể lấy banner sau khi xác định port mở bằng SYN
                # Có thể cần một kết nối đầy đủ để lấy banner.
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(ip, port), timeout=timeout / 2
                    )
                    writer.write(b"GET / HTTP/1.0\r\n\r\n")
                    await writer.drain()
                    data = await asyncio.wait_for(reader.read(1024), timeout=1)
                    banner = data.decode(errors='ignore').strip().split('\n')[0]
                    writer.close()
                    await writer.wait_closed()
                except (asyncio.TimeoutError, ConnectionRefusedError, Exception):
                    banner = "Không lấy được banner (SYN thành công)"
            elif received_packet.haslayer(TCP) and received_packet.getlayer(TCP).flags == 0x14: # RST-ACK (RST)
                status = "Đóng"
        else: # Không có phản hồi
            status = "Lọc/Timeout"
    except Exception as e:
        status = f"Lỗi (Scapy): {e}"
        if "Operation not permitted" in str(e):
            status += " (Thiếu quyền Admin/Root?)"
    return ip, port, status, banner, rtt # Đã sửa: Trả về ip và port

async def udp_scan(ip, port, timeout):
    """
    Thực hiện quét UDP bằng Scapy.
    Yêu cầu quyền quản trị/root.
    Trả về: (ip, port, status, banner, rtt)
    """
    if not SCAPY_AVAILABLE:
        return ip, port, "N/A (Scapy không có)", "", "N/A" # Đã sửa: Trả về ip và port

    status = "Mở/Lọc" # UDP không phản hồi mặc định nếu mở, nên khó phân biệt
    banner = ""
    rtt = "N/A"
    try:
        # Gửi một gói UDP rỗng hoặc gói không hợp lệ để kích hoạt phản hồi ICMP nếu port đóng
        # Hoặc một gói DNS/NTP/SNMP probe để lấy banner nếu port mở
        # Ở đây, gửi một gói rỗng đơn giản
        udp_packet = IP(dst=ip)/UDP(dport=port)/Raw(load="X") # Gửi 1 byte dữ liệu

        start_time = time.time()
        ans, unans = sr(udp_packet, timeout=timeout, verbose=0, retry=0)
        end_time = time.time()
        rtt = f"{int((end_time - start_time) * 1000)} ms" if ans else "N/A"

        if ans:
            received_packet = ans[0][1]
            # Kiểm tra ICMP Port Unreachable
            if received_packet.haslayer(ICMP) and received_packet.getlayer(ICMP).type == 3 and received_packet.getlayer(ICMP).code == 3:
                status = "Đóng"
            else:
                # Có phản hồi nhưng không phải ICMP Port Unreachable.
                # Có thể là phản hồi của dịch vụ, hoặc loại ICMP khác.
                status = "Mở" # Giả định là mở nếu có phản hồi
                # Có thể thử banner grabbing cụ thể hơn ở đây nếu biết dịch vụ
                banner = received_packet.summary() # Tóm tắt gói tin
        else:
            # Không có phản hồi: Có thể port mở (không có dịch vụ phản hồi) hoặc bị lọc
            status = "Mở/Lọc"
    except Exception as e:
        status = f"Lỗi (Scapy): {e}"
        if "Operation not permitted" in str(e):
            status += " (Thiếu quyền Admin/Root?)"
    return ip, port, status, banner, rtt # Đã sửa: Trả về ip và port


# --- Giao diện người dùng Tkinter ---

class PortScannerApp:
    def __init__(self, master):
        self.master = master
        master.title("Port Scanner Nâng cao")
        master.geometry("900x700")
        master.resizable(True, True)

        self.scanning_thread = None
        self.stop_scan_event = threading.Event()
        self.async_loop = None # Để giữ tham chiếu đến asyncio loop

        self.create_widgets()
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing) # Xử lý đóng cửa sổ

    def create_widgets(self):
        # Cấu hình grid cho cửa sổ chính
        self.master.grid_rowconfigure(3, weight=1) # Dòng cho Treeview sẽ mở rộng
        self.master.grid_columnconfigure(0, weight=1)

        # --- Khung nhập liệu và tùy chọn ---
        input_frame = ttk.LabelFrame(self.master, text="Cấu hình quét", padding="10")
        input_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=10, pady=5)
        input_frame.grid_columnconfigure(1, weight=1) # Cột nhập liệu mở rộng

        # Dải IP
        ttk.Label(input_frame, text="Dải IP (Bắt đầu):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.ip_start_entry = ttk.Entry(input_frame, width=20)
        self.ip_start_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.ip_start_entry.insert(0, DEFAULT_IP_START)

        ttk.Label(input_frame, text="Dải IP (Kết thúc):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.ip_end_entry = ttk.Entry(input_frame, width=20)
        self.ip_end_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.ip_end_entry.insert(0, DEFAULT_IP_END)

        # Dải Cổng
        ttk.Label(input_frame, text="Dải Cổng (Bắt đầu):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.port_start_entry = ttk.Entry(input_frame, width=20)
        self.port_start_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.port_start_entry.insert(0, str(DEFAULT_PORT_START))

        ttk.Label(input_frame, text="Dải Cổng (Kết thúc):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.port_end_entry = ttk.Entry(input_frame, width=20)
        self.port_end_entry.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.port_end_entry.insert(0, str(DEFAULT_PORT_END))

        # Timeout
        ttk.Label(input_frame, text="Timeout (giây):").grid(row=4, column=0, sticky=tk.W, padx=5, pady=2)
        self.timeout_entry = ttk.Entry(input_frame, width=10)
        self.timeout_entry.grid(row=4, column=1, sticky=(tk.W), padx=5, pady=2)
        self.timeout_entry.insert(0, str(DEFAULT_TIMEOUT))

        # Loại quét
        scan_type_frame = ttk.LabelFrame(input_frame, text="Loại quét", padding="5")
        scan_type_frame.grid(row=0, column=2, rowspan=5, sticky=(tk.N, tk.S, tk.W, tk.E), padx=10, pady=5)
        scan_type_frame.grid_columnconfigure(0, weight=1)

        self.scan_type_var = tk.StringVar(value="TCP_CONNECT") # Mặc định là TCP Connect

        self.tcp_connect_radio = ttk.Radiobutton(scan_type_frame, text="TCP Connect Scan", variable=self.scan_type_var, value="TCP_CONNECT")
        self.tcp_connect_radio.grid(row=0, column=0, sticky=tk.W, pady=2)

        self.tcp_syn_radio = ttk.Radiobutton(scan_type_frame, text="TCP SYN Scan (cần Admin/Root)", variable=self.scan_type_var, value="TCP_SYN", state=tk.DISABLED if not SCAPY_AVAILABLE else tk.NORMAL)
        self.tcp_syn_radio.grid(row=1, column=0, sticky=tk.W, pady=2)
        if not SCAPY_AVAILABLE:
            ttk.Label(scan_type_frame, text="(Yêu cầu Scapy)", foreground="red").grid(row=2, column=0, sticky=tk.W)

        self.udp_scan_radio = ttk.Radiobutton(scan_type_frame, text="UDP Scan (cần Admin/Root)", variable=self.scan_type_var, value="UDP", state=tk.DISABLED if not SCAPY_AVAILABLE else tk.NORMAL)
        self.udp_scan_radio.grid(row=3, column=0, sticky=tk.W, pady=2)
        if not SCAPY_AVAILABLE:
            ttk.Label(scan_type_frame, text="(Yêu cầu Scapy)", foreground="red").grid(row=4, column=0, sticky=tk.W)


        # Banner Grabbing
        self.banner_grab_var = tk.BooleanVar(value=True) # Mặc định bật banner grabbing
        ttk.Checkbutton(input_frame, text="Thực hiện Banner Grabbing", variable=self.banner_grab_var).grid(row=5, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)

        # --- Nút điều khiển ---
        control_frame = ttk.Frame(self.master, padding="10")
        control_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=10, pady=5)
        control_frame.grid_columnconfigure(0, weight=1)
        control_frame.grid_columnconfigure(1, weight=1)
        control_frame.grid_columnconfigure(2, weight=1) # Để căn giữa các nút

        self.start_button = ttk.Button(control_frame, text="Bắt đầu Quét", command=self.start_scan)
        self.start_button.grid(row=0, column=0, sticky=tk.E, padx=5)

        self.stop_button = ttk.Button(control_frame, text="Dừng Quét", command=self.stop_scan, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, sticky=tk.W, padx=5)

        self.clear_button = ttk.Button(control_frame, text="Xóa Kết quả", command=self.clear_results)
        self.clear_button.grid(row=0, column=2, sticky=tk.W, padx=5)

        # --- Thanh trạng thái và tiến độ ---
        self.status_label = ttk.Label(self.master, text="Sẵn sàng.", relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.grid(row=2, column=0, sticky=(tk.W, tk.E), padx=10, pady=5)

        self.progress_bar = ttk.Progressbar(self.master, orient="horizontal", length=100, mode="determinate")
        self.progress_bar.grid(row=2, column=0, sticky=(tk.W, tk.E), padx=10, pady=(0, 5), columnspan=1) # Căn chỉnh lại progress bar


        # --- Khu vực hiển thị kết quả (Treeview) ---
        self.results_tree = ttk.Treeview(self.master, columns=("ip", "port", "status", "rtt", "banner"), show="headings")
        self.results_tree.heading("ip", text="IP", anchor=tk.W)
        self.results_tree.heading("port", text="Cổng", anchor=tk.W)
        self.results_tree.heading("status", text="Trạng thái", anchor=tk.W)
        self.results_tree.heading("rtt", text="RTT", anchor=tk.W)
        self.results_tree.heading("banner", text="Banner/Dịch vụ", anchor=tk.W)

        self.results_tree.column("ip", width=120, stretch=tk.NO)
        self.results_tree.column("port", width=80, stretch=tk.NO)
        self.results_tree.column("status", width=120, stretch=tk.NO)
        self.results_tree.column("rtt", width=80, stretch=tk.NO)
        self.results_tree.column("banner", width=300, stretch=tk.YES)

        self.results_tree.grid(row=3, column=0, sticky=(tk.N, tk.S, tk.W, tk.E), padx=10, pady=10)

        # Thanh cuộn cho Treeview
        scrollbar = ttk.Scrollbar(self.master, orient=tk.VERTICAL, command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=3, column=1, sticky=(tk.N, tk.S), padx=(0,10), pady=10)

    def update_status(self, message, is_error=False):
        """Cập nhật thanh trạng thái của GUI."""
        self.status_label.config(text=message)
        if is_error:
            self.status_label.config(foreground="red")
        else:
            self.status_label.config(foreground="black")

    def clear_results(self):
        """Xóa tất cả các hàng trong Treeview."""
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self.update_progress(0)
        self.update_status("Kết quả đã được xóa.")

    def update_progress(self, value, maximum=100):
        """Cập nhật thanh tiến độ."""
        self.progress_bar["maximum"] = maximum
        self.progress_bar["value"] = value
        self.master.update_idletasks() # Cập nhật ngay lập tức

    def add_result_to_tree(self, ip, port, status, rtt, banner):
        """Thêm một hàng kết quả vào Treeview."""
        self.results_tree.insert("", tk.END, values=(ip, port, status, rtt, banner))

    def validate_inputs(self):
        """Kiểm tra tính hợp lệ của các trường nhập liệu."""
        ip_start_str = self.ip_start_entry.get().strip()
        ip_end_str = self.ip_end_entry.get().strip()
        port_start_str = self.port_start_entry.get().strip()
        port_end_str = self.port_end_entry.get().strip()
        timeout_str = self.timeout_entry.get().strip()

        try:
            ip_start = ipaddress.IPv4Address(ip_start_str)
            ip_end = ipaddress.IPv4Address(ip_end_str)
            if ip_start > ip_end:
                raise ValueError("IP bắt đầu không thể lớn hơn IP kết thúc.")

            port_start = int(port_start_str)
            port_end = int(port_end_str)
            if not (1 <= port_start <= 65535) or not (1 <= port_end <= 65535):
                raise ValueError("Cổng phải nằm trong khoảng 1-65535.")
            if port_start > port_end:
                raise ValueError("Cổng bắt đầu không thể lớn hơn cổng kết thúc.")

            timeout = float(timeout_str)
            if timeout <= 0:
                raise ValueError("Timeout phải là một số dương.")

        except ValueError as e:
            self.update_status(f"Lỗi nhập liệu: {e}", is_error=True)
            return None, None, None, None, None
        except ipaddress.AddressValueError as e:
            self.update_status(f"Lỗi định dạng IP: {e}", is_error=True)
            return None, None, None, None, None

        return ip_start, ip_end, port_start, port_end, timeout

    def start_scan(self):
        """Bắt đầu quá trình quét."""
        ip_start, ip_end, port_start, port_end, timeout = self.validate_inputs()
        if ip_start is None:
            return

        self.clear_results()
        self.update_status("Đang chuẩn bị quét...", is_error=False)
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.clear_button.config(state=tk.DISABLED)

        self.stop_scan_event.clear() # Đặt lại cờ dừng
        self.scanning_thread = threading.Thread(
            target=self._run_scan_in_thread,
            args=(ip_start, ip_end, port_start, port_end, timeout)
        )
        self.scanning_thread.daemon = True # Cho phép thread đóng khi app đóng
        self.scanning_thread.start()

    def stop_scan(self):
        """Dừng quá trình quét."""
        self.stop_scan_event.set() # Đặt cờ dừng
        self.update_status("Đang yêu cầu dừng quét...", is_error=False)
        self.stop_button.config(state=tk.DISABLED)

    def on_closing(self):
        """Xử lý khi đóng cửa sổ ứng dụng."""
        if self.scanning_thread and self.scanning_thread.is_alive():
            self.stop_scan_event.set() # Yêu cầu dừng quét
            messagebox.showinfo("Đang dừng quét", "Đang chờ quá trình quét dừng lại. Vui lòng đợi trong giây lát.")
            # Đợi thread dừng lại một cách nhẹ nhàng (có timeout để tránh treo)
            self.scanning_thread.join(timeout=5)
        self.master.destroy() # Đóng cửa sổ

    def _run_scan_in_thread(self, ip_start, ip_end, port_start, port_end, timeout):
        """
        Hàm này chạy trong một luồng riêng biệt để quản lý asyncio event loop.
        """
        self.async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.async_loop)
        try:
            self.async_loop.run_until_complete(
                self._scan_ip_and_ports_async(ip_start, ip_end, port_start, port_end, timeout)
            )
        except asyncio.CancelledError:
            self.master.after(0, lambda: self.update_status("Quét đã bị hủy.", is_error=True)) # Đã sửa
        except Exception as e:
            self.master.after(0, lambda: self.update_status(f"Lỗi không mong muốn trong quá trình quét: {e}", is_error=True)) # Đã sửa
        finally:
            self.async_loop.close()
            self.async_loop = None # Đặt lại tham chiếu
            self.master.after(0, lambda: self.start_button.config(state=tk.NORMAL))
            self.master.after(0, lambda: self.stop_button.config(state=tk.DISABLED))
            self.master.after(0, lambda: self.clear_button.config(state=tk.NORMAL))


    async def _scan_ip_and_ports_async(self, ip_start_obj, ip_end_obj, port_start, port_end, timeout):
        """
        Chức năng quét chính, chạy bất đồng bộ để xử lý nhiều IP/cổng.
        """
        scan_type = self.scan_type_var.get()
        do_banner_grab = self.banner_grab_var.get()

        all_ips = []
        current_ip = ip_start_obj
        while current_ip <= ip_end_obj:
            all_ips.append(str(current_ip))
            current_ip += 1

        total_ports_to_scan = len(all_ips) * (port_end - port_start + 1)
        scanned_ports_count = 0

        self.master.after(0, self.update_status, f"Bắt đầu quét {total_ports_to_scan} cổng trên {len(all_ips)} IP...")

        tasks = []
        for ip_str in all_ips:
            for port in range(port_start, port_end + 1):
                if self.stop_scan_event.is_set():
                    # Hủy tất cả các tác vụ đang chờ nếu cờ dừng được đặt
                    for task in tasks:
                        task.cancel()
                    self.master.after(0, self.update_status, "Quá trình quét đã dừng.", is_error=True)
                    return

                # Dựa vào loại quét đã chọn
                if scan_type == "TCP_CONNECT":
                    task = asyncio.create_task(tcp_connect_scan(ip_str, port, timeout))
                elif scan_type == "TCP_SYN" and SCAPY_AVAILABLE:
                    task = asyncio.create_task(tcp_syn_scan(ip_str, port, timeout))
                elif scan_type == "UDP" and SCAPY_AVAILABLE:
                    task = asyncio.create_task(udp_scan(ip_str, port, timeout))
                else:
                    # Fallback hoặc thông báo lỗi nếu Scapy không có nhưng loại quét yêu cầu Scapy
                    self.master.after(0, self.add_result_to_tree, ip_str, port, "Lỗi: Quét không khả dụng", "N/A", "Cần Scapy/Admin")
                    continue
                
                tasks.append(task)
                active_tasks.append(task) # Thêm vào hàng đợi các tác vụ đang chạy

                # Xử lý kết quả ngay khi chúng sẵn sàng để cập nhật GUI liên tục
                if len(tasks) >= 50: # Giới hạn số lượng tác vụ đồng thời để tránh quá tải
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for completed_task in done:
                        # Đã sửa: Giờ đây result() trả về 5 giá trị
                        ip, port_num, status, banner_result, rtt = completed_task.result() 
                        scanned_ports_count += 1
                        self.master.after(0, self.add_result_to_tree, ip, port_num, status, rtt, banner_result)
                        self.master.after(0, self.update_progress, scanned_ports_count, total_ports_to_scan)
                        active_tasks.remove(completed_task) # Xóa khỏi hàng đợi
                    tasks = list(pending) # Tiếp tục với các tác vụ còn lại

        # Chờ tất cả các tác vụ còn lại hoàn thành
        if tasks:
            done, pending = await asyncio.wait(tasks)
            for completed_task in done:
                # Đã sửa: Giờ đây result() trả về 5 giá trị
                ip, port_num, status, banner_result, rtt = completed_task.result()
                scanned_ports_count += 1
                self.master.after(0, self.add_result_to_tree, ip, port_num, status, rtt, banner_result)
                self.master.after(0, self.update_progress, scanned_ports_count, total_ports_to_scan)
                active_tasks.remove(completed_task) # Xóa khỏi hàng đợi

        self.master.after(0, self.update_status, f"Quét hoàn tất. Đã quét {scanned_ports_count}/{total_ports_to_scan} cổng.")
        self.master.after(0, self.update_progress, 0) # Reset progress bar


# --- Hàm chính để chạy ứng dụng ---
if __name__ == "__main__":
    root = tk.Tk()
    app = PortScannerApp(root)
    root.mainloop()

    # Đảm bảo tất cả các tác vụ asyncio được hủy khi ứng dụng đóng
    # Điều này quan trọng nếu ứng dụng bị đóng đột ngột trong khi quét đang chạy
    if app.async_loop and not app.async_loop.is_closed():
        for task in list(active_tasks): # Sao chép để tránh lỗi khi sửa đổi deque
            task.cancel()
        # Chờ các tác vụ hoàn tất việc hủy, có thể gây chặn một chút khi đóng
        # Nếu muốn đóng ngay lập tức, có thể bỏ qua await này
        try:
            app.async_loop.run_until_complete(asyncio.gather(*active_tasks, return_exceptions=True))
        except RuntimeError:
            pass # Loop may be already closed or stopping
        finally:
            if not app.async_loop.is_closed():
                app.async_loop.close()
