"""Taskboard v1: exact state filtering; baseline for a real MiniMax change."""


def list_tasks(tasks, state=None):
    """Select existing task records without changing their order or contents."""
    if state is None:
        return list(tasks)
    return [task for task in tasks if task["state"] == state]
