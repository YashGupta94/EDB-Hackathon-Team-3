#def main():
#    print("Hello from adkagents!")

import json
import os
import importlib
uvicorn = None
try:
    uvicorn = importlib.import_module("uvicorn")
except Exception:
    uvicorn = None
from functools import lru_cache

# Dynamic import of FastAPI symbols to avoid static import errors in
# environments where FastAPI is not installed.
Form = None
HTTPException = Exception
Request = None
HTMLResponse = None
RedirectResponse = None
FastAPI = None
Cookie = None
Body = None
try:
    fastapi_mod = importlib.import_module("fastapi")
    fastapi_responses = importlib.import_module("fastapi.responses")
    Form = getattr(fastapi_mod, "Form")
    HTTPException = getattr(fastapi_mod, "HTTPException")
    Request = getattr(fastapi_mod, "Request")
    # optional dependencies
    try:
      Cookie = getattr(fastapi_mod, "Cookie")
    except Exception:
      Cookie = None
    try:
      Body = getattr(fastapi_mod, "Body")
    except Exception:
      Body = None
    FastAPI = getattr(fastapi_mod, "FastAPI")
    HTMLResponse = getattr(fastapi_responses, "HTMLResponse")
    RedirectResponse = getattr(fastapi_responses, "RedirectResponse")
except Exception:
    # Provide lightweight fallbacks so the module can be imported
    class _FallbackRequest:
        pass

    def _fallback_Form(*a, **kw):
        return None

    class _FallbackHTMLResponse:
        def __init__(self, content="", status_code=200):
            self.content = content
            self.status_code = status_code

    class _FallbackRedirectResponse(_FallbackHTMLResponse):
        pass

    Request = _FallbackRequest
    Form = _fallback_Form
    Cookie = lambda *a, **kw: None
    Body = lambda *a, **kw: None
    HTTPException = Exception
    HTMLResponse = _FallbackHTMLResponse
    RedirectResponse = _FallbackRedirectResponse
    FastAPI = None

get_fast_api_app = None
try:
    ga = importlib.import_module("google.adk.cli.fast_api")
    get_fast_api_app = getattr(ga, "get_fast_api_app")
except Exception:
    # Fallback that returns a bare FastAPI app if available, else None
    def get_fast_api_app(agents_dir=None, allow_origins=None, web=False, trace_to_cloud=False):
        if FastAPI:
            return FastAPI()
        return None

from bank_agent.observability import store, CostGranularity
import traceback
import sys

# 1. Grab the dynamic port assigned by Google Cloud Run
port = int(os.environ.get("PORT", 8080))

# 2. Wrap your ADK agent in a production-ready FastAPI web server
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
app = get_fast_api_app(
    agents_dir=AGENT_DIR,
    allow_origins=["*"],
    web=True,
    trace_to_cloud=os.environ.get("TRACE_TO_CLOUD", "false").lower() == "true",
)

# Provide helpful error output for request validation errors (422) so debugging
# is easier when the frontend receives "422 Unprocessable Content".
try:
  from fastapi.exceptions import RequestValidationError
  from fastapi.responses import JSONResponse

  if app is not None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
      # Return JSON with the validation errors and the raw body (if any)
      body = None
      try:
        body = await request.body()
        body = body.decode('utf-8') if isinstance(body, (bytes, bytearray)) else str(body)
      except Exception:
        body = None
      return JSONResponse(status_code=422, content={
        "detail": getattr(exc, 'errors', lambda: str(exc))(),
        "body": body,
      })
except Exception:
  # FastAPI may not be installed in this environment; skip handler.
  pass

