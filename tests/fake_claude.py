#!/usr/bin/env python3
"""A stand-in for `claude` that speaks the stream-json protocol cic relies on.

Behavior is chosen with FAKE_CLAUDE_SCENARIO:
  done        report done (edits fake_output.txt)
  verify_fix  turn 1 writes "bad" to answer.txt, later turns write "good"
  needs_input report needs_input with a question
  denied      a permission denial, report partial
  auth        is_error result "Not logged in" with subtype success (real Claude does this)
  slow        keep working until interrupted; folds steering messages into the turn
  stubborn    partial, partial, then done (exercises escalation via set_model)
  noreport    first turn without structured output, then a report
  chat        plain-text echo
Every invocation's argv is appended to $FAKE_CLAUDE_LOG (one JSON line).
"""

import json
import os
import queue
import sys
import threading
import time
import uuid

args = sys.argv[1:]
log_path = os.environ.get("FAKE_CLAUDE_LOG")
if log_path:
    with open(log_path, "a") as handle:
        handle.write(json.dumps(args) + "\n")

if args[:1] == ["--version"]:
    print("2.1.291 (Claude Code)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro"}))
    sys.exit(0)


def flag(name, default=None):
    if name in args:
        index = args.index(name)
        return args[index + 1] if index + 1 < len(args) else default
    return default


scenario = os.environ.get("FAKE_CLAUDE_SCENARIO", "done")
model = flag("--model", "sonnet")
schema = flag("--json-schema")
session = flag("--session-id") or flag("--resume") or str(uuid.uuid4())
mode = flag("--permission-mode", "default")
if mode == "auto" and "haiku" in model:
    mode = "default"
replay = "--replay-user-messages" in args
state_file = os.path.join(os.getcwd(), ".fake_claude_turns")
models_file = os.environ.get("FAKE_CLAUDE_MODELS")

inbox: "queue.Queue" = queue.Queue()


def reader():
    for line in sys.stdin:
        line = line.strip()
        if line:
            inbox.put(json.loads(line))
    inbox.put(None)


threading.Thread(target=reader, daemon=True).start()


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


cost = 0.0


def turn_count():
    try:
        return int(open(state_file).read())
    except (OSError, ValueError):
        return 0


def bump_turn():
    count = turn_count() + 1
    with open(state_file, "w") as handle:
        handle.write(str(count))
    return count


def report(status, summary, **extra):
    data = {"status": status, "summary": summary, "changes": [], "verification": [], "assumptions": [],
            "risks": [], "open_questions": [], "next_steps": [], "confidence": 0.8}
    data.update(extra)
    return data


def finish(result_text=None, structured=None, subtype="success", is_error=False, terminal="completed", denials=None):
    global cost
    cost += 0.01
    event = {"type": "result", "subtype": subtype, "is_error": is_error, "terminal_reason": terminal,
             "result": result_text, "session_id": session, "total_cost_usd": round(cost, 4), "num_turns": 1,
             "permission_denials": denials or [], "queued_turn_count": 0, "modelUsage": {model: {}}}
    if structured is not None:
        event["structured_output"] = structured
        event["result"] = json.dumps(structured)
    emit(event)


def tool(name, data):
    emit({"type": "assistant", "parent_tool_use_id": None,
          "message": {"content": [{"type": "tool_use", "id": "t" + uuid.uuid4().hex[:6], "name": name, "input": data}]}})


def say(text):
    emit({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [{"type": "text", "text": text}]}})


def ack(message):
    if replay:
        emit({"type": "user", "isReplay": True, "parent_tool_use_id": None, "message": message["message"]})


def answer_for_schema(turn, text):
    if schema and '"verdict"' in schema:
        return report_review()
    if schema and '"steps"' in schema:
        return {"summary": "plan", "approach": "do the simple thing", "alternatives": [{"option": "x", "why_not": "y"}],
                "steps": [{"title": "edit", "details": "change file", "files": ["a.py"], "verify": "true"}],
                "risks": [], "verification": ["true"], "open_questions": []}
    return None


