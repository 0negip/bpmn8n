# UC-01 · Intelligent hospital appointment booking

Patients can describe the appointment they need in ordinary language. Fixed menus can fall behind hospital reorganizations, so the Chat Agent reads the current service directory on every request. An unclear service remains empty for a person to clarify.

This executable demonstration uses synthetic local slots and bookings. A real integration needs adapters for the hospital directory, patient records, referral rules, booking transaction and notification delivery. The administrative booleans in the demo webhook represent trusted upstream facts. Never accept those facts directly from an untrusted patient client in a real deployment.

## Agent responsibilities

| Role | Color | Course pattern | Implementation |
|---|---|---|---|
| 0 Coordinator | Purple `#674497` | Goal Setting & Monitoring, Multi-Agent Collaboration | The workflow routes completion, retries and staff referrals |
| A Chat Agent | Teal `#096D76` | Memory Management | Configured Studio LLM proposes fields from a message and current directory. Patient reviews them |
| B Classifier | Orange `#96461D` | Guardrails/Safety, Router | Typed schema and deterministic administrative checks |
| C Booker | Blue `#305C99` | Tool Use, Exception Handling & Recovery | Database search and reservation with unique slot/request constraints |

These are four logical responsibilities. The runnable example uses one LLM call for A and deterministic controls for B, C and orchestration. A full conversational memory adapter and live hospital systems are further integration work. The taxonomy follows the university project proposal and Cimino's *Agentic Engineering* course.

## Run

From the repository root, with dependencies installed and database configured:

```bash
python manage.py migrate
python manage.py loaddata hospital_demo
python -m projects.hospital.process
python manage.py check_project projects/hospital
python manage.py test projects.hospital
```

Create the `patients` and `hospital-staff` groups in Django Admin and assign demo users to them. Configure a default LLM in Admin Settings, including Ollama as described in the main README. Import `projects/hospital/workflow.json` into n8n, assign the bpmn8n API credential to task nodes, and activate it. The example webhook body is:

```json
{
  "request_id": "DEMO-001",
  "patient_id": "DEMO-PATIENT",
  "message": "Cardiology between 2026-11-09 and 2026-11-13, in the morning",
  "registered": true,
  "referral_required": true,
  "referral_present": true
}
```

Use the n8n webhook URL shown in the editor. Dates are explicit to keep the fixture reproducible. Add future demo slots when presenting at a later date. Human tasks appear in the people inbox. The patient reviews service and dates before validation and chooses a slot before reservation. Confirmation appears in a final patient task, without sending email or SMS.

Missing/ambiguous details go through patient review. Invalid registration/referral facts go to staff. No slots leads to revised preferences or closure. A reservation conflict returns to search. Patient rejection closes the case. Reservation retries return the same booking for the same request, patient and slot. Conflicting request reuse fails. Database uniqueness arbitrates two requests for the same slot.

## Domain research

To design a variant, start a Studio project with the use case above. Its existing two-round SearXNG research works with the configured local Ollama model. Research generic appointment workflows and service-directory integration, then supply the hospital's actual rules during the interview. Web research provides design context. Runtime availability and eligibility come from hospital adapters. Keep patient identities and clinical details out of public search queries.

## Scope and validation

The generated JSON is an importable workflow example. Automated tests exercise its graph and task API, patient selection, slot conflicts and reservation replay. Running the full workflow in n8n, a live Ollama conversation and live web research require the respective services. The event log supplied by bpmn8n can support later process-mining analysis.