# Universal middleware to log exceptions and dump validation error details
if app is not None:
  try:
    @app.middleware("http")
    async def _log_exceptions(request, call_next):
      try:
        return await call_next(request)
      except Exception as exc:
        tb = traceback.format_exc()
        # Try to extract Pydantic/FastAPI validation details if available
        details = None
        try:
          if hasattr(exc, "errors"):
            details = exc.errors()
        except Exception:
          details = str(exc)
        # Log to stdout/stderr for developer visibility
        print("--- Exception during request ---", file=sys.stderr)
        print("URL:", getattr(request, 'url', None), file=sys.stderr)
        print("Exception:", repr(exc), file=sys.stderr)
        print("Details:", details, file=sys.stderr)
        print(tb, file=sys.stderr)
        # Return a JSON response with details to help debugging
        try:
          from fastapi.responses import JSONResponse
          status_code = getattr(exc, 'status_code', 500)
          return JSONResponse(status_code=status_code, content={
            'error': str(exc),
            'details': details,
            'trace': tb,
          })
        except Exception:
          # Fallback
          return HTMLResponse(content="Internal server error", status_code=500)
  except Exception:
    pass


def _get_agent_names() -> list[str]:
    names = []
    for entry in os.listdir(AGENT_DIR):
        entry_path = os.path.join(AGENT_DIR, entry)
        if os.path.isdir(entry_path) and os.path.exists(os.path.join(entry_path, "agent.py")):
            names.append(entry)
    return sorted(names)


def _friendly_agent_name(agent_name: str) -> str:
    return " ".join(part.capitalize() for part in agent_name.replace("_", " ").split())


