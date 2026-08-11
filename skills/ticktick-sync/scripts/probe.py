# skills/ticktick-sync/scripts/probe.py
"""Ask the live TickTick API what it actually supports, and record the answers.

Nothing here is designed against a guessed endpoint. Throwaway in spirit but
committed, so the next person can re-run it when the API moves.

This probe writes into the user's real "Work" list (id
6f1e2d3c4b5a69788796a5b4), which already holds their own personal tasks. It
creates exactly one throwaway task, exercises update/complete/reopen against
it, and deletes it again at the end -- printing an unmissable warning if the
delete does not succeed.
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

BASE = "https://api.ticktick.com/open/v1"
ALT_BASE = "https://ticktick.com/open/v1"
FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"

PROJECT_ID = "6f1e2d3c4b5a69788796a5b4"  # target list, id-keyed (see docs/api-notes.md)
# Label only, used to sanity-check the id -- deliberately just the ASCII tail
# ("Work"), not the leading emoji, since that emoji does not round-trip
# reliably through every Windows console encoding.
PROJECT_NAME = "Work"


def token():
    env = pathlib.Path(os.environ["LOCALAPPDATA"]) / "ticktick-sync" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        # The user's file uses TICKTICK_API_KEY; accept both names rather than
        # making them re-edit a working secret to match our preference.
        if line.split("=")[0].strip() in ("TICKTICK_TOKEN", "TICKTICK_API_KEY"):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no TICKTICK_TOKEN or TICKTICK_API_KEY in %s" % env)


def _do_call(base, method, path, payload):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Authorization", "Bearer " + token())
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return response.status, (json.loads(body) if body.strip() else None)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")[:400]
    except urllib.error.URLError as error:
        return -1, str(error.reason)


def call(method, path, payload=None):
    """Call BASE; on a 404, retry against ALT_BASE and record which one answered."""
    status, body = _do_call(BASE, method, path, payload)
    if status == 404:
        print("  (404 on %s, trying alt base %s)" % (BASE, ALT_BASE))
        alt_status, alt_body = _do_call(ALT_BASE, method, path, payload)
        if alt_status != 404:
            print("  (alt base answered: %s -> %s)" % (ALT_BASE, alt_status))
            return alt_status, alt_body
    return status, body


def record(name, payload):
    """Write a fixture -- unless it would capture the user's own tasks.

    The original probe ran against an EMPTY target list, so the recorded
    `project_data*.json` fixtures are harmless. That list now holds the user's
    real mirrored work, and a re-run would overwrite those committed fixtures
    with their personal task titles. Refuse rather than leak.
    """
    if isinstance(payload, dict) and payload.get("tasks"):
        print("  (not recording %s: the list holds %d real task(s))"
              % (name, len(payload["tasks"])))
        return
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def task_in_list(pid, task_id):
    """Fetch one task out of the project data, or None. Read-only."""
    status, data = call("GET", "/project/%s/data" % pid)
    if status != 200:
        return None
    for task in (data or {}).get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None


def measure_dead_id_update(pid, dead_id):
    """C2: does POST /task/{id} on a DELETED id actually fail?

    `sync_core.run_sync` falls back from Reopen to Create by catching
    TickTickError out of `client.update()`. If a dead id answers 200, that
    fallback never fires: the run reports `reopened=1` forever, the item never
    comes back, and the dead id is never evicted from state.json.

    Called with an id that was created and deleted by this same probe -- it
    never points at anything the user owns.
    """
    print("== C2: UPDATE ON A DELETED TASK ID ==")
    print("dead id under test:", dead_id)
    status, body = _do_call(BASE, "POST", "/task/%s" % dead_id, {
        "id": dead_id, "projectId": pid, "title": "probe dead-id update",
        "content": "[sync:probe-dead]", "priority": 3, "status": 0})
    print("POST /task/<deleted id> -> %s %s" % (status, str(body)[:400]))
    print("VERDICT: the fallback %s -- a dead id %s"
          % ("WORKS as written" if status != 200 else "IS BROKEN",
             "errors" if status != 200 else "answers 200"))
    # A 200 would also mean the task got resurrected; make sure it did not.
    resurrected = task_in_list(pid, dead_id)
    print("is the dead id visible in the list afterwards?", resurrected is not None)
    if resurrected is not None:
        print("!! DELETE IT BY HAND: 'probe dead-id update' (id %s)" % dead_id)
    return status


def measure_whole_object_replace(pid):
    """M6: is POST /task/{id} a whole-object REPLACE or a partial merge?

    `Client.update()` sends only id/projectId/title/content/priority/status. If
    the endpoint replaces, every field it omits -- a due date the user set by
    hand, for instance -- is wiped on each sync. Creates its own throwaway task
    with a due date, updates it exactly the way the adapter does, and looks.
    """
    print("== M6: IS UPDATE A WHOLE-OBJECT REPLACE? ==")
    due = "2030-01-15T09:00:00+0000"
    status, created = call("POST", "/task", {
        "projectId": pid, "title": "probe task 2 (due date)",
        "content": "[sync:probe-2]", "priority": 3,
        "dueDate": due, "isAllDay": False, "timeZone": "Europe/Vienna"})
    print("create with dueDate ->", status, json.dumps(created, indent=2,
                                                       ensure_ascii=False)[:600])
    if status != 200:
        print("!! could not create the M6 probe task; measurement skipped")
        return None
    tid = created["id"]
    print("dueDate as created:", (created or {}).get("dueDate"))

    # Exactly the payload lib/ticktick.py Client.update() sends.
    status, updated = call("POST", "/task/%s" % tid, {
        "id": tid, "projectId": pid, "title": "probe task 2 (due date) edited",
        "content": "[sync:probe-2] edited", "priority": 5, "status": 0})
    print("adapter-shaped update ->", status,
          json.dumps(updated, indent=2, ensure_ascii=False)[:600])

    after = task_in_list(pid, tid) or {}
    survived = bool(after.get("dueDate"))
    print("dueDate after the update:", after.get("dueDate"))
    print("VERDICT: update is a %s -- the due date %s"
          % ("PARTIAL MERGE" if survived else "WHOLE-OBJECT REPLACE",
             "survived" if survived else "was wiped"))

    print("-- cleaning up the M6 probe task --")
    status, body = call("DELETE", "/project/%s/task/%s" % (pid, tid))
    print("delete ->", status, body)
    gone = task_in_list(pid, tid) is None
    print("M6 probe task gone?", gone)
    if not gone:
        print("!! DELETE IT BY HAND: 'probe task 2 (due date) edited' (id %s)" % tid)
    return survived


if __name__ == "__main__":
    # `--measure` runs only the C2/M6 measurements. The full probe re-walks
    # create/update/complete/reopen, which is already recorded in
    # docs/api-notes.md and needs no repeat against a list that is now live.
    measure_only = "--measure" in sys.argv

    print("== list projects ==")
    status, projects = call("GET", "/project")
    print(status, json.dumps(projects, indent=2, ensure_ascii=False)[:1200])
    if status == 200:
        record("projects.json", projects)
    else:
        sys.exit(1)

    pid = PROJECT_ID  # target list; already exists, never created here

    match = next((p for p in (projects or []) if p.get("id") == pid), None)
    if match is None:
        print("!! WARNING: project id %s not found in /project listing at all" % pid)
    elif PROJECT_NAME not in (match.get("name") or ""):
        # The id is what config is keyed on; the name is only a sanity label
        # (it carries an emoji that does not round-trip cleanly through every
        # Windows console encoding), so mismatch is a loud warning, not a stop.
        print("!! WARNING: project %s has name %r, expected it to contain %r" % (
            pid, match.get("name"), PROJECT_NAME))
    else:
        print("target project id confirmed: %s (%r)" % (pid, match.get("name")))

    if measure_only:
        print("== C2 setup: one throwaway task, created and then deleted ==")
        status, throwaway = call("POST", "/task", {
            "projectId": pid, "title": "probe dead-id task",
            "content": "[sync:probe-dead]", "priority": 0})
        print("create ->", status, json.dumps(throwaway, indent=2,
                                              ensure_ascii=False)[:400])
        if status != 200:
            raise SystemExit("could not create the throwaway task")
        dead = throwaway["id"]
        status, body = call("DELETE", "/project/%s/task/%s" % (pid, dead))
        print("delete ->", status, body)
        if task_in_list(pid, dead) is not None:
            print("!! DELETE IT BY HAND: 'probe dead-id task' (id %s)" % dead)
            raise SystemExit(2)
        print("deletion confirmed -- id %s is now dead" % dead)

        measure_dead_id_update(pid, dead)
        measure_whole_object_replace(pid)
        print("== measurements complete, nothing left behind ==")
        raise SystemExit(0)

    print("== project data (tasks in the list) ==")
    status, data = call("GET", "/project/%s/data" % pid)
    print(status, json.dumps(data, indent=2, ensure_ascii=False)[:1500])
    if status == 200:
        record("project_data.json", data)

    print("== create ==")
    status, created = call("POST", "/task", {
        "projectId": pid, "title": "probe task", "content": "[sync:probe-1]", "priority": 3})
    print(status, json.dumps(created, indent=2, ensure_ascii=False)[:800])
    if status != 200:
        raise SystemExit("create failed")
    record("task_created.json", created)
    tid = created["id"]

    print("== update ==")
    status, updated = call("POST", "/task/%s" % tid, {
        "id": tid, "projectId": pid, "title": "probe task edited",
        "content": "[sync:probe-1] edited", "priority": 5})
    print(status, json.dumps(updated, indent=2, ensure_ascii=False)[:800])
    if status == 200:
        record("task_updated.json", updated)

    print("== complete ==")
    status, complete_body = call("POST", "/project/%s/task/%s/complete" % (pid, tid))
    print("complete ->", status, complete_body)

    print("== is the completed task visible in project data? ==")
    status, after_complete = call("GET", "/project/%s/data" % pid)
    seen_after_complete = any(
        t.get("id") == tid for t in (after_complete or {}).get("tasks", []))
    print("visible right after complete?", seen_after_complete)
    if status == 200:
        record("project_data_after_complete.json", after_complete)

    print("== CAN A COMPLETED TASK BE RE-OPENED? ==")
    status, reopened = call("POST", "/task/%s" % tid, {
        "id": tid, "projectId": pid, "title": "probe task edited", "status": 0})
    print("reopen ->", status, json.dumps(reopened, indent=2, ensure_ascii=False)[:600])
    if status == 200:
        record("task_reopened.json", reopened)
    status, after = call("GET", "/project/%s/data" % pid)
    reopened_visible = any(t.get("id") == tid for t in (after or {}).get("tasks", []))
    print("visible again?", reopened_visible)
    if status == 200:
        record("project_data_after_reopen.json", after)

    print("== delete the probe task ==")
    status, delete_body = call("DELETE", "/project/%s/task/%s" % (pid, tid))
    print("delete ->", status, delete_body)
    status, after_delete = call("GET", "/project/%s/data" % pid)
    gone = not any(t.get("id") == tid for t in (after_delete or {}).get("tasks", []))
    print("probe task gone?", gone)
    if status == 200:
        record("project_data_after_delete.json", after_delete)
    if not gone:
        print("!! DELETE IT BY HAND in the TickTick app: 'probe task edited' (id %s)" % tid)
        sys.exit(2)

    measure_dead_id_update(pid, tid)
    measure_whole_object_replace(pid)

    print("== all probes complete, probe task cleaned up ==")
