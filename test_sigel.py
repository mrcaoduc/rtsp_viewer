import requests
import time
import urllib3
import threading
from statistics import mean
import tkinter as tk
from tkinter import messagebox, scrolledtext

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class ConnectionTesterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Connection Stability Tester")
        self.running = False
        self.results = {}
        self.thread = None

        # Make the GUI resizable
        for i in range(2):
            self.root.columnconfigure(i, weight=1)
        for i in range(5):
            self.root.rowconfigure(i, weight=1)

        # Label
        tk.Label(root, text="Enter URLs (separated by ; or newline):").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 0)
        )

        # URL input box
        self.url_input = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=5)
        self.url_input.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10))

        # Button frame (horizontal)
        self.button_frame = tk.Frame(root)
        self.button_frame.grid(row=2, column=0, columnspan=2, pady=5)
        self.button_frame.columnconfigure(0, weight=1)
        self.button_frame.columnconfigure(1, weight=1)

        self.start_btn = tk.Button(
            self.button_frame, text="▶ Start Test", height=2, width=20,
            command=self.start_testing
        )
        self.start_btn.grid(row=0, column=0, padx=10, pady=5, sticky="ew")

        self.stop_btn = tk.Button(
            self.button_frame, text="⏹ Stop & Evaluate", height=2, width=20,
            command=self.stop_testing, state="disabled"
        )
        self.stop_btn.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        # Status display
        self.status_display = scrolledtext.ScrolledText(root, wrap=tk.WORD, state="disabled")
        self.status_display.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10))

    def log(self, message):
        self.status_display.config(state="normal")
        self.status_display.insert(tk.END, message + "\n")
        self.status_display.see(tk.END)
        self.status_display.config(state="disabled")

    def start_testing(self):
        raw = self.url_input.get("1.0", tk.END).strip()
        self.urls = [url.strip() for line in raw.splitlines() for url in line.split(";") if url.strip()]
        if not self.urls:
            messagebox.showerror("Error", "Please enter at least one valid URL.")
            return

        self.running = True
        self.results = {url: [] for url in self.urls}
        self.start_btn.config(state="disabled", highlightbackground="#90ee90", highlightthickness=2)
        self.stop_btn.config(state="normal", highlightthickness=0)
        self.log("🔍 Starting connection test...\n")
        self.thread = threading.Thread(target=self.test_loop)
        self.thread.start()

    def stop_testing(self):
        self.running = False
        self.start_btn.config(highlightthickness=0)
        self.stop_btn.config(highlightbackground="#ff7f7f", highlightthickness=2)
        self.log("\n🧠 Evaluating connection data...\n")
        self.thread.join()
        self.evaluate_results()
        self.stop_btn.config(highlightthickness=0)
        self.start_btn.config(state="normal")

    def test_loop(self):
        while self.running:
            for url in self.urls:
                start = time.time()
                try:
                    r = requests.get(url, timeout=5, verify=False)
                    latency = time.time() - start
                    self.results[url].append(("success", latency))
                    self.log(f"[{time.strftime('%H:%M:%S')}] ✔ {url} — Status {r.status_code}, {latency:.3f}s")
                except requests.exceptions.RequestException as e:
                    self.results[url].append(("fail", None))
                    self.log(f"[{time.strftime('%H:%M:%S')}] ❌ {url} — Failed: {e}")
            time.sleep(0.5)

    def evaluate_results(self):
        output = ""
        for url in self.urls:
            entries = self.results[url]
            success = sum(1 for r in entries if r[0] == "success")
            fail = sum(1 for r in entries if r[0] == "fail")
            latencies = [r[1] for r in entries if r[0] == "success"]
            avg_latency = mean(latencies) if latencies else 0.0

            stability = "Stable" if fail == 0 else "Unstable"
            speed = "Fast" if avg_latency < 0.3 else "Moderate" if avg_latency < 0.7 else "Slow"

            suggestion = (
                "- Check local network/firewall/SSL settings.\n"
                "- Use VPN or tunneling tools for consistent connection."
                if fail > 0 else "- No action needed. Connection is stable."
            )

            output += f"Result for: {url}\n"
            output += "+-----------------+-----------------+-----------------+-------------------------+\n"
            output += "| Total Attempts  | Success Count   | Failure Count   | Avg Latency (seconds)  |\n"
            output += "+-----------------+-----------------+-----------------+-------------------------+\n"
            output += f"| {len(entries):<15} | {success:<15} | {fail:<15} | {avg_latency:<23.3f} |\n"
            output += "+-----------------+-----------------+-----------------+-------------------------+\n"
            output += f"Stability: {stability}\n"
            output += f"Speed: {speed}\n"
            output += "Recommendation:\n"
            output += f"{suggestion}\n"
            output += "-" * 50 + "\n\n"

        self.log(output)

        with open("connection_report.txt", "w", encoding="utf-8") as f:
            f.write(output)

        self.log("📁 Report saved to connection_report.txt")
        messagebox.showinfo("Done", "Analysis complete.\nReport saved to connection_report.txt")

# Launch the app
if __name__ == "__main__":
    root = tk.Tk()
    app = ConnectionTesterGUI(root)
    root.mainloop()