def report_review():
    verdict = os.environ.get("FAKE_REVIEW_VERDICT", "approve")
    findings = [] if verdict == "approve" else [{"severity": "high", "title": "bug", "file": "a.py", "line_start": 1,
                                                 "line_end": 2, "body": "breaks", "recommendation": "fix it",
                                                 "confidence": 0.9}]
    return {"verdict": verdict, "summary": "ship" if verdict == "approve" else "no-ship", "findings": findings,
            "next_steps": []}


def handle(message):
    text = message["message"]["content"]
    text = text if isinstance(text, str) else json.dumps(text)
    ack(message)
    turn = bump_turn()
    special = answer_for_schema(turn, text)
    if special is not None:
        tool("Read", {"file_path": "a.py"})
        finish(structured=special)
        return
    if scenario == "chat" or not schema:
        say(f"echo: {text[-200:]}")
        finish(result_text=f"echo turn {turn}: {text[-120:]}")
        return
    if scenario == "done":
        tool("Write", {"file_path": os.path.join(os.getcwd(), "fake_output.txt")})
        open("fake_output.txt", "w").write("ok\n")
        finish(structured=report("done", "did it", changes=[{"path": "fake_output.txt", "change": "created"}],
                                 verification=[{"command": "true", "outcome": "pass", "details": "ok"}]))
    elif scenario == "verify_fix":
        content = "bad" if turn == 1 else "good"
        tool("Edit", {"file_path": os.path.join(os.getcwd(), "answer.txt")})
        open("answer.txt", "w").write(content + "\n")
        finish(structured=report("done", f"wrote {content}"))
    elif scenario == "needs_input":
        finish(structured=report("needs_input", "need a decision", open_questions=["Which database?"]))
    elif scenario == "denied":
        emit({"type": "system", "subtype": "permission_denied", "tool_name": "Bash", "message": "denied"})
        finish(structured=report("partial", "could not run tests"),
               denials=[{"tool_name": "Bash", "tool_use_id": "x", "tool_input": {"command": "npm install"}}])
    elif scenario == "auth":
        finish(result_text="Not logged in · Please run /login", is_error=True, terminal="api_error")
    elif scenario == "stubborn":
        if turn < 3:
            finish(structured=report("partial", f"turn {turn} incomplete", next_steps=["finish the rest"]))
        else:
            finish(structured=report("done", "finally done"))
    elif scenario == "noreport":
        if turn == 1:
            finish(result_text="I did the work but forgot the report")
        else:
            finish(structured=report("done", "here is the report"))
    elif scenario == "slow":
        steered = []
        for _ in range(240):
            tool("Bash", {"command": "sleep 0.25"})
            time.sleep(0.25)
            try:
                incoming = inbox.get_nowait()
            except queue.Empty:
                continue
            if incoming is None:
                return
            if incoming.get("type") == "control_request":
                if not control(incoming):
                    finish(subtype="error_during_execution", is_error=True, terminal="aborted_streaming")
                    return
            elif incoming.get("type") == "user":
                ack(incoming)
                steered.append(incoming["message"]["content"])
                if len(steered) >= 1:
                    break
        finish(structured=report("done", "STEERED: " + " | ".join(str(s) for s in steered)))


def control(message):
    """Answer a control request; return False when it was an interrupt."""
    request = message.get("request") or {}
    emit({"type": "control_response", "response": {"subtype": "success", "request_id": message.get("request_id")}})
    if request.get("subtype") == "set_model":
        global model
        model = request.get("model")
        if models_file:
            with open(models_file, "a") as handle:
                handle.write(model + "\n")
        return True
    return request.get("subtype") != "interrupt"


emit({"type": "system", "subtype": "init", "session_id": session, "model": model, "permissionMode": mode,
      "cwd": os.getcwd(), "tools": [], "capabilities": ["interrupt_receipt_v1"]})
while True:
    item = inbox.get()
    if item is None:
        break
    if item.get("type") == "control_request":
        control(item)
        continue
    if item.get("type") == "user":
        handle(item)
sys.exit(0)
