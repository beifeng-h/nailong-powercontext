"""Taskboard v2: trim and Unicode-casefold state filters."""


def list_tasks(tasks, state=None):
    """Select existing task records without changing their order or contents."""
    if state is None:
        return list(tasks)

    normalized_state = state.strip().casefold()
    return [task for task in tasks if task["state"] == normalized_state]
