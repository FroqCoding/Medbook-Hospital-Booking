"""Simple smoke test for deployed Medbook service.

Usage (PowerShell example):
  $env:BASE_URL="https://your-service.onrender.com"
  python smoke_test.py

Or pass as arg:
  python smoke_test.py --base https://your-service.onrender.com

The script will:
 1. /health
 2. /doctors (list first doc)
 3. /doctors/<id>
 4. (Optional) login with provided creds via env SMOKE_EMAIL/SMOKE_PASSWORD
 5. (Optional) create + cancel a test appointment if login succeeds.

Set SMOKE_SKIP_APPOINTMENT=1 to skip booking.
"""
from __future__ import annotations
import os, sys, json, datetime, random, time
import argparse
import requests

TIMEOUT = 15

def log(step: str, status: str, detail: str = ""):
    print(f"[SMOKE] {step:<25} {status:<8} {detail}")

def get_base(arg_base: str | None) -> str:
    base = arg_base or os.getenv("BASE_URL")
    if not base:
        print("ERROR: Provide --base URL or set BASE_URL env var.")
        sys.exit(2)
    return base.rstrip('/')

def req(method: str, url: str, **kw):
    r = requests.request(method, url, timeout=TIMEOUT, **kw)
    return r

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', help='Base URL like https://service.onrender.com')
    args = parser.parse_args()

    base = get_base(args.base)
    log('Base URL', 'INFO', base)

    # 1. Health
    try:
        r = req('GET', f'{base}/health')
        if r.status_code == 200 and r.json().get('status') == 'ok':
            log('Health check', 'PASS')
        else:
            log('Health check', 'FAIL', f'status={r.status_code} body={r.text[:200]}')
    except Exception as e:
        log('Health check', 'ERROR', str(e))
        return 1

    # 2. Doctors list
    try:
        r = req('GET', f'{base}/doctors')
        if r.status_code == 200:
            doctors = r.json()
            count = len(doctors)
            if count == 0:
                log('Doctors list', 'WARN', 'Empty list')
            else:
                log('Doctors list', 'PASS', f'{count} doctors')
            # pick first
            first_id = doctors[0]['doctorid'] if doctors else None
        else:
            log('Doctors list', 'FAIL', f'status={r.status_code}')
            first_id = None
    except Exception as e:
        log('Doctors list', 'ERROR', str(e))
        first_id = None

    # 3. Doctor detail
    if first_id is not None:
        try:
            r = req('GET', f'{base}/doctors/{first_id}')
            if r.status_code == 200 and r.json().get('doctorid') == first_id:
                log('Doctor detail', 'PASS', f'id={first_id}')
            else:
                log('Doctor detail', 'FAIL', f'status={r.status_code}')
        except Exception as e:
            log('Doctor detail', 'ERROR', str(e))

    email = os.getenv('SMOKE_EMAIL')
    pwd = os.getenv('SMOKE_PASSWORD')
    token = None
    userid = None

    if email and pwd:
        try:
            r = req('POST', f'{base}/users/login', json={'email': email, 'password': pwd})
            if r.status_code == 200:
                data = r.json()
                token = data.get('access_token')
                userid = data.get('userid')
                if token and userid:
                    log('Login', 'PASS', f'user={userid}')
                else:
                    log('Login', 'FAIL', 'missing token or userid')
            else:
                log('Login', 'FAIL', f'status={r.status_code} body={r.text[:120]}')
        except Exception as e:
            log('Login', 'ERROR', str(e))

    skip_appt = os.getenv('SMOKE_SKIP_APPOINTMENT') == '1'
    if skip_appt:
        log('Appointment step', 'SKIP', 'SMOKE_SKIP_APPOINTMENT=1 set')
        return 0

    if token and userid and first_id is not None:
        # Build a date likely on a weekday (next 3-7 days)
        for offset in range(3, 10):
            target = datetime.date.today() + datetime.timedelta(days=offset)
            # naive: just try; server will reject if not available
            appt_date = target.strftime('%Y-%m-%d')
            appt_time = '09:00'
            try:
                r = req('POST', f'{base}/appointments', json={
                    'userid': userid,
                    'doctorid': first_id,
                    'date': appt_date,
                    'time': appt_time,
                    'reason': f'Smoke test {int(time.time())}'
                })
                if r.status_code == 201:
                    appt = r.json()['appointment']
                    appt_id = appt['appointmentid']
                    log('Create appointment', 'PASS', f'id={appt_id} {appt_date} {appt_time}')
                    # Cancel it
                    c = req('PUT', f'{base}/appointments/{appt_id}/cancel')
                    if c.status_code == 200:
                        log('Cancel appointment', 'PASS', f'id={appt_id}')
                    else:
                        log('Cancel appointment', 'FAIL', f'status={c.status_code}')
                    break
                else:
                    # try next offset
                    continue
            except Exception as e:
                log('Create appointment', 'ERROR', str(e))
                break
    else:
        log('Appointment step', 'SKIP', 'Missing token/userid or no doctors')

    return 0

if __name__ == '__main__':
    sys.exit(main())
