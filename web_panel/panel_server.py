#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
REPORTS = APP / "reports"
DOCS = APP / "docs"
PROMPTS = APP / "prompts"
TOKEN_FILE = STATE / "panel_token.txt"

HOST = "0.0.0.0"
PORT = 8080
WORKERS = ["worker-1", "worker-2", "worker-3", "worker-4"]

def now():
    return datetime.now(timezone.utc).isoformat()

def read_text(path, default=""):
    try:
        return Path(path).read_text(errors="replace")
    except Exception:
        return default

def read_json(path, default=None):
    if default is None:
        default = {}
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text())
    except Exception as exc:
        return {"error": str(exc), "path": str(path)}
    return default

def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    tmp = Path(path).with_suffix(Path(path).suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)

def tail(path, lines=120):
    text = read_text(path, "")
    if not text:
        return ""
    return "\n".join(text.splitlines()[-lines:])

def token():
    return read_text(TOKEN_FILE, "").strip()

def is_auth(handler):
    parsed = urlparse(handler.path)
    query = parse_qs(parsed.query)
    t = token()
    if not t:
        return False
    if query.get("token", [""])[0] == t:
        return True
    return f"codex_panel_token={t}" in handler.headers.get("Cookie", "")

def audit(action, ok=True, detail=""):
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "audit.log").open("a", encoding="utf-8") as f:
        f.write(f"{now()} action={action} ok={ok} detail={detail}\n")

def run_cmd(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=str(APP), text=True, capture_output=True, timeout=timeout)
        return {
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout": p.stdout[-5000:],
            "stderr": p.stderr[-5000:],
            "cmd": " ".join(cmd)
        }
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": str(exc), "cmd": " ".join(cmd)}

def service_status(name):
    r = run_cmd(["systemctl", "is-active", name], timeout=15)
    return (r["stdout"].strip() or "unknown")

def service_enabled(name):
    r = run_cmd(["systemctl", "is-enabled", name], timeout=15)
    return (r["stdout"].strip() or "unknown")

def all_services():
    names = [
        "codex-panel",
        "codex-lifecycle",
        "codex-cto",
        "codex-worker-1",
        "codex-worker-2",
        "codex-worker-3",
        "codex-worker-4",
        "codex-watchdog",
    ]
    return [
        {
            "name": name,
            "active": service_status(name),
            "enabled": service_enabled(name)
        }
        for name in names
    ]

def system_payload():
    return {
        "ok": True,
        "time": now(),
        "state": read_json(STATE / "system_state.json", {}),
        "workers": read_json(STATE / "workers.json", {"workers": []}),
        "queue": read_json(STATE / "task_queue.json", {"tasks": []}),
        "approvals": read_json(STATE / "approval_requests.json", {"approvals": []}),
        "modules": read_json(STATE / "module_registry.json", {"modules": []}),
        "actions": read_json(STATE / "action_catalog.json", {"actions": []}),
        "service_health": read_json(STATE / "service_health.json", {}),
        "service_recovery_policy": read_json(STATE / "service_recovery_policy.json", {}),
        "services": all_services(),
        "agent_onboarding_status": read_json(STATE / "agent_onboarding_status.json", {}),
        "agent_onboarding_map": read_text(DOCS / "AGENT_ONBOARDING_MAP.md", ""),
        "new_agent_prompt": read_text(PROMPTS / "NEW_AGENT_START_PROMPT.md", ""),
        "quality_gate": {
            "preflight": read_json(STATE / "quality_gate_preflight.json", {}),
            "tests": read_json(STATE / "quality_gate_tests.json", {}),
            "status": read_json(STATE / "quality_gate_status.json", {}),
            "diff": read_json(STATE / "quality_gate_diff.json", {}),
        },
        "drift_report": read_json(STATE / "drift_report.json", {}),
        "reports": sorted([p.name for p in REPORTS.glob("*.md")])[-40:] if REPORTS.exists() else [],
        "logs": {
            "system": tail(LOGS / "system.log", 120),
            "watchdog": tail(LOGS / "service_watchdog.log", 120),
            "lifecycle": tail(LOGS / "lifecycle.log", 120),
            "drift": tail(LOGS / "drift_checker.log", 120),
            "audit": tail(LOGS / "audit.log", 160),
        }
    }

