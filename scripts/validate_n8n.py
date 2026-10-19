"""Static checks for the exported n8n workflows in workflows/n8n/ (no n8n instance needed).

Checks, per docs/research/02_technical_verification.md section 2:
  - top-level keys name, nodes, connections, settings;
  - every node has a UUID id, a unique name, a type in the verified table and a listed typeVersion,
    a two-number position and a parameters object;
  - every connection source and target exists, connection types are known, and AI sub-node links use
    the sub-node as the source;
  - webhook nodes carry a UUID webhookId and their paths are unique across all workflows;
  - Structured Output Parser schemas match vsia.schemas.TriageOutput (drift check);
  - Code node JavaScript parses (when `node` is on PATH).

Run: python scripts/validate_n8n.py [--dir workflows/n8n]. Exit code 1 on any error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# type -> allowed typeVersions (n8n 2.43.7; n8n-nodes-base and @n8n/n8n-nodes-langchain 2.43.5).
VERIFIED: dict[str, set[float]] = {
    "n8n-nodes-base.scheduleTrigger": {1, 1.1, 1.2, 1.3, 1.4},
    "n8n-nodes-base.webhook": {1, 1.1, 2, 2.1, 2.2},
    "n8n-nodes-base.respondToWebhook": {1, 1.1, 1.2, 1.3, 1.4, 1.5},
    "n8n-nodes-base.httpRequest": {1, 2, 3, 4, 4.1, 4.2, 4.3, 4.4, 4.5},
    "n8n-nodes-base.postgres": {1, 2, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7},
    "n8n-nodes-base.code": {1, 2},
    "n8n-nodes-base.if": {1, 2, 2.1, 2.2, 2.3},
    "n8n-nodes-base.executeWorkflow": {1, 1.1, 1.2, 1.3, 1.4},
    "n8n-nodes-base.executeWorkflowTrigger": {1, 1.1, 1.2, 1.3},
    "@n8n/n8n-nodes-langchain.agent": {1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2, 2.1, 3, 3.1},
    "@n8n/n8n-nodes-langchain.lmChatAnthropic": {1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6},
    "@n8n/n8n-nodes-langchain.lmChatOpenAi": {1, 1.1, 1.2, 1.3},
    "@n8n/n8n-nodes-langchain.lmChatOllama": {1},
    "@n8n/n8n-nodes-langchain.toolWorkflow": {1, 1.1, 1.2, 1.3, 2, 2.1, 2.2},
    "@n8n/n8n-nodes-langchain.toolHttpRequest": {1, 1.1},
    "@n8n/n8n-nodes-langchain.outputParserStructured": {1, 1.1, 1.2, 1.3},
    # Inferred, not read from package source (research 2.2): confirm by exporting from a running instance.
    "n8n-nodes-base.httpRequestTool": {4.5},
}
INFERRED = {"n8n-nodes-base.httpRequestTool"}
LEGACY = {"@n8n/n8n-nodes-langchain.toolHttpRequest"}

CONNECTION_TYPES = {"main", "ai_agent", "ai_chain", "ai_document", "ai_embedding", "ai_languageModel", "ai_memory",
                    "ai_outputParser", "ai_retriever", "ai_reranker", "ai_textSplitter", "ai_tool",
                    "ai_vectorStore"}
REQUIRED_TOP = ("name", "nodes", "connections", "settings")
REQUIRED_NODE = ("id", "name", "type", "typeVersion", "position", "parameters")


def is_uuid(v: object) -> bool:
    try:
        return isinstance(v, str) and str(uuid.UUID(v)) == v.lower()
    except ValueError:
        return False


def triage_schema() -> dict | None:
    """TriageOutput JSON schema with $defs inlined (the form embedded in the n8n parser node)."""
    sys.path.insert(0, str(REPO / "src"))
    try:
        from vsia.schemas import TriageOutput
    except Exception:  # noqa: BLE001
        return None
    schema = TriageOutput.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(x):
        if isinstance(x, dict):
            if "$ref" in x:
                return walk(dict(defs[x["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    return walk(schema)


def check_js(source: str) -> str | None:
    """Return a syntax error message, or None. n8n wraps Code node bodies in an async function."""
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write("(async function () {\n" + source + "\n});\n")
        path = f.name
    try:
        r = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=30, check=False)
        if r.returncode == 0:
            return None
        lines = r.stderr.strip().splitlines()
        return next((ln for ln in lines if "Error" in ln), lines[0] if lines else "syntax error")
    finally:
        Path(path).unlink(missing_ok=True)


def validate(path: Path, webhook_paths: dict[str, str], schema: dict | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        wf = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"], warnings

    for key in REQUIRED_TOP:
        if key not in wf:
            errors.append(f"missing top-level key '{key}'")
    nodes = wf.get("nodes", [])
    names: dict[str, dict] = {}
    ids: set[str] = set()
    for i, n in enumerate(nodes):
        label = n.get("name", f"#{i}")
        for key in REQUIRED_NODE:
            if key not in n:
                errors.append(f"node {label}: missing '{key}'")
        if label in names:
            errors.append(f"duplicate node name '{label}'")
        names[label] = n
        if not is_uuid(n.get("id")):
            errors.append(f"node {label}: id is not a UUID")
        elif n["id"] in ids:
            errors.append(f"node {label}: duplicate id")
        ids.add(n.get("id"))
        pos = n.get("position")
        if not (isinstance(pos, list) and len(pos) == 2 and all(isinstance(p, (int, float)) for p in pos)):
            errors.append(f"node {label}: position must be [x, y]")
        if not isinstance(n.get("parameters"), dict):
            errors.append(f"node {label}: parameters must be an object")

        t, v = n.get("type"), n.get("typeVersion")
        if t not in VERIFIED:
            errors.append(f"node {label}: type '{t}' is not in the verified table")
        elif not isinstance(v, (int, float)) or v not in VERIFIED[t]:
            errors.append(f"node {label}: typeVersion {v} not available for {t}")
        if t in INFERRED:
            warnings.append(f"node {label}: type '{t}' v{v} is inferred, not verified from source")
        if t in LEGACY:
            warnings.append(f"node {label}: '{t}' is legacy and hidden in n8n 2.43")

        if n.get("onError") not in (None, "stopWorkflow", "continueRegularOutput", "continueErrorOutput"):
            errors.append(f"node {label}: invalid onError '{n.get('onError')}'")

        if t == "n8n-nodes-base.webhook":
            if not is_uuid(n.get("webhookId")):
                errors.append(f"node {label}: webhookId must be a UUID")
            wpath = n.get("parameters", {}).get("path")
            if not wpath:
                errors.append(f"node {label}: webhook path missing")
            elif wpath in webhook_paths:
                errors.append(f"webhook path '{wpath}' also used in {webhook_paths[wpath]}")
            else:
                webhook_paths[wpath] = path.name

        if t == "@n8n/n8n-nodes-langchain.outputParserStructured" and schema is not None:
            try:
                embedded = json.loads(n["parameters"].get("inputSchema", ""))
            except json.JSONDecodeError:
                errors.append(f"node {label}: inputSchema is not valid JSON")
            else:
                if embedded != schema:
                    errors.append(f"node {label}: inputSchema differs from vsia.schemas.TriageOutput")

        if t == "n8n-nodes-base.code":
            err = check_js(n.get("parameters", {}).get("jsCode", ""))
            if err:
                errors.append(f"node {label}: JavaScript syntax error: {err}")

    connected: set[str] = set()
    for src, by_type in wf.get("connections", {}).items():
        if src not in names:
            errors.append(f"connection source '{src}' is not a node")
            continue
        for ctype, outputs in by_type.items():
            if ctype not in CONNECTION_TYPES:
                errors.append(f"connection from '{src}': unknown type '{ctype}'")
            for targets in outputs:
                for tgt in targets or []:
                    if tgt.get("node") not in names:
                        errors.append(f"connection {src} -> '{tgt.get('node')}': target is not a node")
                    if tgt.get("type") != ctype:
                        errors.append(f"connection {src} -> {tgt.get('node')}: type '{tgt.get('type')}' under "
                                      f"'{ctype}'")
                    if ctype != "main" and not names.get(tgt.get("node"), {}).get("type", "").endswith(".agent"):
                        warnings.append(f"connection {src} -> {tgt.get('node')}: {ctype} target is not an agent")
                    connected.update({src, tgt.get("node")})
    for label, n in names.items():
        if label not in connected and len(names) > 1:
            warnings.append(f"node {label}: not connected")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(REPO / "workflows" / "n8n"))
    args = ap.parse_args(argv)
    files = sorted(Path(args.dir).glob("*.json"))
    if not files:
        print(f"no workflow JSON found in {args.dir}")
        return 1
    schema = triage_schema()
    if schema is None:
        print("warning: could not import vsia.schemas; skipping the output-parser drift check")
    if not shutil.which("node"):
        print("warning: node not on PATH; skipping JavaScript syntax checks")
    webhook_paths: dict[str, str] = {}
    total_errors = 0
    for f in files:
        errors, warnings = validate(f, webhook_paths, schema)
        try:
            n_nodes = len(json.loads(f.read_text()).get("nodes", []))
        except json.JSONDecodeError:
            n_nodes = 0
        status = "OK" if not errors else "FAIL"
        print(f"{status:4} {f.name} ({n_nodes} nodes, {len(warnings)} warnings)")
        for e in errors:
            print(f"     error: {e}")
        for w in warnings:
            print(f"     warning: {w}")
        total_errors += len(errors)
    print(f"{len(files)} workflows, {total_errors} errors")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
