<div align="center">

# bpmn8n

**BPMN workflows on n8n, checked before they run.**

Draw real BPMN on the n8n canvas. Describe a process in plain words and an LLM researches the domain, interviews you and builds it. A workflow check catches what n8n would only reveal when a case gets stuck.

![n8n](https://img.shields.io/badge/engine-n8n-ea4b71?style=flat-square)
![License](https://img.shields.io/badge/licence-AGPL--3.0-blue?style=flat-square)
![Django](https://img.shields.io/badge/tasks-Django-0c4b33?style=flat-square)
![BPMN 2.0](https://img.shields.io/badge/notation-BPMN%202.0-1f6feb?style=flat-square)

</div>

---

## Why

n8n runs workflows well, but it does not speak the language of business processes, and a broken branch only shows up when a real case reaches it. bpmn8n adds the missing layer:

| | |
|---|---|
| 🔷 **Real BPMN** | 14 nodes (tasks, gateways, events) drawn with the official BPMN 2.0 symbols. Shapes, markers and line weights follow bpmn.io. |
| 🧠 **Studio** | Say what the process is. The LLM searches the web for the domain's rules, asks you one question at a time, then writes the activities and the workflow. |
| ✅ **Workflow check** | Every activity is imported and run against its examples, and the workflow is analysed before anything is loaded. Only what passes is published. |
| 👤 **People in the loop** | User and Manual Tasks get a page generated from the form. Final decisions always go through a person. |
| 🤖 **Small models where they shine** | [GLiNER2.5](https://github.com/fastino-ai/GLiNER2) fills task inputs from free text, [Laya](https://github.com/NandhaKishorM/laya) decides gateways in about 20 ms, Vision reads scanned documents. |
| 📈 **Process mining** | Every step lands in an event log, ready for PM4Py. |

## How it fits together

```
 describe a process ─▶ Studio (research · interview · build) ─▶ checked project
                                                                    │
 n8n  ◀── BPMN nodes ── Django tasks (OpenAPI, auto-discovered) ◀───┘
  │
  └─▶ People inbox · event log · process mining
```

## Quick start

```bash
./start.sh            # builds the nodes and starts everything (safe to re-run)
./start.sh status     # what is running
./start.sh stop       # stop, data is kept
```

Then open:

| | |
|---|---|
| http://localhost:5678 | n8n, with the BPMN canvas |
| http://localhost:8000/studio/ | design a process with the LLM |
| http://localhost:8000/docs/ | the full guide |

**Needs:** Docker, Node.js and, on a Mac, [uv](https://docs.astral.sh/uv/). Add an LLM provider key in *Admin → Settings*, or point it to a local model.

## One task, one function

```python
@task("businessRuleTask")
def check_expense_policy(request, data: Expense) -> PolicyCheck:
    """Per-person limit by category."""
    ...
```

It appears in the node's menu at once, with a typed form, validation and an OpenAPI entry.

## Learn more

The complete guide lives in [`docs/GUIDE.md`](docs/GUIDE.md): the nodes, the workflow check, Studio, people and states, extraction, OCR, process mining, BPMN coverage, tests and known limits.

The [hospital appointment project presentation](docs/presentations/hospital-appointment-management.pptx) covers the booking use case, four agent roles and their proposed course-pattern taxonomy, the complete editable workflow and its connection to bpmn8n. It contains 10 slides in English with speaker notes timed for a five-minute presentation.

## Licence

[AGPL-3.0](LICENSE): free for everyone. If you offer a modified bpmn8n as a network service, you must publish your changes under the same licence. Need to use it in a closed product? Open an issue to ask about a commercial licence.

BPMN symbols come from [bpmn-font](https://github.com/bpmn-io/bpmn-font) (SIL OFL 1.1). Process mining uses [PM4Py](https://pm4py.fit.fraunhofer.de) (AGPL-3.0). More in the guide's *Licences* section.