def add_task(title, desc, risk):
    return run_cmd(["python3", "supervisor/supervisor_cli.py", "add-task", "--title", title, "--description", desc or title, "--risk", risk], timeout=60)

def worker_action(worker, action):
    if worker not in WORKERS:
        return {"ok": False, "error": "invalid_worker"}
    if action not in ["start", "stop", "restart", "status"]:
        return {"ok": False, "error": "invalid_action"}
    svc = f"codex-{worker}"
    cmd = ["systemctl", "is-active", svc] if action == "status" else ["sudo", "systemctl", action, svc]
    return run_cmd(cmd, timeout=60)

def html():
    return r'''<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>Codex Dev Center Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:Arial,sans-serif;margin:0;background:#f6f7f9;color:#111827}
header{background:#111827;color:white;padding:18px 24px}
main{padding:22px;max-width:1600px;margin:auto}
.grid{display:grid;grid-template-columns:repeat(4,minmax(170px,1fr));gap:14px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.card{background:white;border-radius:12px;padding:18px;margin-bottom:18px;box-shadow:0 1px 5px rgba(0,0,0,.08)}
.metric{font-size:23px;font-weight:bold;margin-top:8px}
.label,.small{color:#6b7280;font-size:13px}
pre,textarea{white-space:pre-wrap;word-break:break-word;background:#f3f4f6;padding:12px;border-radius:8px;font-size:13px;max-height:420px;overflow:auto}
textarea{width:100%;box-sizing:border-box;min-height:220px}
table{width:100%;border-collapse:collapse}
th,td{padding:9px;border-bottom:1px solid #e5e7eb;text-align:left;font-size:14px;vertical-align:top}
.badge{display:inline-block;padding:4px 8px;border-radius:999px;background:#e5e7eb;margin:2px 4px 2px 0;font-size:12px}
.ok{background:#dcfce7}.warn{background:#fef3c7}.bad{background:#fee2e2}
button{border:0;border-radius:8px;padding:9px 12px;cursor:pointer;margin:3px;background:#2563eb;color:white}
button.secondary{background:#4b5563}button.danger{background:#dc2626}button.safe{background:#16a34a}
input,select{width:100%;box-sizing:border-box;border:1px solid #e5e7eb;border-radius:8px;padding:10px;margin:6px 0 12px}
.result{background:#f3f4f6;border-radius:8px;padding:10px;white-space:pre-wrap}
@media(max-width:1000px){.grid,.row{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
<h2>Codex Dev Center Dashboard</h2>
<div>Canlı durum + servis recovery + yeni ajan onboarding + worker/task/modül yönetimi</div>
</header>
<main>

<div class="grid">
<div class="card"><div class="label">System phase</div><div class="metric" id="phase">-</div></div>
<div class="card"><div class="label">Worker</div><div class="metric" id="workerCount">-</div></div>
<div class="card"><div class="label">Aktif görev</div><div class="metric" id="taskCount">-</div></div>
<div class="card"><div class="label">Bekleyen onay</div><div class="metric" id="approvalCount">-</div></div>
</div>

<div class="card">
<h3>Canlı Durum</h3>
<span class="badge ok" id="live">Bağlanıyor...</span>
<span class="badge" id="lastUpdate">-</span>
<span class="badge" id="autostart">Autostart: -</span>
<span class="badge" id="selfhealing">Self-healing: -</span>
</div>

<div class="card">
<h3>Service Health / Recovery Center</h3>
<div class="small">VM yeniden başlarsa veya servis düşerse watchdog sistemi servisleri ayağa kaldırır. Bu bölüm servislerin active/enabled durumunu canlı gösterir.</div>
<button class="safe" onclick="runServiceHealth()">Servis Health Check Çalıştır</button>
<button class="secondary" onclick="refreshDashboard()">Şimdi Güncelle</button>
<div id="servicesTable">Yükleniyor...</div>
<h4>Son Service Health</h4>
<pre id="serviceHealth">Yükleniyor...</pre>
</div>

<div class="card">
<h3>Yeni Ajan Başlangıç Haritası</h3>
<div class="small">Hafızası olmayan yeni ajan önce bu promptu alır, sonra okuma ağacını takip eder.</div>
<button class="safe" onclick="validateAgentOnboarding()">Onboarding Dosyalarını Doğrula</button>
<button class="secondary" onclick="copyPrompt()">Yeni Ajan Promptunu Kopyala</button>
<h4>Yeni Ajana İlk Söylenecek Prompt</h4>
<textarea id="newAgentPromptBox"></textarea>
<h4>Okuma Haritası</h4>
<pre id="onboardingMap">Yükleniyor...</pre>
</div>

<div class="row">
<div class="card">
<h3>Görev Ekle</h3>
<input id="taskTitle" placeholder="Görev başlığı">
<input id="taskDesc" placeholder="Açıklama">
<select id="taskRisk"><option>low</option><option>medium</option><option>high</option><option>critical</option></select>
<button onclick="addTask()">Görev Ekle</button>
<button class="safe" onclick="dispatchTasks()">Dispatch</button>
</div>
<div class="card">
<h3>Son Aksiyon Sonucu</h3>
<div class="result" id="actionResult">Henüz aksiyon yok.</div>
</div>
</div>

<div class="card">
<h3>Worker Kontrol</h3>
<div id="workerControls">Yükleniyor...</div>
</div>

<div class="card">
<h3>Codex Quality Gate</h3>
<button class="safe" onclick="apiPost('codex_preflight')">Preflight Kontrol</button>
<button class="safe" onclick="apiPost('codex_test_suite')">Test Suite Çalıştır</button>
<button class="secondary" onclick="apiPost('codex_diff_report')">Diff Raporu Al</button>
<button class="secondary" onclick="apiPost('codex_gate_status')">Gate Durumu</button>
<pre id="qualityGate">Yükleniyor...</pre>
</div>

<div class="card">
<h3>Worker Lifecycle / Drift Control</h3>
<button class="secondary" onclick="apiPost('sleep_idle_workers')">Boş Workerları Uyut</button>
<button class="safe" onclick="apiPost('wake_required_workers')">Workerları Uyandır</button>
<button class="safe" onclick="apiPost('run_drift_check')">Drift Kontrol Çalıştır</button>
<pre id="driftReport">Yükleniyor...</pre>
</div>

<div class="row">
<div class="card"><h3>Workers</h3><div id="workersTable">Yükleniyor...</div></div>
<div class="card"><h3>Task Queue</h3><div id="tasksTable">Yükleniyor...</div></div>
</div>

<div class="card"><h3>Modules</h3><div id="modulesTable">Yükleniyor...</div></div>
<div class="card"><h3>Action Catalog</h3><div id="actionsTable">Yükleniyor...</div></div>
<div class="card"><h3>Approvals</h3><pre id="approvals">Yükleniyor...</pre></div>
<div class="card"><h3>Watchdog Log</h3><pre id="watchdogLog">Yükleniyor...</pre></div>
<div class="card"><h3>Audit Log</h3><pre id="auditLog">Yükleniyor...</pre></div>

</main>

<script>
let lastPrompt = "";
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function cls(s){s=String(s||'').toUpperCase();if(['ACTIVE','ENABLED','IDLE','READY','DONE','PASS','TRUE'].includes(s))return'badge ok';if(['SLEEPING','PENDING','QUEUED','ASSIGNED','RUNNING','WARN'].includes(s))return'badge warn';if(['FAILED','ERROR','INACTIVE','DISABLED','STOPPED','FAIL','FALSE'].includes(s))return'badge bad';return'badge'}
function table(headers, rows){return '<table><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows+'</tbody></table>'}
function renderServices(a){return table(['Servis','Active','Enabled'],(a||[]).map(s=>`<tr><td>${esc(s.name)}</td><td><span class="${cls(s.active)}">${esc(s.active)}</span></td><td><span class="${cls(s.enabled)}">${esc(s.enabled)}</span></td></tr>`))}
function renderWorkers(w){let a=w?.workers||[];return table(['ID','Rol','Durum','Görev','Son'],a.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.role)}</td><td><span class="${cls(x.status)}">${esc(x.status)}</span></td><td>${esc(x.current_task||'-')}</td><td>${esc(x.last_seen||'-')}</td></tr>`))}
function renderWorkerControls(w){let a=w?.workers||[];return a.map(x=>`<div><b>${esc(x.id)}</b> <span class="${cls(x.status)}">${esc(x.status)}</span> <button onclick="workerAction('${esc(x.id)}','start')">Başlat</button><button class="secondary" onclick="workerAction('${esc(x.id)}','restart')">Restart</button><button class="danger" onclick="workerAction('${esc(x.id)}','stop')">Durdur</button><button class="secondary" onclick="workerAction('${esc(x.id)}','status')">Durum</button></div>`).join('')}
function renderTasks(q){let a=q?.tasks||[];return table(['ID','Başlık','Durum','Worker','Risk'],a.slice().reverse().slice(0,30).map(t=>`<tr><td>${esc(t.id)}</td><td>${esc(t.title)}</td><td><span class="${cls(t.status)}">${esc(t.status)}</span></td><td>${esc(t.assigned_worker||'-')}</td><td>${esc(t.risk||'-')}</td></tr>`))}
function renderModules(m){let a=m?.modules||[];return table(['ID','Modül','Durum','Risk','Ayar','Aksiyon'],a.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.name)}</td><td><span class="${cls(x.status)}">${esc(x.status)}</span></td><td>${esc(x.risk)}</td><td>${esc(x.settings_enabled)}</td><td>${esc(x.actions_enabled)}</td></tr>`))}
function renderActions(c){let a=c?.actions||[];return table(['ID','Label','Module','Risk','Onay','Aktif'],a.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.label)}</td><td>${esc(x.module)}</td><td>${esc(x.risk)}</td><td>${esc(x.requires_approval)}</td><td>${esc(x.enabled)}</td></tr>`))}
function setResult(x){actionResult.textContent=typeof x==='string'?x:JSON.stringify(x,null,2)}
async function apiPost(action,payload={}){let r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...payload})});let d=await r.json();setResult(d);await refreshDashboard();return d}
async function runServiceHealth(){await apiPost('run_service_health_check')}
async function validateAgentOnboarding(){await apiPost('validate_agent_onboarding')}
async function addTask(){let title=taskTitle.value.trim();if(!title){setResult('Başlık boş olamaz');return}await apiPost('add_task',{title,description:taskDesc.value.trim(),risk:taskRisk.value})}
async function dispatchTasks(){await apiPost('dispatch_tasks')}
async function workerAction(worker,worker_action){await apiPost('worker_action',{worker,worker_action})}
function copyPrompt(){newAgentPromptBox.select();document.execCommand('copy');setResult('Yeni ajan promptu kopyalandı.')}
async function refreshDashboard(){
 try{
  let r=await fetch('/api/status',{cache:'no-store'}); if(!r.ok)throw new Error('HTTP '+r.status); let d=await r.json();
  let st=d.state||{}, w=d.workers||{}, q=d.queue||{}, ap=d.approvals||{};
  phase.textContent=st.phase||'unknown';
  workerCount.textContent=(w.workers||[]).length;
  taskCount.textContent=(q.tasks||[]).filter(t=>['PENDING','QUEUED','ASSIGNED','RUNNING'].includes(String(t.status).toUpperCase())).length;
  approvalCount.textContent=(ap.approvals||[]).filter(a=>String(a.status).toUpperCase()==='PENDING').length;
  live.textContent='Canlı bağlantı OK'; live.className='badge ok';
  lastUpdate.textContent='Son güncelleme: '+new Date().toLocaleTimeString();
  autostart.textContent='Autostart: '+st.autostart_on_reboot_enabled;
  selfhealing.textContent='Self-healing: '+st.self_healing_enabled;
  servicesTable.innerHTML=renderServices(d.services||[]);
  serviceHealth.textContent=JSON.stringify(d.service_health||{},null,2);
  if(d.new_agent_prompt && !lastPrompt){lastPrompt=d.new_agent_prompt;newAgentPromptBox.value=d.new_agent_prompt;}
  onboardingMap.textContent=d.agent_onboarding_map||'';
  workerControls.innerHTML=renderWorkerControls(w);
  workersTable.innerHTML=renderWorkers(w);
  tasksTable.innerHTML=renderTasks(q);
  modulesTable.innerHTML=renderModules(d.modules||{});
  actionsTable.innerHTML=renderActions(d.actions||{});
  approvals.textContent=JSON.stringify(ap,null,2);
  qualityGate.textContent=JSON.stringify(d.quality_gate||{},null,2);
  driftReport.textContent=JSON.stringify(d.drift_report||{},null,2);
  watchdogLog.textContent=d.logs?.watchdog||'';
  auditLog.textContent=d.logs?.audit||'';
 }catch(e){live.textContent='Hata: '+e.message;live.className='badge bad'}
}
refreshDashboard();setInterval(refreshDashboard,2000);
</script>
</body>
</html>'''
    
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        LOGS.mkdir(parents=True, exist_ok=True)
        with (LOGS / "panel_access.log").open("a", encoding="utf-8") as f:
            f.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send(self, raw, typ="application/json; charset=utf-8", code=200, cookie=False):
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", f"codex_panel_token={token()}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, data, code=200):
        self.send(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), code=code)

    def body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        if not is_auth(self):
            if parsed.path == "/health":
                self.send_json({"ok": False, "error": "unauthorized"}, 401)
            else:
                self.send(b"<h2>Giris gerekli</h2><p>Tokenli panel linkini kullanin.</p>", "text/html; charset=utf-8", 401)
            return

        if parsed.path == "/health":
            self.send_json({"ok": True, "service": "codex-panel", "dashboard_v3": True})
            return
        if parsed.path == "/api/status":
            self.send_json(system_payload())
            return
        if parsed.path in ("/", "/index.html"):
            self.send(html().encode("utf-8"), "text/html; charset=utf-8", 200, True)
            return
        self.send_json({"ok": False, "error": "not_found"}, 404)

    def do_POST(self):
        if not is_auth(self):
            self.send_json({"ok": False, "error": "unauthorized"}, 401)
            return

        b = self.body()
        action = b.get("action", "")

        try:
            if action == "run_service_health_check":
                self.send_json(run_cmd(["python3", "supervisor/service_watchdog.py"], 120))
                return
            if action == "validate_agent_onboarding":
                self.send_json(run_cmd(["python3", "supervisor/agent_onboarding.py"], 60))
                return
            if action == "add_task":
                self.send_json(add_task(str(b.get("title","")), str(b.get("description","")), str(b.get("risk","low"))))
                return
            if action == "dispatch_tasks":
                self.send_json(run_cmd(["python3", "supervisor/supervisor_cli.py", "dispatch"], 60))
                return
            if action == "worker_action":
                self.send_json(worker_action(str(b.get("worker","")), str(b.get("worker_action",""))))
                return
            if action == "sleep_idle_workers":
                self.send_json(run_cmd(["python3", "supervisor/lifecycle_manager.py", "sleep-now"], 90))
                return
            if action == "wake_required_workers":
                self.send_json(run_cmd(["python3", "supervisor/lifecycle_manager.py", "wake-now"], 90))
                return
            if action == "run_drift_check":
                self.send_json(run_cmd(["python3", "supervisor/drift_checker.py"], 120))
                return
            if action == "codex_preflight":
                self.send_json(run_cmd(["python3", "supervisor/codex_quality_gate.py", "preflight"], 120))
                return
            if action == "codex_test_suite":
                self.send_json(run_cmd(["python3", "supervisor/codex_quality_gate.py", "test-suite"], 180))
                return
            if action == "codex_diff_report":
                self.send_json(run_cmd(["python3", "supervisor/codex_quality_gate.py", "diff-report"], 120))
                return
            if action == "codex_gate_status":
                self.send_json(run_cmd(["python3", "supervisor/codex_quality_gate.py", "status"], 120))
                return

            self.send_json({"ok": False, "error": "unknown_action"}, 400)
        except Exception as exc:
            audit(action or "unknown", False, str(exc))
            self.send_json({"ok": False, "error": str(exc)}, 500)

def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Codex dashboard v3 listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
