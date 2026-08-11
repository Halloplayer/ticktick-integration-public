"""The writing edge. Kept thin so the interesting part stays pure.

Field names and paths come from docs/api-notes.md -- measured, not guessed.
"""
import json
import urllib.error
import urllib.request

from .models import Task, display_tags, key_from_body, tag_set

BASE = "https://api.ticktick.com/open/v1"
DONE = 2  # TickTick: status 2 == done


class TickTickError(Exception):
    pass


def tasks_from_payload(payload):
    """Only what carries a marker belongs to the mirror.

    Everything else the user created themselves. Touching it would be an
    intrusion; completing it would be data loss.
    """
    tasks = {}
    for raw in payload.get("tasks", []):
        body = raw.get("content") or ""
        key = key_from_body(body)
        if not key:
            continue
        tasks[key] = Task(key=key, task_id=raw["id"], title=raw.get("title", ""),
                          body=body, tags=tag_set(raw.get("tags")),
                          completed=raw.get("status", 0) == DONE)
    return tasks


class Client:
    def __init__(self, token, base=BASE, calls=None):
        self._token = token
        self._base = base
        self._calls = calls or self._http

    def _http(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self._base + path, data=data, method=method)
        request.add_header("Authorization", "Bearer " + self._token)
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body.strip() else None
        except urllib.error.HTTPError as error:
            raise TickTickError("%s %s -> %d" % (method, path, error.code))
        except OSError as error:
            raise TickTickError("%s %s -> %s" % (method, path, error))

    def resolve_list(self, name, list_id=None):
        """Prefer the id; the name is the guard on it.

        Mirroring machine tasks into the wrong list of somebody's personal task
        manager is the kind of mistake that must fail loudly, so a mismatch
        between the configured id and name is an error, not a fallback.
        """
        projects = self._calls("GET", "/project") or []
        if list_id:
            for project in projects:
                if project.get("id") == list_id:
                    if project.get("name") != name:
                        raise TickTickError(
                            "list id %s is named %r, but the config says %r -- refusing to "
                            "mirror into the wrong list" % (list_id, project.get("name"), name))
                    return list_id
            raise TickTickError("no TickTick list with id %s" % list_id)

        for project in projects:
            if project.get("name") == name:
                return project["id"]
        raise TickTickError(
            "there is no TickTick list named %r. Please create it once by hand "
            "-- this mirror never creates lists itself." % name)

    def read_tasks(self, project_id):
        return tasks_from_payload(self._calls("GET", "/project/%s/data" % project_id) or {})

    def create(self, project_id, item):
        """Returns the new task's id, which the caller records in state.json.

        That id is the only way to restore a task later: once completed, a task
        is invisible to the project-data endpoint (Task 1), so it can never be
        rediscovered by reading TickTick.
        """
        created = self._calls("POST", "/task", {
            "projectId": project_id, "title": item.title,
            "content": item.body, "tags": display_tags(item.tags)})
        return (created or {}).get("id")

    def update(self, project_id, task_id, item):
        """`status: 0` also re-opens a completed task -- measured in Task 1."""
        self._calls("POST", "/task/%s" % task_id,
                    {"id": task_id, "projectId": project_id, "title": item.title,
                     "content": item.body, "tags": display_tags(item.tags), "status": 0})

    def complete(self, project_id, task_id):
        self._calls("POST", "/project/%s/task/%s/complete" % (project_id, task_id))
