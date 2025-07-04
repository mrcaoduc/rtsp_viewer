import requests
import time
import urllib3
from statistics import mean

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

urls = [
    "https://153.139.29.130:54006/",
    "https://14.192.108.249:443/"
]

results = {url: [] for url in urls}
log_lines = []

print("🔍 Starting connection checks...\nPress Ctrl+C to stop and evaluate.\n")

try:
    while True:
        for url in urls:
            start = time.time()
            try:
                r = requests.get(url, timeout=5, verify=False)
                latency = time.time() - start
                results[url].append(("success", latency))
                print(f"[{time.strftime('%H:%M:%S')}] ✔ {url} — Status {r.status_code}, {latency:.3f}s")
            except requests.exceptions.RequestException as e:
                results[url].append(("fail", None))
                print(f"[{time.strftime('%H:%M:%S')}] ❌ {url} — Connection failed: {e}")
            time.sleep(0.5)

except KeyboardInterrupt:
    print("\n📊 Analyzing results...\n")

    for url in urls:
        entries = results[url]
        success_count = sum(1 for r in entries if r[0] == "success")
        fail_count = sum(1 for r in entries if r[0] == "fail")
        latencies = [r[1] for r in entries if r[0] == "success"]
        avg_latency = mean(latencies) if latencies else None

        # Stability evaluation
        stability = "Stable" if fail_count == 0 else "Unstable"
        if avg_latency is not None:
            if avg_latency < 0.3:
                speed = "Fast"
            elif avg_latency < 0.7:
                speed = "Moderate"
            else:
                speed = "Slow"
        else:
            speed = "Unknown"

        # Recommendation
        if fail_count > 0:
            suggestion = (
                "- Check local network or server port availability.\n"
                "- Verify firewall, SSL, and DNS configuration.\n"
                "- Consider tunneling (e.g., Cloudflare Tunnel) for stable connectivity."
            )
        else:
            suggestion = "- No issues detected. Connection is stable."

        report = (
            f"▶️ Result for: {url}\n"
            f"- Total attempts: {len(entries)}\n"
            f"- Successful: {success_count}, Failed: {fail_count}\n"
            f"- Average latency: {avg_latency:.3f}s\n"
            f"- Stability: {stability}, Speed: {speed}\n"
            f"- Suggested action:\n{suggestion}\n"
            + "-" * 50 + "\n"
        )

        print(report)
        log_lines.append(report)

    # Save to file
    with open("connection_report.txt", "w", encoding="utf-8") as f:
        f.writelines(log_lines)

    print("✅ Connection report saved to: connection_report.txt\n🔚 Program exited.")