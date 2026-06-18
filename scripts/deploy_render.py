"""Create or update MoneyLine on Render via API (uses ~/.render/cli.yaml token)."""
from __future__ import annotations

import json
import pathlib
import re
import urllib.error
import urllib.request

OWNER_ID = "tea-d8nruuojs32c73e1ebug"
REPO = "https://github.com/andersonmise488-wq/MoneyLine"
BRANCH = "main"
SERVICE_NAME = "moneyline"


def _api_key() -> str:
    cfg = pathlib.Path.home() / ".render" / "cli.yaml"
    text = cfg.read_text(encoding="utf-8")
    m = re.search(r"^\s*key:\s*(.+)$", text, re.M)
    if not m:
        raise SystemExit("No Render API key in ~/.render/cli.yaml — run: render login")
    return m.group(1).strip()


def _request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"https://api.render.com/v1{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"Render API {method} {path} failed ({exc.code}): {detail}") from exc


def _load_dotenv() -> dict[str, str]:
    env_path = pathlib.Path(__file__).resolve().parents[1] / ".env"
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _static_env() -> list[dict]:
    return [
        {"key": "PYTHONPATH", "value": "/app/src"},
        {"key": "WEB_SCAN_MIN_MARGIN_PCT", "value": "0.0"},
        {"key": "WEB_SCAN_MAX_EVENTS", "value": "0"},
        {"key": "WEB_SCAN_MAX_MARKETS", "value": "0"},
        {"key": "MATCH_FIRST_MARKETS", "value": "true"},
        {"key": "MARKET_FETCH_CONCURRENCY", "value": "50"},
        {"key": "RAW_CACHE_TTL_SECONDS", "value": "0"},
        {"key": "ODDS_STALENESS_SECONDS", "value": "0"},
        {"key": "WEB_SCAN_INTERVAL_MINUTES", "value": "20"},
        {"key": "WEB_SCAN_POLL_SECONDS", "value": "60"},
        {"key": "ALERT_DEDUP_MINUTES", "value": "20"},
        {"key": "ALERT_MIN_MARGIN_PCT", "value": "5.0"},
        {"key": "SCAN_AUTO_ALERTS_ENABLED", "value": "true"},
    ]


def _secret_env(local: dict[str, str]) -> list[dict]:
    keys = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_ADMIN_CHAT_IDS",
        "WEB_ADMIN_TOKEN",
        "WEB_ALLOWED_ORIGINS",
        "STANBIC_CLIENT_ID",
        "STANBIC_CLIENT_SECRET",
        "STANBIC_BILL_ACCOUNT_REF",
        "STANBIC_CALLBACK_URL",
        "STANBIC_ENV",
        "STANBIC_PAYMENT_MODE",
        "STANBIC_TOKEN_URL",
        "STANBIC_STK_URL",
        "SUBSCRIPTION_DEMO_MODE",
    ]
    out: list[dict] = []
    for key in keys:
        val = local.get(key, "")
        if val and "your-domain" not in val:
            out.append({"key": key, "value": val})
    return out


def _find_service() -> dict | None:
    data = _request("GET", "/services?limit=50")
    rows = data if isinstance(data, list) else data.get("value", []) or []
    for row in rows:
        svc = row.get("service") or row
        if svc.get("name") == SERVICE_NAME:
            return svc
    return None


def _create_service(env_vars: list[dict]) -> dict:
    body = {
        "type": "web_service",
        "name": SERVICE_NAME,
        "ownerId": OWNER_ID,
        "repo": REPO,
        "branch": BRANCH,
        "autoDeploy": "yes",
        "envVars": env_vars,
        "serviceDetails": {
            "runtime": "docker",
            "plan": "free",
            "healthCheckPath": "/health",
            "envSpecificDetails": {"dockerfilePath": "./Dockerfile"},
        },
    }
    return _request("POST", "/services", body)


def _update_env(service_id: str, env_vars: list[dict]) -> None:
    for item in env_vars:
        key = item["key"]
        value = item["value"]
        _request("PUT", f"/services/{service_id}/env-vars/{key}", {"value": value})


def _trigger_deploy(service_id: str) -> dict:
    return _request("POST", f"/services/{service_id}/deploys", {"clearCache": "clear"})


def _service_url(svc: dict) -> str:
    slug = svc.get("slug") or SERVICE_NAME
    return f"https://{slug}.onrender.com"


def main() -> None:
    local = _load_dotenv()
    existing = _find_service()

    if existing:
        sid = existing["id"]
        svc = existing
        print(f"Service exists: {sid}")
    else:
        print("Creating Render web service...")
        boot_env = _static_env() + _secret_env(local)
        result = _create_service(boot_env)
        svc = result.get("service") or result
        sid = svc["id"]
        print(f"Created service: {sid}")

    base = _service_url(svc)
    local["WEB_ALLOWED_ORIGINS"] = base
    local["STANBIC_CALLBACK_URL"] = f"{base}/stanbic/callback"
    env_vars = _static_env() + _secret_env(local)
    _update_env(sid, env_vars)

    deploy = _trigger_deploy(sid)
    deploy_id = deploy.get("deploy", deploy).get("id") if isinstance(deploy.get("deploy"), dict) else deploy.get("id")
    print(f"Deploy triggered: {deploy_id}")
    print(f"URL: {base}")
    print(f"Health: {base}/health")
    print(f"Admin: {base}/admin")


if __name__ == "__main__":
    main()
