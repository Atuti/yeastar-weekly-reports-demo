# Yeastar Weekly Call Reports — Public Demo

A portfolio demonstration of a Python reporting pipeline for Yeastar P-Series call-detail records (CDRs). It normalizes call records, attributes calls to configurable teams, calculates operational indicators, and generates HTML and CSV outputs.

> **Demo only:** This repository contains synthetic call records and generic configuration. It is not the production deployment of any organization and is not connected to a live PBX. Never commit real CDR exports, caller details, employee information, API credentials, PBX addresses, or internal extension maps.

## Features

- Weekly reporting window using a configurable IANA timezone (defaults to `Africa/Nairobi`).
- Configurable team attribution using extension, queue, and ring-group identifiers.
- Inbound/outbound classification and call-outcome summaries.
- Agent/extension performance, average routing delay, and handling duration.
- Hour/day patterns for unanswered and voicemail calls.
- Repeat-caller analysis using normalized caller identifiers.
- Heuristic callback matching with an explicit warning that it is not proof of agent compliance.
- HTML report and CSV drill-down output.
- Synthetic fixture data so the project can be run without a PBX account.

## Architecture

```text
Yeastar CDR API or synthetic JSON fixture
                  |
                  v
           CDR input adapter
                  |
                  v
         Normalize and validate
                  |
                  v
       Team / agent attribution
                  |
                  v
          Metrics and analysis
             /          \
            v            v
       HTML report    CSV export
```

The default workflow starts with a local JSON fixture. `yeastar_client.py` provides an optional Yeastar P-Series API adapter; credentials and the PBX base URL belong only in a local `.env` file and must never be committed.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env             # optional for the local fixture
python report.py --input data/sample_cdr.json --output-dir output
```

The command creates:

- `output/weekly_report.html`
- `output/call_incidents.csv`

Open the HTML file in a browser. The fixture contains only fictional names and reserved example phone numbers.

## Configuration

Copy `.env.example` to `.env` for local configuration. `DEPARTMENT_MAP_JSON` is deliberately populated with fictional identifiers. Replace these only in your private deployment environment; do not publish internal mappings.

| Variable | Purpose |
|---|---|
| `TIMEZONE` | IANA timezone used for report boundaries |
| `DEPARTMENT_MAP_JSON` | Maps fictional extension, queue, and ring-group IDs to teams |
| `SLA_ANSWER_SECONDS` | Optional answer-delay reference threshold |
| `SLA_CALLBACK_HOURS` | Time window used by the callback heuristic |

The default mode does not call a PBX API or send email. An optional `--live` mode is included for users who configure their own Yeastar API credentials locally:

```bash
cp .env.example .env
# Edit .env locally with your own PBX URL, API client credentials, and private team mappings.
python report.py --live --output-dir output
```

Live mode retrieves CDR records and generates local HTML/CSV outputs; it does not email reports. Keep `.env` untracked and never use your employer's credentials or mappings in a public demo.

## Data contract

Each input record is a CDR-like object. The analysis uses fields such as:

- `time`, `call_type`, `last_status`
- `call_from_number`, `call_to_number`
- `second_participant_number`, `last_participant_number`
- `routing_duration`, `handling_duration`
- `queues`, `ring_groups`, `uid`

Unknown or missing fields are handled conservatively. The sample schema is illustrative; confirm the exact fields and semantics against the API version and PBX firmware used in a real deployment.

## Metric definitions and limitations

- **Missed/failed inbound:** no-answer, busy, and failed outcomes. Abandoned and voicemail are shown separately.
- **Answer delay:** uses `routing_duration` for answered inbound calls when present.
- **Handling duration:** uses `handling_duration` for answered calls when present.
- **Callback match:** heuristic match of a subsequent answered outbound call to the same normalized caller identifier inside the configured window. It can produce false positives and false negatives.
- **Repeat caller:** a normalized external caller identifier with more than one inbound record in the report period.
- **Queue/IVR/transfer visibility:** depends on the CDR fields returned by the specific PBX/API version. A CDR report is not a complete queue-offer or IVR funnel audit.

Validate all operational totals against the PBX interface and source CDR export before using them for management decisions. Agree formal service targets with the relevant business owners; sample thresholds are not policies.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Security and privacy

- `.env`, generated `output/`, and local CDR exports are ignored by Git.
- Use synthetic data in public examples and screenshots.
- Keep credentials in a secret manager or protected environment variables in production.
- Restrict API access and report recipients using least privilege.
- Minimize retention and access to call metadata, which may contain personal data.
- Review commit history before publishing; removing a file from the latest commit does not erase it from earlier Git history.

## Portfolio context

This is a sanitized technical demonstration based on common PBX reporting patterns. It illustrates API-oriented data ingestion, timezone-aware reporting, data normalization, configurable attribution, analytics, and report generation. It intentionally omits production endpoints, organization names, real mappings, customer data, and private operational details.
