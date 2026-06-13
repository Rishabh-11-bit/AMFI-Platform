# AMFI v4 — Autonomous NOC Agent

Purpose-built autonomous NOC agent that handles L1 and L2 incident resolution without human intervention.

## Current Status

**Active development — core agent loop is fully functional.**

| Component | Status |
|---|---|
| Alert ingestion (Prometheus, Zabbix, SolarWinds, PRTG, manual) | ✅ Working |
| Fault classifier (pattern matching → fault type + ITIL priority) | ✅ Working |
| SSH diagnostics executor | ✅ Working |
| Llama 3.1 integration (local via Ollama) | ✅ Working |
| Fix executor (restart, disk clear, memory cache clear) | ✅ Working |
| Fix verification | ✅ Working |
| L3 escalation with AI-written brief | ✅ Working |
| React dashboard (live feed, incidents, approvals, hosts, analytics) | ✅ Working |
| Training data export | ✅ Working |
| NMS webhook connectors | ✅ Working |
| ITSM connectors (ServiceNow, Jira) | 🔧 In progress |
| Multi-host orchestration | 🔧 Planned |

## What it does

1. Receives an alert (from a monitoring tool or manually submitted)
2. Classifies the fault — `disk_full`, `high_cpu`, `service_down`, `high_memory`, etc. — using pure regex, no AI
3. Sets ITIL priority P1–P4 and starts the SLA clock
4. SSHs into the affected host and runs targeted diagnostics
5. Feeds the diagnostic output to **Llama 3.1** (running locally via Ollama) to identify root cause
6. Executes the fix — restart service, clear disk, flush memory cache
7. Verifies the fix worked
8. If resolved: logs the incident, notifies, closes
9. If unresolvable: Llama 3.1 writes a full L3 escalation brief, engineer gets complete context

AI is used in exactly **2 places**: reading SSH output and writing escalation briefs. Everything else is deterministic code.

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up database
```bash
python scripts/setup_db.py
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env — set SSH credentials, Ollama URL, NMS endpoints
```

### 4. Install Ollama + pull model
```bash
# Linux:
bash scripts/setup_ollama.sh

# Windows — download from https://ollama.ai, then:
ollama pull llama3.1
```

### 5. Run
```bash
python run.py
# Dashboard: http://localhost:8000
```

## Docker (recommended)
```bash
cp .env.example .env
bash docker-start.sh
# Dashboard: http://localhost:8000
```

## Architecture

```
Alert (Prometheus / Zabbix / SolarWinds / PRTG / manual)
    │
    ▼
Fault Classifier  ──→  fault type + ITIL priority P1-P4
    │
    ▼
Procedure Library  ──→  step sequence for this fault type
    │
    ▼
Executor
    ├── ping (is host reachable?)
    ├── SSH diagnostics (disk / cpu / memory / service / logs)
    ├── Llama 3.1 (root cause from diagnostic output)
    ├── Fix (restart / clear disk / flush memory)
    └── Verify
    │
    ├── Resolved ──→ log + notify + close
    └── Escalated ──→ Llama 3.1 writes L3 brief + notify engineer
```

## Dashboard Pages

| Page | Purpose |
|---|---|
| Dashboard | Live agent feed, recent incidents, resolution stats |
| Incidents | Full list with search/filter, manual incident creation |
| Incident Detail | Step-by-step timeline of every agent action |
| Approvals | One-click approve/reject for risky actions before execution |
| Hosts | CMDB — add and manage servers with SSH credentials |
| NMS Sources | Connect Prometheus, Zabbix, SolarWinds, PRTG |
| Analytics | Auto-resolution rate, MTTR, ROI estimator, agent memory |

## Training Data

Every resolved incident is automatically exported as a fine-tuning example. After enough production incidents you have a dataset to fine-tune a smaller, specialized model.

```bash
python scripts/export_training.py
```

## Default Credentials
- Username: `admin`
- Password: `amfi2024!`
- **Change these before any real deployment**
