# AMFI v4 — Autonomous NOC Agent

Purpose-built autonomous NOC agent that handles L1 and L2 incident resolution automatically.

## What it does

- Receives alerts from Prometheus, Zabbix, SolarWinds, PRTG or manual input
- Classifies the fault type using pattern matching (no AI needed)
- Runs SSH diagnostics on the affected host
- Uses Llama 3.1 (running locally on your server) to interpret what the diagnostics mean
- Executes the fix — restart service, clear disk, clear memory cache
- Verifies the fix worked
- Escalates to L3 with a full written brief if it cannot resolve
- Records every resolved incident as training data for future model fine-tuning

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up database
```bash
python scripts/setup_db.py
```

### 3. Configure
```bash
cp .env.example .env
# Edit .env with your settings
```

### 4. Install Ollama (AI engine — runs locally)
```bash
# Linux server:
bash scripts/setup_ollama.sh

# Windows:
# Download from https://ollama.ai and run:
ollama pull llama3.1
```

### 5. Start
```bash
python run.py
# Open: http://localhost:8000
```

## Docker (easiest)
```bash
cp .env.example .env
bash docker-start.sh
# Open: http://localhost:8000
```

## Architecture

```
Alert arrives (Prometheus/Zabbix/SolarWinds/PRTG/manual)
    │
    ▼
Fault Classifier (pure regex — no AI)
    Maps alert → disk_full / high_cpu / service_down / etc.
    Sets ITIL priority P1-P4
    Starts SLA clock
    │
    ▼
Procedure Lookup (hardcoded library)
    Gets the step sequence for this exact fault type
    │
    ▼
Executor (deterministic code)
    Step 1: ping — is host reachable?
    Step 2: SSH diagnostics — disk/cpu/memory/service/logs
    Step 3: Llama 3.1 reads output — what is the root cause?
    Step 4: Execute fix — restart/clear disk/clear memory
    Step 5: Verify fix worked
    │
    ▼
Resolved → writes resolution record, notifies, closes
   OR
Escalated → Llama 3.1 writes L3 brief, engineer gets full context
```

## AI is used in exactly 2 places

1. Reading SSH diagnostic output to identify root cause
2. Writing escalation briefs for L3 engineers

Everything else is deterministic code. Predictable. Auditable. Certifiable.

## Pages

- **Dashboard** — live agent feed, recent incidents, stats
- **Incidents** — full list with search and filter, create incidents
- **Incident Detail** — step-by-step timeline of what the agent did
- **Approvals** — approve/reject risky actions with one click
- **Hosts** — CMDB, add servers with SSH credentials
- **NMS Sources** — connect monitoring tools
- **Analytics** — auto-resolution rate, ROI estimator, agent memory

## Training Data

Every resolved incident is automatically exported as a fine-tuning example.
After 3-6 months of production use you have enough data to fine-tune your own model.

```bash
python scripts/export_training.py
```

## Default credentials
- Username: admin
- Password: amfi2024!
- **Change before production deployment**