@lru_cache(maxsize=None)
def _load_json_lines(filename: str) -> list[dict]:
    file_path = os.path.join(AGENT_DIR, "bq_seed", filename)
    if not os.path.exists(file_path):
        return []
    with open(file_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _get_customer_records(customer_id: str) -> tuple[dict | None, list[dict], list[dict]]:
    customer_id = customer_id.strip().upper()
    customers = _load_json_lines("customers.json")
    customer = next((c for c in customers if c.get("customer_id") == customer_id), None)
    if not customer:
        return None, [], []
    accounts = [a for a in _load_json_lines("accounts.json") if a.get("customer_id") == customer_id]
    account_ids = {a.get("account_id") for a in accounts}
    transactions = [t for t in _load_json_lines("transactions.json") if t.get("account_id") in account_ids]
    return customer, accounts, transactions


def _customer_exists(customer_id: str) -> bool:
    customer, _, _ = _get_customer_records(customer_id)
    return customer is not None


def _normalize_customer_id(customer_id: str | None) -> str | None:
    if not customer_id:
        return None
    return customer_id.strip().upper()


def _render_login_page(error: str | None = None) -> str:
    error_html = f"<p class=\"error\">{error}</p>" if error else ""
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <title>Customer Login</title>
  <style>
    body {{ font-family: Inter, system-ui, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; min-height: 100vh; display: grid; place-items: center; }}
    .card {{ width: min(420px, calc(100% - 32px)); padding: 32px; background: rgba(15,23,42,.92); border: 1px solid rgba(148,163,184,.16); border-radius: 24px; box-shadow: 0 24px 80px rgba(15,23,42,.24); }}
    h1 {{ margin: 0 0 12px; font-size: 1.9rem; color: #f8fafc; }}
    p.subtitle {{ margin: 0 0 24px; color: #94a3b8; }}
    label {{ display: block; margin-bottom: 12px; font-size: .95rem; color: #cbd5e1; }}
    input {{ width: 100%; padding: 12px 14px; margin-top: 6px; border: 1px solid #334155; border-radius: 12px; background: #020617; color: #f8fafc; }}
    button {{ width: 100%; margin-top: 18px; padding: 14px 16px; border: none; border-radius: 12px; background: #2563eb; color: white; font-weight: 700; cursor: pointer; transition: transform .15s ease, background .15s ease; }}
    button:hover {{ background: #1d4ed8; transform: translateY(-1px); }}
    .error {{ margin-top: 18px; color: #fecaca; font-size: .95rem; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>Customer Login</h1>
    <p class=\"subtitle\">Enter your customer ID from the dataset, for example C001.</p>
    <form method=\"post\" action=\"/login\">
      <label>Customer ID<input name=\"customer_id\" placeholder=\"e.g. C001\" required></label>
      <button type=\"submit\">Continue</button>
    </form>
    {error_html}
  </div>
</body>
</html>"""


def _render_dashboard_page(agent_names: list[str], customer: dict, total_balance: float, total_expenses: float) -> str:
    accounts_html = "\n".join(
        f'<li><strong>{acct.get("product_type")}</strong>: £{acct.get("balance", 0):,.2f}</li>'
        for acct in customer.get("accounts", [])
    )
    return f"""<!DOCTYPE html>
  <html lang=\"en\">
  <head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>Customer Dashboard</title>
    <style>
      body {{ margin: 0; font-family: Inter, system-ui, sans-serif; background: radial-gradient(circle at top, rgba(59,130,246,.18), transparent 28%), #020617; color: #e2e8f0; min-height: 100vh; }}
      .page {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
      .header {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }}
      .header h1 {{ margin: 0; font-size: 1.4rem; }}
      .summary-row {{ display: flex; gap: 12px; align-items: center; margin-bottom: 18px; flex-wrap: wrap; }}
      .summary-card {{ flex: 1 1 auto; padding: 16px 18px; border-radius: 14px; background: rgba(15,23,42,.92); border: 1px solid rgba(148,163,184,.12); }}
      .summary-card h3 {{ margin: 0 0 6px; font-size: .95rem; color: #cbd5e1; }}
      .summary-card p {{ margin: 0; font-weight: 700; color: #f8fafc; }}
      .accounts-inline {{ margin: 0; padding: 0; list-style: none; display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; }}
      .chat-area {{ margin-top: 18px; }}
      .chat-card {{ padding: 18px; border-radius: 16px; background: rgba(15,23,42,.94); border: 1px solid rgba(148,163,184,.12); min-height: 520px; display: flex; flex-direction: column; gap: 12px; }}
      .chat-iframe {{ width: 100%; flex: 1 1 0; border: none; border-radius: 12px; min-height: 420px; background: #020617; }}
      .small-link {{ color: #93c5fd; text-decoration: none; }}
      .footer {{ margin-top: 12px; color: #94a3b8; display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap }}
      @media (max-width: 780px) {{ .summary-row {{ flex-direction: column; align-items: stretch; }} }}
    </style>
  </head>
  <body>
    <div class=\"page\">
      <div class=\"header\">
        <div>
          <h1>Customer Dashboard</h1>
          <p style=\"margin:0;color:#94a3b8;\">Welcome back, {customer.get("name")} ({customer.get("customer_id")}).</p>
        </div>
        <div><a class=\"small-link\" href=\"/logout\">Logout</a></div>
      </div>

      <div class=\"summary-row\">
        <div class=\"summary-card\">
          <h3>Current balance</h3>
          <p>£{total_balance:,.2f}</p>
        </div>
        <div class=\"summary-card\">
          <h3>Total expenses</h3>
          <p>£{total_expenses:,.2f}</p>
        </div>
        <div class=\"summary-card\">
          <h3>Customer</h3>
          <p>{customer.get("customer_id")} • {customer.get("postcode")}, age {customer.get("age")}</p>
          <ul class=\"accounts-inline\">{accounts_html}</ul>
        </div>
      </div>

      <div class=\"chat-area\">
        <div class=\"chat-card\">
          <h3 style=\"margin:0;color:#cbd5e1;\">Bank agent chat</h3>
          <p style=\"margin:0;color:#94a3b8;\">The chat is connected to the bank agent and receives your customer context.</p>
          <iframe id="bank-devui-iframe" class="chat-iframe" src="/dev-ui/?customer_id={customer.get("customer_id", "")}" title="Bank agent chat"></iframe>
          <script>
            (function(){{
              const iframe = document.getElementById('bank-devui-iframe');
              function parseCookies(){{
                const pairs = document.cookie.split(';').map(s=>s.trim()).filter(Boolean);
                const map = {{}};
                for(const p of pairs){{
                  const i = p.indexOf('=');
                  if(i>-1) map[decodeURIComponent(p.slice(0,i))]=decodeURIComponent(p.slice(i+1));
                }}
                return map;
              }}

              function findSessionCookie(){{
                const cookies = parseCookies();
                const names = Object.keys(cookies);
                // common session cookie name patterns
                const candidates = ['adk_session','adk-session','session','sessionid','sid','adk.sid','devui_session'];
                for(const n of candidates){{ if(cookies[n]) return cookies[n]; }}
                // fallback: return the first cookie that contains 'session' or 'sid' in its name
                for(const n of names){{ if(/session|sid/i.test(n)) return cookies[n]; }}
                return null;
              }}

              async function postSession(sessionId){{
                try{{
                  await fetch('/dev-ui/session', {{
                    method: 'POST',
                    credentials: 'include',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ session_id: sessionId }})
                  }});
                }}catch(e){{ /* ignore network errors */ }}
              }}

              // Try when iframe loads, and retry a few times if session cookie not yet set.
              let attempts = 0;
              function tryAssociate(){{
                attempts++;
                const sid = findSessionCookie();
                if(sid){{ postSession(sid); return; }}
                // try to inspect iframe window for possible globals (same-origin)
                try{{
                  const w = iframe && iframe.contentWindow;
                  if(w){{
                    if(w.__ADK_SESSION_ID) {{ postSession(w.__ADK_SESSION_ID); return; }}
                    if(w.ADk && w.ADk.sessionId) {{ postSession(w.ADk.sessionId); return; }}
                  }}
                }}catch(e){{ /* cross-origin or not ready */ }}
                if(attempts < 8) setTimeout(tryAssociate, 600);
              }}

              iframe.addEventListener && iframe.addEventListener('load', tryAssociate);
              // also try immediately (in case cookie already present)
              tryAssociate();
            }})();
          </script>
        </div>
      </div>

      <div class=\"footer\">
        <div>{len(agent_names)} agent(s) available</div>
        <div><a class=\"small-link\" href=\"/obs\">Observability dashboard</a></div>
      </div>
    </div>
  </body>
  </html>"""


def _render_agent_page(agent_name: str, customer: dict) -> str:
    display_name = _friendly_agent_name(agent_name)
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <title>{display_name}</title>
  <style>
    body {{ margin: 0; font-family: Inter, system-ui, sans-serif; background: #020617; color: #e2e8f0; min-height: 100vh; display: grid; place-items: center; padding: 20px; }}
    .card {{ width: min(760px, 100%); padding: 32px; border-radius: 24px; background: rgba(15,23,42,.94); border: 1px solid rgba(148,163,184,.18); box-shadow: 0 24px 80px rgba(15,23,42,.24); }}
    h1 {{ margin: 0 0 16px; font-size: clamp(2rem, 2.8vw, 3rem); }}
    p {{ margin: 0 0 24px; color: #94a3b8; }}
    a.button {{ display: inline-block; padding: 14px 18px; border-radius: 14px; background: #2563eb; color: white; text-decoration: none; font-weight: 700; margin-right: 12px; }}
    a.button:hover {{ background: #1d4ed8; }}
    .meta {{ padding: 18px; border-radius: 18px; background: rgba(15,23,42,.88); border: 1px solid rgba(148,163,184,.12); margin-top: 24px; color: #cbd5e1; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>{display_name}</h1>
    <p>Logged in as {customer.get("name")} ({customer.get("customer_id")}).</p>
    <p>This is a simple agent landing page. In a full app, this would launch or configure the selected agent workflow.</p>
    <a class=\"button\" href=\"/dashboard\">Back to Dashboard</a>
    <a class=\"button\" style=\"background:#475569;\" href=\"/logout\">Logout</a>
    <div class=\"meta\">
      Agent directory: <strong>{agent_name}</strong>
    </div>
  </div>
</body>
</html>"""


@app.get("/obs", response_class=HTMLResponse)
async def obs_dashboard():
    """Serves the frontend dashboard for agent observability."""
    html_path = os.path.join(AGENT_DIR, "bank_agent", "observability", "dashboard.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="Dashboard file not found.", status_code=404)


@app.get("/obs/summary")
async def obs_summary(granularity: str | None = None):
    """Aggregated stats: sessions, total tokens, cost, avg latency.

    Optional ``?granularity=session|turn|cumulative`` query param overrides
    the default (env ``COST_GRANULARITY``).
    """
    gran = None
    if granularity:
        try:
            gran = CostGranularity(granularity.strip().lower())
        except ValueError:
            pass
    return store.get_summary(granularity=gran)


@app.get("/obs/traces")
async def obs_traces(limit: int = 100):
    """Individual LLM call records (newest first).

    Optional ``?limit=N`` query param controls the number of records returned
    (default 100).
    """
    return store.get_traces(limit=limit)


@app.get("/obs/tools")
async def obs_tools():
    """Per-tool call counts, success rates, and duration percentiles."""
    return store.get_tool_stats()


@app.post("/dev-ui/session")
async def dev_ui_set_session(session_id: str | None = Body(None), customer_id: str | None = Cookie(None)):
    """Associate a frontend chat session id with the logged-in customer_id.

    Expected JSON body: {"session_id": "<session-id>"}
    The server will read the logged-in `customer_id` from the cookie and
    store it in the observability store session metadata so agent code can
    later look it up via `store.get_session_meta(session_id)`.
    """
    # session_id may either be the body (JSON) or missing; ensure we have it
    if not session_id:
        return {"status": "error", "message": "session_id required"}
    # customer_id may be provided via cookie (preferred) or body fallback
    cust = _normalize_customer_id(customer_id)
    if not cust:
        return {"status": "error", "message": "no logged-in customer_id"}
    store.set_session_meta(session_id, {"customer_id": cust})
    return {"status": "ok", "session_id": session_id, "customer_id": customer_id}


@app.post("/obs/reset")
async def obs_reset():
    """Clear all recorded observability data."""
    store.reset()
    return {"status": "ok", "message": "Observability data cleared"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(customer_id: str | None = Cookie(None)):
  customer_id = _normalize_customer_id(customer_id)
  if not customer_id:
    return RedirectResponse(url="/login", status_code=303)
  customer, accounts, transactions = _get_customer_records(customer_id)
  if not customer:
    return RedirectResponse(url="/login", status_code=303)
  customer["accounts"] = accounts
  total_balance = sum(a.get("balance", 0) for a in accounts)
  total_expenses = sum(-t.get("amount", 0) for t in transactions if t.get("amount", 0) < 0)
  return HTMLResponse(content=_render_dashboard_page(_get_agent_names(), customer, total_balance, total_expenses))


@app.get("/agent/{agent_name}", response_class=HTMLResponse)
async def agent_detail(agent_name: str, customer_id: str | None = Cookie(None)):
  customer_id = _normalize_customer_id(customer_id)
  if not customer_id:
    return RedirectResponse(url="/login", status_code=303)
  customer, _, _ = _get_customer_records(customer_id)
  if not customer:
    return RedirectResponse(url="/login", status_code=303)
  agents = _get_agent_names()
  if agent_name not in agents:
    raise HTTPException(status_code=404, detail="Agent not found")
  return HTMLResponse(content=_render_agent_page(agent_name, customer))


@app.get("/login", response_class=HTMLResponse)
async def login_form():
    return HTMLResponse(content=_render_login_page())


@app.post("/login", response_class=HTMLResponse)
async def login_submit(customer_id: str = Form(...)):
    customer_id = customer_id.strip().upper()
    if not customer_id:
        return HTMLResponse(content=_render_login_page("Please enter a customer ID."), status_code=400)
    if not _customer_exists(customer_id):
        return HTMLResponse(content=_render_login_page(f"Customer ID {customer_id} not found."), status_code=400)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie("customer_id", customer_id, httponly=True, samesite="lax")
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("customer_id")
    return response


@app.get("/")
async def root():
    return HTMLResponse(content=_render_login_page())


if __name__ == "__main__":
    # 3. Start the server!
    uvicorn.run(app, host="0.0.0.0", port=port)
