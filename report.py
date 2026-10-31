#!/usr/bin/env python3
"""Generate HTML and CSV reports from a local, synthetic CDR JSON fixture."""
import argparse
import csv
import json
import os
from datetime import date, datetime, time, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from analytics import analyze


def load_config():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    timezone = ZoneInfo(os.getenv("TIMEZONE", "Africa/Nairobi"))
    default_map = {
        "Customer Experience": {"extensions": ["2001", "2002"], "queues": ["DEMO-CX"], "ring_groups": ["DEMO-CX-RG"]},
        "Collections": {"extensions": ["2101", "2102"], "queues": ["DEMO-COLLECTIONS"], "ring_groups": ["DEMO-COLLECTIONS-RG"]},
    }
    raw_map = os.getenv("DEPARTMENT_MAP_JSON")
    return timezone, json.loads(raw_map) if raw_map else default_map, int(os.getenv("SLA_CALLBACK_HOURS", "4"))


def pct(n, total):
    return 100 * n / total if total else 0.0


def make_html(result, start, end):
    def table(headers, rows):
        head = "".join(f"<th>{escape(str(x))}</th>" for x in headers)
        body = "".join("<tr>" + "".join(f"<td>{escape(str(x))}</td>" for x in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    inbound = len(result["inbound"])
    outbound = len(result["outbound"])
    summary = [
        ("Inbound calls", inbound, "100.0%"),
        ("Answered inbound", len(result["answered"]), f"{pct(len(result['answered']), inbound):.1f}%"),
        ("Missed / busy / failed", len(result["missed"]), f"{pct(len(result['missed']), inbound):.1f}%"),
        ("Abandoned", len(result["abandoned"]), f"{pct(len(result['abandoned']), inbound):.1f}%"),
        ("Voicemail", len(result["voicemail"]), f"{pct(len(result['voicemail']), inbound):.1f}%"),
        ("Outbound calls", outbound, "—"),
    ]
    team_rows = []
    for team, rows in sorted(result["by_team"].items()):
        ins = [r for r in rows if r.get("call_type", "").lower() == "inbound"]
        outs = [r for r in rows if r.get("call_type", "").lower() == "outbound"]
        team_rows.append((team, len(ins), sum(r["_status"] == "ANSWERED" for r in ins), len(outs)))
    agent_rows = []
    for (team, agent), rows in sorted(result["by_agent"].items()):
        ins = [r for r in rows if r.get("call_type", "").lower() == "inbound"]
        outs = [r for r in rows if r.get("call_type", "").lower() == "outbound"]
        agent_rows.append((team, agent, len(rows), sum(r["_status"] == "ANSWERED" for r in ins), sum(r["_status"] in {"NO ANSWER", "NOANSWER", "BUSY", "FAILED"} for r in ins), sum(r["_status"] in {"NO ANSWER", "NOANSWER", "BUSY", "FAILED"} for r in outs)))
    repeat_rows = sorted(result["repeats"].items(), key=lambda x: -x[1])
    # Fixture numbers are fictional; a production export should mask caller identifiers.
    html = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Weekly Call Report</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;color:#202124;max-width:1100px;margin:32px auto;padding:0 18px}}header{{background:#171717;color:white;padding:24px;border-bottom:5px solid #c9a227}}h1{{margin:0}}h2{{margin-top:30px}}table{{width:100%;border-collapse:collapse;margin:12px 0 24px}}th,td{{padding:9px;text-align:left;border-bottom:1px solid #ddd}}th{{background:#f2f2f2}}.note{{background:#f7f7f7;padding:12px}}</style></head><body>
<header><h1>Weekly Call Performance</h1><div>{start:%d %b %Y} – {end:%d %b %Y}</div></header>
<p class='note'><b>Portfolio demo:</b> generated from synthetic call-detail records. Metrics are illustrative, not production results.</p>
<h2>Executive summary</h2>{table(['Metric','Calls','Share'], summary)}
<h2>Team comparison</h2>{table(['Team','Inbound','Answered inbound','Outbound'], team_rows)}
<h2>Agent / extension performance</h2>{table(['Team','Demo extension','Total CDRs','Answered inbound','Missed/failed inbound','Missed/failed outbound'], agent_rows)}
<h2>Unanswered / voicemail patterns</h2>{table(['Day','Calls'], result['by_day'].most_common())}
<h2>Repeat callers</h2>{table(['Synthetic caller ID','Inbound calls'], repeat_rows)}
<h2>Callback analysis</h2><p>{sum(x['callback_seconds'] is not None for x in result['callbacks'])} of {len(result['callbacks'])} missed/voicemail records had a possible same-caller outbound match inside the configured window. This is a heuristic, not proof of a completed callback or agent compliance.</p>
<h2>Interpretation notes</h2><ul><li>Missed/failed groups no-answer, busy, and failed outcomes. Abandoned and voicemail are separate.</li><li>Team attribution uses configured extension, queue, and ring-group identifiers.</li><li>Actual queue-offer history, IVR keypress drop-off, transfers, and escalation context depend on PBX CDR fields and may require additional event sources.</li></ul>
</body></html>"""
    return html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='data/sample_cdr.json')
    parser.add_argument('--live', action='store_true', help='Fetch CDRs from a Yeastar P-Series API using local .env settings')
    parser.add_argument('--output-dir', default='output')
    parser.add_argument('--start', help='Start date YYYY-MM-DD; defaults to previous complete week')
    parser.add_argument('--end', help='End date YYYY-MM-DD; defaults to previous complete week')
    args = parser.parse_args()
    timezone, department_map, callback_hours = load_config()
    today = datetime.now(timezone).date()
    monday = today - timedelta(days=today.weekday())
    start_date = date.fromisoformat(args.start) if args.start else monday - timedelta(days=7)
    end_date = date.fromisoformat(args.end) if args.end else monday - timedelta(days=1)
    start = datetime.combine(start_date, time.min, timezone)
    end = datetime.combine(end_date, time(23, 59, 59), timezone)
    if end < start:
        parser.error('--end must be on or after --start')
    if args.live:
        from yeastar_client import YeastarClient
        records = YeastarClient.from_environment(timezone).get_cdrs(start, end)
    else:
        records = json.loads(Path(args.input).read_text(encoding='utf-8'))
    result = analyze(records, start, end, department_map, callback_hours)
    if not result['calls']:
        raise SystemExit('No parseable CDR records in the selected period.')
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'weekly_report.html').write_text(make_html(result, start, end), encoding='utf-8')
    fields = ['time','call_type','last_status','team','agent','call_from_number','call_to_number','routing_duration','handling_duration','uid']
    with (out / 'call_incidents.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in result['calls']:
            writer.writerow({'time':row.get('time'),'call_type':row.get('call_type'),'last_status':row['_status'],'team':row['_team'],'agent':row['_agent'],'call_from_number':row.get('call_from_number'),'call_to_number':row.get('call_to_number'),'routing_duration':row.get('routing_duration'),'handling_duration':row.get('handling_duration'),'uid':row.get('uid')})
    print(f"Generated {out / 'weekly_report.html'}")
    print(f"Generated {out / 'call_incidents.csv'}")

if __name__ == '__main__':
    main()
