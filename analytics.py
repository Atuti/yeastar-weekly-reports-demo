"""Normalize and analyze Yeastar-like CDR records without exposing live data."""
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean

MISSED = {"NO ANSWER", "NOANSWER", "BUSY", "FAILED"}


def clean(value):
    return "" if value is None else str(value).strip()


def digits(value):
    return "".join(ch for ch in clean(value) if ch.isdigit())


def parse_time(value, timezone):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone) if value.tzinfo is None else value.astimezone(timezone)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(clean(value), fmt).replace(tzinfo=timezone)
        except ValueError:
            continue
    return None


def status_of(row):
    status = clean(row.get("last_status") or row.get("disposition") or row.get("reason")).upper()
    aliases = {"ANSWER": "ANSWERED", "NOANSWER": "NO ANSWER", "ABANDON": "ABANDONED"}
    return aliases.get(status, status or "UNKNOWN")


def team_for_call(row, department_map):
    queue_names = set()
    for item in row.get("queues") or []:
        if isinstance(item, dict):
            queue_names.update(clean(item.get(k)).casefold() for k in ("name", "number"))
        else:
            queue_names.add(clean(item).casefold())
    ring_names = set()
    for item in row.get("ring_groups") or []:
        if isinstance(item, dict):
            ring_names.update(clean(item.get(k)).casefold() for k in ("name", "number"))
        else:
            ring_names.add(clean(item).casefold())
    participants = {clean(row.get(k)) for k in (
        "call_from_number", "call_to_number", "second_participant_number", "last_participant_number"
    )}
    for team, config in department_map.items():
        extensions = {str(x) for x in config.get("extensions", [])}
        queues = {str(x).casefold() for x in config.get("queues", [])}
        rings = {str(x).casefold() for x in config.get("ring_groups", [])}
        if extensions.intersection(participants) or queues.intersection(queue_names) or rings.intersection(ring_names):
            return team
    return "Unmapped"


def agent_for_call(row, department_map):
    extensions = {str(ext) for config in department_map.values() for ext in config.get("extensions", [])}
    for key in ("last_participant_number", "second_participant_number", "call_to_number", "call_from_number"):
        value = clean(row.get(key))
        if value in extensions:
            return value
    return "Unknown"


def analyze(records, start, end, department_map, callback_hours=4):
    unique = {}
    for raw in records:
        dt = parse_time(raw.get("time"), start.tzinfo)
        if not dt or not start <= dt <= end:
            continue
        row = dict(raw)
        row["_dt"] = dt
        row["_status"] = status_of(row)
        row["_team"] = team_for_call(row, department_map)
        row["_agent"] = agent_for_call(row, department_map)
        key = clean(row.get("uid") or row.get("id")) or f"{dt.isoformat()}|{row.get('call_from_number')}|{row.get('call_to_number')}"
        if key not in unique or len(row) > len(unique[key]):
            unique[key] = row
    calls = sorted(unique.values(), key=lambda r: r["_dt"])

    inbound = [r for r in calls if clean(r.get("call_type")).lower() == "inbound"]
    outbound = [r for r in calls if clean(r.get("call_type")).lower() == "outbound"]
    answered = [r for r in inbound if r["_status"] == "ANSWERED"]
    missed = [r for r in inbound if r["_status"] in MISSED]
    abandoned = [r for r in inbound if r["_status"] == "ABANDONED"]
    voicemail = [r for r in inbound if r["_status"] == "VOICEMAIL"]

    by_team = defaultdict(list)
    by_agent = defaultdict(list)
    for row in calls:
        by_team[row["_team"]].append(row)
        if row["_team"] != "Unmapped":
            by_agent[(row["_team"], row["_agent"])].append(row)

    caller_counts = Counter(digits(r.get("call_from_number")) for r in inbound if digits(r.get("call_from_number")))
    repeats = {caller: count for caller, count in caller_counts.items() if count > 1}
    unanswered = missed + voicemail
    by_day = Counter(r["_dt"].strftime("%A") for r in unanswered)
    by_hour = Counter(r["_dt"].strftime("%A %H:00") for r in unanswered)

    # Same-caller callback matching is intentionally heuristic, not an SLA compliance verdict.
    connected_outbound = [r for r in outbound if r["_status"] == "ANSWERED"]
    callbacks = []
    for missed_call in unanswered:
        caller = digits(missed_call.get("call_from_number"))
        match = None
        if caller:
            candidates = []
            for outgoing in connected_outbound:
                called = digits(outgoing.get("call_to_number"))
                delta = (outgoing["_dt"] - missed_call["_dt"]).total_seconds()
                if called and (called.endswith(caller[-7:]) or caller.endswith(called[-7:])) and 0 <= delta <= callback_hours * 3600:
                    candidates.append(delta)
            match = min(candidates) if candidates else None
        callbacks.append({"call": missed_call, "callback_seconds": match})

    return {
        "calls": calls, "inbound": inbound, "outbound": outbound,
        "answered": answered, "missed": missed, "abandoned": abandoned,
        "voicemail": voicemail, "by_team": dict(by_team), "by_agent": dict(by_agent),
        "repeats": repeats, "by_day": by_day, "by_hour": by_hour,
        "callbacks": callbacks,
    }
