"""
Training Data Collector
Automatically exports resolved incidents as fine-tuning examples.
Every resolved incident becomes a training pair:
  Input:  alert + diagnostic output
  Output: correct agent decision and action

This builds your dataset automatically while the product runs.
After 3-6 months you have enough to fine-tune your own model.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.models import Incident, IncidentStep, IncidentStatus, Resolution
from backend.config import get_settings

logger   = logging.getLogger("amfi.training")
settings = get_settings()

TRAINING_DIR = Path("./training_data")


async def export_resolved_incident(incident_id: int, db: AsyncSession) -> bool:
    """
    Export a resolved incident as a training example.
    Called automatically when the agent resolves an incident.
    """
    try:
        # Get incident
        r = await db.execute(select(Incident).where(Incident.id == incident_id))
        inc = r.scalar_one_or_none()
        if not inc or inc.status != IncidentStatus.RESOLVED:
            return False

        # Get steps
        sr = await db.execute(
            select(IncidentStep)
            .where(IncidentStep.incident_id == incident_id)
            .order_by(IncidentStep.sequence)
        )
        steps = sr.scalars().all()

        # Build training example
        example = _build_example(inc, steps)
        if not example:
            return False

        # Save to file
        TRAINING_DIR.mkdir(exist_ok=True)
        date_str = datetime.utcnow().strftime("%Y%m")
        filepath = TRAINING_DIR / f"training_{date_str}.jsonl"

        with open(filepath, "a") as f:
            f.write(json.dumps(example) + "\n")

        logger.debug("Exported training example for %s", inc.number)
        return True

    except Exception as e:
        logger.error("Training export failed for incident %d: %s", incident_id, e)
        return False


def _build_example(inc: Incident, steps: list) -> dict:
    """Build a training pair from a resolved incident."""
    if not inc.fault_category or not inc.resolution:
        return None

    # Build the input (what the agent saw)
    diagnostic_findings = []
    for step in steps:
        if step.step_type and "diagnostic" in str(step.step_type):
            if step.parsed_result and step.parsed_result.get("issues"):
                diagnostic_findings.extend(step.parsed_result["issues"])
        if step.ai_interpretation:
            diagnostic_findings.append(f"AI interpretation: {step.ai_interpretation}")

    # Build the output (what the correct action was)
    actions_taken = []
    for step in steps:
        if step.step_type and "action" in str(step.step_type):
            if step.success:
                actions_taken.append({
                    "action": step.action,
                    "success": step.success,
                    "output": (step.raw_output or "")[:200],
                })

    if not actions_taken:
        return None

    example = {
        # Metadata
        "incident_number":  inc.number,
        "fault_category":   str(inc.fault_category.value) if inc.fault_category else "unknown",
        "priority":         str(inc.priority.value) if inc.priority else "p3",
        "resolved_at_level": inc.resolved_by or "agent_l1",
        "exported_at":      datetime.utcnow().isoformat(),

        # Input — what the agent sees
        "input": {
            "alert_title":       inc.title,
            "alert_description": inc.description or "",
            "affected_host":     inc.affected_host or "",
            "affected_service":  inc.affected_service or "",
            "fault_category":    str(inc.fault_category.value) if inc.fault_category else "unknown",
            "diagnostic_findings": diagnostic_findings,
        },

        # Output — what the correct response is
        "output": {
            "actions_taken":     actions_taken,
            "resolution":        inc.resolution or "",
            "root_cause":        inc.root_cause or "",
            "resolved":          True,
        },

        # Formatted as instruction pair for fine-tuning
        "instruction": (
            f"You are an autonomous NOC agent. An incident has been reported: {inc.title}. "
            f"The host is {inc.affected_host or 'unknown'}. "
            f"Fault category: {str(inc.fault_category.value) if inc.fault_category else 'unknown'}. "
            f"Diagnostic findings: {'; '.join(diagnostic_findings[:5]) if diagnostic_findings else 'none'}. "
            f"What actions should be taken to resolve this incident?"
        ),
        "response": (
            f"Based on the diagnostic findings, I will take the following actions: "
            f"{'; '.join(a['action'] for a in actions_taken)}. "
            f"Resolution: {inc.resolution or 'Resolved by automated procedure'}"
        ),
    }
    return example


async def get_stats(db: AsyncSession) -> dict:
    """Get training data collection statistics."""
    total_resolved = (
        await db.execute(
            select(Incident).where(Incident.status == IncidentStatus.RESOLVED)
        )
    )
    resolved_count = len(total_resolved.scalars().all())

    # Count exported examples
    exported = 0
    if TRAINING_DIR.exists():
        for f in TRAINING_DIR.glob("training_*.jsonl"):
            with open(f) as fp:
                exported += sum(1 for _ in fp)

    # Count by fault category
    by_category = {}
    if TRAINING_DIR.exists():
        for f in TRAINING_DIR.glob("training_*.jsonl"):
            with open(f) as fp:
                for line in fp:
                    try:
                        ex = json.loads(line)
                        cat = ex.get("fault_category", "unknown")
                        by_category[cat] = by_category.get(cat, 0) + 1
                    except Exception:
                        pass

    return {
        "resolved_incidents":   resolved_count,
        "exported_examples":    exported,
        "by_fault_category":    by_category,
        "training_dir":         str(TRAINING_DIR.absolute()),
        "ready_to_fine_tune":   exported >= 1000,
        "recommended_minimum":  1000,
        "message": (
            f"Ready for fine-tuning! Run scripts/fine_tune.py" if exported >= 1000
            else f"{1000 - exported} more examples needed before fine-tuning (have {exported}/1000)"
        ),
    }


async def generate_synthetic_examples(count: int = 100) -> int:
    """
    Generate synthetic training examples using the LLM.
    Useful for bootstrapping before you have real incident data.
    """
    from backend.agent.llm import _call_llm

    TRAINING_DIR.mkdir(exist_ok=True)
    filepath = TRAINING_DIR / "synthetic_training.jsonl"

    fault_types = [
        "disk_full", "high_cpu", "high_memory",
        "service_down", "network_down", "database_issue",
    ]

    generated = 0
    per_type  = max(1, count // len(fault_types))

    for fault in fault_types:
        prompt = f"""Generate {per_type} realistic NOC incident scenarios for fault type: {fault}

