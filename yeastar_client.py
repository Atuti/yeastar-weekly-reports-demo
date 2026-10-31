"""Minimal, configurable Yeastar P-Series CDR API adapter.

No PBX hostname or credentials are embedded in this project. Supply them via
local environment variables or an untracked .env file.
"""
import os
from datetime import datetime

import requests


class YeastarClient:
    def __init__(self, base_url, client_id, client_secret, auth_version='v1.0',
                 cdr_version='v2.0', time_format='%m/%d/%Y %H:%M:%S',
                 verify_tls=True, page_size=1000):
        self.base_url = base_url.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_version = auth_version
        self.cdr_version = cdr_version
        self.time_format = time_format
        self.verify_tls = verify_tls
        self.page_size = min(max(int(page_size), 1), 10000)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'yeastar-weekly-reports-demo', 'Content-Type': 'application/json'})
        self.token = None

    @classmethod
    def from_environment(cls, timezone=None):
        required = ('YEASTAR_BASE_URL', 'YEASTAR_CLIENT_ID', 'YEASTAR_CLIENT_SECRET')
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise RuntimeError('Missing local API settings: ' + ', '.join(missing))
        return cls(
            os.environ['YEASTAR_BASE_URL'], os.environ['YEASTAR_CLIENT_ID'], os.environ['YEASTAR_CLIENT_SECRET'],
            auth_version=os.getenv('YEASTAR_AUTH_API_VERSION', 'v1.0'),
            cdr_version=os.getenv('YEASTAR_CDR_API_VERSION', 'v2.0'),
            time_format=os.getenv('YEASTAR_TIME_FORMAT', '%m/%d/%Y %H:%M:%S'),
            verify_tls=os.getenv('YEASTAR_VERIFY_TLS', 'true').lower() in ('1', 'true', 'yes'),
            page_size=int(os.getenv('YEASTAR_PAGE_SIZE', '1000')),
        )

    def _request(self, method, endpoint, *, version, params=None, body=None, auth=True):
        if auth and not self.token:
            self.login()
        query = dict(params or {})
        if auth:
            query['access_token'] = self.token
        response = self.session.request(
            method, f'{self.base_url}/openapi/{version}/{endpoint.lstrip("/")}',
            params=query, json=body, timeout=45, verify=self.verify_tls,
        )
        response.raise_for_status()
        payload = response.json()
        code = payload.get('errcode', 0)
        if code not in (0, '0', None):
            message = str(payload.get('errmsg', ''))
            if auth and 'token' in message.lower():
                self.token = None
                self.login()
                query['access_token'] = self.token
                response = self.session.request(
                    method, f'{self.base_url}/openapi/{version}/{endpoint.lstrip("/")}',
                    params=query, json=body, timeout=45, verify=self.verify_tls,
                )
                response.raise_for_status()
                payload = response.json()
                code = payload.get('errcode', 0)
            if code not in (0, '0', None):
                raise RuntimeError(f'Yeastar API error {code}: {payload.get("errmsg", "Unknown error")}')
        return payload

    def login(self):
        payload = self._request(
            'POST', 'get_token', version=self.auth_version,
            body={'username': self.client_id, 'password': self.client_secret}, auth=False,
        )
        self.token = payload.get('access_token')
        if not self.token:
            raise RuntimeError('Authentication response did not contain access_token')

    def get_cdrs(self, start: datetime, end: datetime):
        records, page, total = [], 1, None
        while True:
            payload = self._request(
                'GET', 'cdr/search', version=self.cdr_version,
                params={
                    'page': page, 'page_size': self.page_size,
                    'order_by': 'asc', 'sort_by': 'time',
                    'time_begin': start.strftime(self.time_format),
                    'time_end': end.strftime(self.time_format),
                },
            )
            batch = payload.get('data') or []
            records.extend(batch)
            total = int(payload.get('total_number', len(records)) or 0)
            if not batch or len(records) >= total or len(batch) < self.page_size:
                break
            page += 1
        # Validate API filtering locally; fail closed if the returned records do not match.
        from analytics import parse_time
        in_window = []
        for row in records:
            parsed = parse_time(row.get('time'), start.tzinfo)
            if parsed and start <= parsed <= end:
                in_window.append(row)
        if records and not in_window:
            raise RuntimeError('PBX returned CDRs, but none matched the requested window. Check API version and YEASTAR_TIME_FORMAT.')
        return in_window
