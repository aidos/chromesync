from utils import Command, Notification


def reload():
    command = Command('Page.reload', {})
    return command

def reloaded():
    notification = Notification('Page.loadEventFired')
    return notification