For each scenario provide:
1. A realistic alert title
2. The affected host (use realistic hostnames like web-01, db-server-02, etc)
3. Diagnostic findings (what df/top/systemctl shows)
4. The correct remediation action
5. The resolution notes

Format each as JSON on one line with keys:
title, host, findings (list), action, resolution

Generate exactly {per_type} examples. One JSON object per line. No markdown."""

        response = await _call_llm(prompt, max_tokens=1000)
        if not response:
            continue

        for line in response.strip().split("\n"):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
                example = {
                    "fault_category": fault,
                    "priority":       "p2",
                    "resolved_at_level": "agent_l1",
                    "exported_at":    datetime.utcnow().isoformat(),
                    "source":         "synthetic",
                    "input": {
                        "alert_title":        data.get("title", ""),
                        "affected_host":      data.get("host", ""),
                        "fault_category":     fault,
                        "diagnostic_findings": data.get("findings", []),
                    },
                    "output": {
                        "actions_taken": [{"action": data.get("action",""), "success": True}],
                        "resolution":    data.get("resolution", ""),
                        "resolved":      True,
                    },
                    "instruction": f"Incident: {data.get('title','')}. Host: {data.get('host','')}. Fault: {fault}. Findings: {'; '.join(data.get('findings',[])[:3])}. What actions?",
                    "response":    f"Execute {data.get('action','')}. {data.get('resolution','')}",
                }
                with open(filepath, "a") as f:
                    f.write(json.dumps(example) + "\n")
                generated += 1
            except Exception:
                pass

    logger.info("Generated %d synthetic training examples", generated)
    return generated
