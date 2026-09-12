"""
main.py — EPOCH gateway (packaged form, Session 17.1).

Routes:
    GET  /health              liveness probe — reports tenant_isolation state
    GET  /cluster/health      human-readable backend status (litellm)
    POST /v1/agent/invoke     frozen, carries Deprecation/Sunset/Link headers
    POST /v2/agent/invoke     live, no deprecation headers

Both invoke versions share _handle_invoke: verify JWT -> parse body -> bind
tenant (reject cross-tenant hospital_id) -> redact PII -> enforce admin-only
tools -> call the LLM backend -> redact the answer -> return
{status, hospital_id, role, answer}.

Everything except the tenant-binding step and the /health body is carried
forward unchanged from Week 16.2 (phase5/session5/services/fastapi/app/main.py).
"""
import json
import os
import re

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .epoch_auth import verify_jwt

app = FastAPI(title="epoch-gateway", version="17.1.0")

LITELLM_URL        = os.environ.get("LITELLM_URL", "http://litellm:4000")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-epoch-demo-master-key")

# "active" (default) enforces the cross-tenant check below. Any other value
# disables enforcement but is still reported verbatim by /health, so a
# misconfigured deployment is visible on the probe, not silent.
TENANT_ISOLATION = os.environ.get("EPOCH_TENANT_ISOLATION", "active")

CC_PATTERN  = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Prompts that route to the admin-only generate_client_deliverable tool.
ADMIN_ONLY_KEYWORDS = ("clinical pdf", "deliverable")


def redact_pii(text: str) -> str:
    text = CC_PATTERN.sub("[REDACTED_CC]", text)
    text = SSN_PATTERN.sub("[REDACTED_SSN]", text)
    return text


def redact_json(obj):
    if isinstance(obj, str):
        return redact_pii(obj)
    if isinstance(obj, dict):
        return {k: redact_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_json(v) for v in obj]
    return obj


def requires_admin_tool(prompt: str) -> bool:
    p = prompt.lower()
    return any(kw in p for kw in ADMIN_ONLY_KEYWORDS)


def resolve_tenant(claims: dict, body: dict) -> str:
    """
    The tenant is the caller's hospital_id claim — never a value the client
    sends. When isolation is active, a body that names a *different*
    hospital_id is a cross-tenant attempt and is rejected upstream; here we
    just surface the mismatch.
    """
    claimed = claims["hospital_id"]
    requested = body.get("hospital_id")
    if TENANT_ISOLATION == "active" and requested is not None and requested != claimed:
        raise ValueError(f"cross-tenant request: token={claimed} body={requested}")
    return claimed


@app.get("/health")
async def health():
    """Liveness probe. No backend calls — HEALTHCHECK and depends_on poll this."""
    return {"status": "ok", "tenant_isolation": TENANT_ISOLATION}


@app.get("/cluster/health")
async def cluster_health():
    """Human-readable backend status. Calls the LLM backend only."""
    results = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{LITELLM_URL}/health")
            results["litellm"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
        except Exception as e:
            results["litellm"] = f"error:{str(e)[:50]}"
    overall = "ok" if all(v == "ok" for v in results.values()) else "degraded"
    return {"status": overall, "tenant_isolation": TENANT_ISOLATION, "backends": results}


@app.post("/v1/agent/invoke")
async def agent_invoke_v1(request: Request):
    """v1 — frozen. Returns deprecation headers so clients know to migrate."""
    resp = await _handle_invoke(request)
    resp.headers["Deprecation"] = "true"
    resp.headers["Sunset"]      = "Sat, 31 Dec 2026 23:59:59 GMT"
    resp.headers["Link"]        = '</v2/agent/invoke>; rel="successor-version"'
    return resp


@app.post("/v2/agent/invoke")
async def agent_invoke_v2(request: Request):
    """v2 — live. No deprecation headers."""
    return await _handle_invoke(request)


async def _handle_invoke(request: Request) -> JSONResponse:
    auth = request.headers.get("Authorization", "")
    try:
        claims = verify_jwt(auth)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=401)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "malformed JSON body"}, status_code=400)

    try:
        tenant = resolve_tenant(claims, body)
    except ValueError as e:
        return JSONResponse(
            {"error": f"forbidden: {e}", "hospital_id": claims["hospital_id"]},
            status_code=403,
        )

    prompt = redact_pii(body.get("prompt") or body.get("question", ""))

    if requires_admin_tool(prompt) and claims["role"] != "admin":
        return JSONResponse(
            {"error": "forbidden: admin role required for this tool", "role": claims["role"]},
            status_code=403,
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            llm_resp = await client.post(
                f"{LITELLM_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"},
                json={"model": "epoch-default",
                      "messages": [{"role": "user", "content": prompt}]},
            )
            answer = llm_resp.json()
        except Exception as e:
            return JSONResponse({"error": f"litellm:{e}"}, status_code=502)

    answer = redact_json(answer)

    resp = JSONResponse({
        "status": 200,
        "hospital_id": claims["hospital_id"],
        "role": claims["role"],
        "answer": answer,
    })
    resp.headers["X-Epoch-Tenant"] = tenant
    resp.headers["X-Epoch-Tenant-Isolation"] = TENANT_ISOLATION
    return resp