"""Minimal stdlib SigV4 signer + Lambda Invoke.

The AgentCore Runtime managed Python runtime doesn't bundle boto3, and
vendoring it would bloat the zip for one API call. This signs a Lambda
Invoke request with credentials from the container credential endpoint
(AWS_CONTAINER_CREDENTIALS_FULL_URI) or env vars.
"""

import datetime
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

_creds_cache = {"expiry": 0.0}


def _credentials():
    """Container credential endpoint first (AgentCore Runtime), env vars as fallback."""
    if time.time() < _creds_cache["expiry"] - 120:
        return _creds_cache["creds"]
    uri = os.environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI")
    if uri:
        headers = {}
        token = os.environ.get("AWS_CONTAINER_AUTHORIZATION_TOKEN")
        token_file = os.environ.get("AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE")
        if token_file and os.path.exists(token_file):
            token = open(token_file).read().strip()
        if token:
            headers["Authorization"] = token
        req = urllib.request.Request(uri, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read())
        creds = (d["AccessKeyId"], d["SecretAccessKey"], d.get("Token"))
        _creds_cache.update(creds=creds, expiry=time.time() + 900)
        return creds
    return (
        os.environ["AWS_ACCESS_KEY_ID"],
        os.environ["AWS_SECRET_ACCESS_KEY"],
        os.environ.get("AWS_SESSION_TOKEN"),
    )


def _sign(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sigv4_request(method, url, body, service, region, extra_headers=None):
    """Build a signed urllib Request for an AWS API call."""
    access_key, secret_key, session_token = _credentials()
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body or b"").hexdigest()

    headers = {"host": host, "x-amz-date": amz_date, "x-amz-content-sha256": payload_hash}
    if session_token:
        headers["x-amz-security-token"] = session_token
    if extra_headers:
        headers.update({k.lower(): v for k, v in extra_headers.items()})

    signed_names = sorted(headers)
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in signed_names)
    signed_headers = ";".join(signed_names)
    canonical_request = "\n".join([
        method,
        urllib.parse.quote(parsed.path or "/"),
        parsed.query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])
    k = _sign(_sign(_sign(_sign(("AWS4" + secret_key).encode(), date_stamp), region), service), "aws4_request")
    signature = hmac.new(k, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers.pop("host")
    return urllib.request.Request(url, data=body, method=method, headers=headers)


def invoke_lambda(function_name, payload, region=None):
    """lambda:Invoke (RequestResponse) returning the parsed JSON result."""
    region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    url = f"https://lambda.{region}.amazonaws.com/2015-03-31/functions/{function_name}/invocations"
    body = json.dumps(payload).encode()
    req = sigv4_request("POST", url, body, "lambda", region,
                        extra_headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    if isinstance(result, dict) and result.get("errorMessage"):
        raise RuntimeError(f"{function_name} failed: {result['errorMessage']}")
    return result
