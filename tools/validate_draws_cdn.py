#!/usr/bin/env python3
"""
==============================================================================
THE ORACLE ENGINE — TIER 2 CDN VERIFICATION UTILITY
Module: tools/validate_draws_cdn.py
Version: 1.0.0
Authoritative Alignment: ARCHITECTURE_CODING_STANDARDS_V6 (Section IV & V)

Purpose:
  1. Ingests and validates Tier 2 CDN 'draws.json' against strict schema rules.
  2. Computes draw horizons, chronological bounds, and game counts (PB & MM).
  3. Detects and reports invalid JSON draw records with pinpoint reasons.
  4. Dynamically publishes 'refresh_report.html' for live admin inspection.
  5. Enforces Rule #5 Fail-Loud Policy: Dispatches Google Chat #ops-alerts 
     webhooks if any schema violations or parse failures are detected.

Standard Library Only: Zero external pip dependencies required.
==============================================================================
"""

import json
import os
import sys
import re
import urllib.request
from datetime import datetime

VALIDATE_DRAWS_CDN_VER = "1.0.0"

# ISO Date Regex Pattern: YYYY-MM-DD
DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def locate_draws_file():
    """
    Locates the target draws.json file from CLI arguments or default paths.
    """
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        return sys.argv[1]
    
    # Check current directory, root directory, or parent directory
    candidates = [
        "draws.json",
        os.path.join("..", "draws.json"),
        os.path.join(os.path.dirname(__file__), "..", "draws.json"),
        os.path.join(os.path.dirname(__file__), "draws.json")
    ]
    for path in candidates:
        if os.path.exists(path):
            return os.path.abspath(path)
            
    return None


def post_to_google_chat(webhook_url, message_text):
    """
    Dispatches a structured operational alert to Google Chat #ops-alerts.
    Matches the schema and formatting established in DataPump.gs.
    """
    if not webhook_url:
        print("[AUDIT NOTICE] OPS_WEBHOOK_URL not configured. Webhook alert skipped.")
        return

    payload = {
        "text": f"🚨 *ORACLE ENGINE CDN AUDIT ALERT* 🚨\n{message_text}"
    }
    
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json; charset=UTF-8"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status in (200, 204):
                print("✅ Successfully dispatched alert to Google Chat #ops-alerts.")
            else:
                print(f"⚠️ Webhook responded with HTTP {response.status}")
    except Exception as e:
        print(f"🚨 [WEBHOOK ERROR] Failed to post alert to Google Chat: {e}")


def validate_single_record(record, index):
    """
    Validates a single draw dictionary against the authoritative schema rules:
      - Required keys present
      - game_code in ('PB', 'MM')
      - draw_date matching YYYY-MM-DD
      - 5 unique sorted white balls within game limits (PB: 1..69, MM: 1..70)
      - 1 bonus ball within game limits (PB: 1..26, MM: 1..25)
    Returns: (is_valid: bool, reason: str)
    """
    if not isinstance(record, dict):
        return False, "Record is not a valid JSON object."

    required_keys = ["game_code", "draw_date", "b1", "b2", "b3", "b4", "b5", "bonus"]
    missing = [k for k in required_keys if k not in record]
    if missing:
        return False, f"Missing required keys: {', '.join(missing)}"

    game_code = record.get("game_code")
    if game_code not in ("PB", "MM"):
        return False, f"Invalid game_code '{game_code}'. Must be 'PB' or 'MM'."

    draw_date = str(record.get("draw_date", "")).strip()
    if not DATE_REGEX.match(draw_date):
        return False, f"Invalid draw_date format '{draw_date}'. Expected 'YYYY-MM-DD'."

    try:
        wb = [
            int(record["b1"]),
            int(record["b2"]),
            int(record["b3"]),
            int(record["b4"]),
            int(record["b5"])
        ]
        bonus = int(record["bonus"])
    except (ValueError, TypeError):
        return False, "White balls (b1..b5) and bonus must be valid integers."

    max_wb = 69 if game_code == "PB" else 70
    max_bonus = 26 if game_code == "PB" else 25

    for idx, b in enumerate(wb, start=1):
        if b < 1 or b > max_wb:
            return False, f"Ball b{idx} ({b}) is outside valid {game_code} range (1..{max_wb})."

    if bonus < 1 or bonus > max_bonus:
        return False, f"Bonus ball ({bonus}) is outside valid {game_code} range (1..{max_bonus})."

    if len(set(wb)) != 5:
        return False, f"Duplicate white balls detected in set: {wb}"

    if wb != sorted(wb):
        return False, f"White balls are not sorted ascending: {wb}"

    return True, "Valid"


