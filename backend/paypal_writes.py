import json
import os
import re
import sys
from typing import Any

import requests


def safe_result(response: requests.Response, token: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except requests.JSONDecodeError:
        return {'body_omitted': 'Non-JSON response.'}
    if not isinstance(payload, dict):
        return {'body_omitted': 'Unexpected response shape.'}
    result = {key: payload[key] for key in ('name', 'debug_id')
              if isinstance(payload.get(key), str)}
    if isinstance(payload.get('links'), list):
        result['links'] = [
            {key: link[key] for key in ('rel', 'href', 'method')
             if isinstance(link.get(key), str)}
            for link in payload['links'] if isinstance(link, dict)
        ]
    text = json.dumps(result)
    for secret in (token, os.getenv('PAYPAL_CLIENT_SECRET'),
                   os.getenv('PAYPAL_CLIENT_ID'), os.getenv('DEV_MERCHANT_TOKEN')):
        if secret:
            text = text.replace(secret, '[redacted]')
    return json.loads(text)


def send_message(
    base_url: str, token: str, dispute_id: str, message: str,
) -> tuple[str, dict[str, Any]]:
    if base_url not in {
        'https://api-m.sandbox.paypal.com', 'https://api.sandbox.paypal.com',
    } or not re.fullmatch(r'[A-Z0-9-]{1,255}', dispute_id):
        raise ValueError('Only a validated PayPal Sandbox dispute is permitted.')
    # PayPal does not document PayPal-Request-Id for send-message. Never retry.
    try:
        response = requests.post(
            f'{base_url}/v1/customer/disputes/{dispute_id}/send-message',
            headers={'Authorization': f'Bearer {token}'},
            json={'message': message}, timeout=20, allow_redirects=False,
        )
        body = safe_result(response, token)
        result = {'http_status': response.status_code, 'body': body}
        response.raise_for_status()
    except requests.HTTPError:
        print(f'PayPal failure HTTP {response.status_code}: {json.dumps(body)[:1000]}',
              file=sys.stderr)
        status = ('FAILED' if 400 <= response.status_code < 500
                  and response.status_code not in (408, 429)
                  else 'REQUIRES_RECONCILIATION')
        return status, result
    except requests.RequestException:
        result = {'http_status': None, 'body': {'error': 'Transport failure.'}}
        print(f'PayPal failure HTTP not available: {json.dumps(result["body"])}',
              file=sys.stderr)
        return 'REQUIRES_RECONCILIATION', result
    links = body.get('links') or []
    expected_path = f'/v1/customer/disputes/{dispute_id}'
    acknowledged = any(
        link.get('rel') in ('self', 'detail') and link.get('method') == 'GET'
        and link.get('href') in {
            f'https://api-m.sandbox.paypal.com{expected_path}',
            f'https://api.sandbox.paypal.com{expected_path}',
        } for link in links
    )
    if response.status_code == 200 and acknowledged:
        return 'SUCCEEDED', result
    print(f'PayPal ambiguous HTTP {response.status_code}: {json.dumps(body)[:1000]}',
          file=sys.stderr)
    return 'REQUIRES_RECONCILIATION', result