def generate_html_report(metrics, output_path):
    """
    Renders a high-contrast, museum-matted 'refresh_report.html' dashboard 
    styled with Ivory (#F4F1E2), Dark Slate (#1E293B), and Emerald Green (#16A34A).
    """
    is_healthy = metrics["invalid_count"] == 0 and metrics["fatal_error"] is None
    status_badge_color = "#16a34a" if is_healthy else "#dc2626"
    status_text = "SYSTEM HEALTHY & SYNCHRONIZED" if is_healthy else "ANOMALY DETECTED — ACTION REQUIRED"
    timestamp_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    invalid_rows_html = ""
    if metrics["invalid_records"]:
        for item in metrics["invalid_records"]:
            raw_preview = json.dumps(item["raw"], separators=(',', ':'))
            invalid_rows_html += f"""
            <tr>
              <td style="padding: 10px; border: 1px solid #cbd5e1; font-weight: bold; color: #dc2626;">#{item['index']}</td>
              <td style="padding: 10px; border: 1px solid #cbd5e1; color: #991b1b; font-weight: 600;">{item['reason']}</td>
              <td style="padding: 10px; border: 1px solid #cbd5e1; font-family: monospace; font-size: 12px; background: #f8fafc;">{raw_preview}</td>
            </tr>
            """
    else:
        invalid_rows_html = """
        <tr>
          <td colspan="3" style="padding: 16px; text-align: center; color: #16a34a; font-weight: 600;">
            Zero invalid records. All draw items strictly conform to Tier 2 schema standards.
          </td>
        </tr>
        """

    fatal_alert_banner = ""
    if metrics["fatal_error"]:
        fatal_alert_banner = f"""
        <div style="background-color: #fee2e2; border-left: 6px solid #dc2626; padding: 16px; margin-bottom: 24px; border-radius: 8px;">
          <h3 style="margin: 0 0 8px 0; color: #991b1b;">Fatal Parsing Error</h3>
          <p style="margin: 0; color: #7f1d1d; font-family: monospace;">{metrics['fatal_error']}</p>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>The Oracle Engine — CDN Ingestion Telemetry</title>
  <style>
    body {{
      background-color: #F4F1E2;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      margin: 0;
      padding: 32px 16px;
      color: #1e293b;
    }}
    .container {{
      max-width: 900px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.08);
      border: 2px solid #e2e8f0;
      overflow: hidden;
    }}
    .header {{
      background: #1e293b;
      padding: 24px 32px;
      color: #ffffff;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
    }}
    .header h1 {{
      margin: 0;
      font-size: 22px;
      letter-spacing: 0.5px;
    }}
    .badge {{
      background-color: {status_badge_color};
      color: #ffffff;
      font-size: 13px;
      font-weight: 800;
      padding: 6px 14px;
      border-radius: 9999px;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }}
    .content {{
      padding: 32px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }}
    .card {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 20px;
    }}
    .card-title {{
      font-size: 12px;
      font-weight: 700;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }}
    .card-value {{
      font-size: 26px;
      font-weight: 900;
      color: #0f172a;
    }}
    .card-subtext {{
      font-size: 13px;
      color: #475569;
      margin-top: 6px;
    }}
    .table-container {{
      overflow-x: auto;
      margin-top: 24px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }}
    th {{
      background-color: #f1f5f9;
      padding: 12px 10px;
      border: 1px solid #cbd5e1;
      font-size: 13px;
      font-weight: 800;
      color: #334155;
      text-transform: uppercase;
    }}
    .footer {{
      padding: 16px 32px;
      background: #f8fafc;
      border-top: 1px solid #e2e8f0;
      text-align: right;
      font-size: 12px;
      color: #64748b;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <h1>The Oracle Engine — CDN Telemetry</h1>
        <div style="font-size: 13px; color: #94a3b8; margin-top: 4px;">Tier 2 Stateless Distribution Bridge Audit</div>
      </div>
      <div class="badge">{status_text}</div>
    </div>
    
    <div class="content">
      {fatal_alert_banner}

      <div class="grid">
        <div class="card">
          <div class="card-title">Total Records</div>
          <div class="card-value">{metrics['total_records']}</div>
          <div class="card-subtext">Ingested Draws</div>
        </div>
        <div class="card">
          <div class="card-title">Powerball (PB) Horizon</div>
          <div class="card-value">{metrics['total_pb']}</div>
          <div class="card-subtext">Bounds: {metrics['pb_first']} → {metrics['pb_last']}</div>
        </div>
        <div class="card">
          <div class="card-title">Mega Millions (MM) Horizon</div>
          <div class="card-value">{metrics['total_mm']}</div>
          <div class="card-subtext">Bounds: {metrics['mm_first']} → {metrics['mm_last']}</div>
        </div>
        <div class="card" style="border-left: 4px solid {status_badge_color};">
          <div class="card-title">Invalid Records</div>
          <div class="card-value" style="color: {status_badge_color};">{metrics['invalid_count']}</div>
          <div class="card-subtext">Schema Violations</div>
        </div>
      </div>

      <h2 style="font-size: 18px; color: #1e293b; margin-bottom: 12px;">Schema Anomaly Ledger</h2>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th style="width: 80px;">Index</th>
              <th style="width: 240px;">Violation Reason</th>
              <th>Raw Payload Preview</th>
            </tr>
          </thead>
          <tbody>
            {invalid_rows_html}
          </tbody>
        </table>
      </div>
    </div>

    <div class="footer">
      Generated automatically by <strong>validate_draws_cdn.py (v{VALIDATE_DRAWS_CDN_VER})</strong> &bull; {timestamp_str}
    </div>
  </div>
</body>
</html>
"""
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"✅ Telemetry HTML dashboard successfully saved: {output_path}")
    except Exception as e:
        print(f"🚨 [FILE WRITE ERROR] Failed to save HTML report: {e}")


def main():
    print("=" * 64)
    print(f"  THE ORACLE ENGINE — TIER 2 CDN VERIFIER (v{VALIDATE_DRAWS_CDN_VER})")
    print("=" * 64)

    draws_file = locate_draws_file()
    webhook_url = os.environ.get("OPS_WEBHOOK_URL", "").strip()

    metrics = {
        "total_records": 0,
        "total_pb": 0,
        "pb_first": "N/A",
        "pb_last": "N/A",
        "total_mm": 0,
        "mm_first": "N/A",
        "mm_last": "N/A",
        "invalid_count": 0,
        "invalid_records": [],
        "fatal_error": None
    }

    if not draws_file:
        error_msg = "CRITICAL: 'draws.json' could not be found in the current working tree."
        print(f"🚨 {error_msg}")
        metrics["fatal_error"] = error_msg
        
        # Save HTML and post alert
        report_output = os.path.abspath("refresh_report.html")
        generate_html_report(metrics, report_output)
        post_to_google_chat(webhook_url, f"Fatal Ingestion Error: {error_msg}")
        sys.exit(1)

    print(f"📂 Ingesting payload from: {draws_file}")

    try:
        with open(draws_file, "r", encoding="utf-8") as f:
            raw_text = f.read()
            data = json.loads(raw_text)
    except json.JSONDecodeError as err:
        error_msg = f"Fatal JSON Syntax Decode Error at Line {err.lineno}, Col {err.colno}: {err.msg}"
        print(f"🚨 {error_msg}")
        metrics["fatal_error"] = error_msg
        metrics["invalid_count"] = 1
        
        report_output = os.path.join(os.path.dirname(draws_file), "refresh_report.html")
        generate_html_report(metrics, report_output)
        post_to_google_chat(webhook_url, f"JSON Parse Failed: {error_msg}")
        sys.exit(1)

    if not isinstance(data, list):
        error_msg = f"Schema Root Violation: Expected a JSON array at root, received '{type(data).__name__}'."
        print(f"🚨 {error_msg}")
        metrics["fatal_error"] = error_msg
        metrics["invalid_count"] = 1
        
        report_output = os.path.join(os.path.dirname(draws_file), "refresh_report.html")
        generate_html_report(metrics, report_output)
        post_to_google_chat(webhook_url, f"Root Schema Mismatch: {error_msg}")
        sys.exit(1)

    metrics["total_records"] = len(data)
    pb_dates = []
    mm_dates = []

    for index, record in enumerate(data):
        is_valid, reason = validate_single_record(record, index)
        if not is_valid:
            metrics["invalid_count"] += 1
            metrics["invalid_records"].append({
                "index": index,
                "reason": reason,
                "raw": record
            })
            continue

        game_code = record["game_code"]
        draw_date = record["draw_date"]

        if game_code == "PB":
            metrics["total_pb"] += 1
            pb_dates.append(draw_date)
        elif game_code == "MM":
            metrics["total_mm"] += 1
            mm_dates.append(draw_date)

    # Calculate date boundaries (min / max)
    if pb_dates:
        metrics["pb_first"] = min(pb_dates)
        metrics["pb_last"] = max(pb_dates)
    if mm_dates:
        metrics["mm_first"] = min(mm_dates)
        metrics["mm_last"] = max(mm_dates)

    # Formatted Console Telemetry
    print("-" * 64)
    print(f"  Total Records Ingested:   {metrics['total_records']}")
    print(f"  Total PB Records:         {metrics['total_pb']}")
    print(f"  First PB Draw Date:       {metrics['pb_first']}")
    print(f"  Last PB Draw Date:        {metrics['pb_last']}")
    print(f"  Total MM Records:         {metrics['total_mm']}")
    print(f"  First MM Draw Date:       {metrics['mm_first']}")
    print(f"  Last MM Draw Date:        {metrics['mm_last']}")
    print(f"  Count of Invalid Draws:   {metrics['invalid_count']}")
    print("-" * 64)

    if metrics["invalid_records"]:
        print("🚨 LISTING OF INVALID JSON DRAWS RECORDS:")
        for inv in metrics["invalid_records"]:
            print(f"  [Index {inv['index']}]: Reason -> {inv['reason']}")
            print(f"    Payload: {inv['raw']}")
        print("-" * 64)

    # Determine output location for HTML report (repository root)
    target_repo_root = os.path.dirname(draws_file) if os.path.isabs(draws_file) else os.getcwd()
    report_output = os.path.join(target_repo_root, "refresh_report.html")
    generate_html_report(metrics, report_output)

    # Fail-Loud Dispatch: Alert Google Chat if anomalies exist
    if metrics["invalid_count"] > 0:
        alert_text = (
            f"Schema Validation Failed on draws.json!\n"
            f"• Invalid Count: {metrics['invalid_count']}\n"
            f"• Total Records: {metrics['total_records']}\n"
            f"• PB Horizon: {metrics['total_pb']} ({metrics['pb_first']} to {metrics['pb_last']})\n"
            f"• MM Horizon: {metrics['total_mm']} ({metrics['mm_first']} to {metrics['mm_last']})\n"
            f"View details at https://theoracle.prestoninformatics.com/refresh_report.html"
        )
        post_to_google_chat(webhook_url, alert_text)
        print("🚨 Validation failed. Google Chat operational alert triggered.")
        sys.exit(1)

    print("🎉 All draw records validated successfully. Zero schema violations.")
    print("=" * 64)


if __name__ == "__main__":
    main()
