
"""

This code comes from Sublime Web Inspector (SWI)

https://github.com/sokolovstas/SublimeWebInspector

"""

import logging
import os.path
import threading
import json

import websocket
import wip
import wip.Debugger




# Define protocol to communicate with remote debugger by web sockets
class Protocol(object):

    def __init__(self):
        self.next_id = 0
        self.commands = {}
        self.notifications = {}
        self.last_log_object = None

    def connect(self, url, on_open=None, on_close=None):
        logger.debug('SWI: Connecting to ' + url)
        websocket.enableTrace(False)
        self.last_break = None
        self.last_log_object = None
        self.url = url
        self.on_open = on_open
        self.on_close = on_close
        thread = threading.Thread(target=self.thread_callback)
        thread.start()

    def disconnect(self):
        logger.debug('SWI: Disconnecting')
        self.socket.close()

    # start connect with new thread
    def thread_callback(self):
        logger.debug('SWI: Thread started')
        self.socket = websocket.WebSocketApp(self.url, on_message=self.message_callback, on_open=self.open_callback, on_close=self.close_callback)
        self.socket.run_forever()
        logger.debug('SWI: Thread stopped')

    # send command and increment command counter
    def send(self, command, callback=None, options=None):
        command.id = self.next_id
        command.callback = callback
        command.options = options
        self.commands[command.id] = command
        self.next_id += 1
        logger.debug('SWI: ' + json.dumps(command.request))
        self.socket.send(json.dumps(command.request))

    # subscribe to notification with callback
    def subscribe(self, notification, callback):
        notification.callback = callback
        self.notifications[notification.name] = notification

    # unsubscribe
    def unsubscribe(self, notification):
        del self.notifications[notification.name]

    # unsubscribe
    def message_callback(self, ws, message):
        parsed = json.loads(message)
        logger.debug('SWI: <<- %s\n' % message)

        if 'method' in parsed:
            if parsed['method'] in self.notifications:
                notification = self.notifications[parsed['method']]
                if 'params' in parsed:
                    data = notification.parser(parsed['params'])
                else:
                    data = None
                notification.callback(data, notification)
            # else:
                # print 'SWI: New unsubscribe notification --- ' + parsed['method']
        else:
            if parsed['id'] in self.commands:
                command = self.commands[parsed['id']]
                if 'error' in parsed:
                    sublime.set_timeout(lambda: sublime.error_message(parsed['error']['message']), 0)
                else:
                    if 'result' in parsed:
                        command.data = command.parser(parsed['result'])
                    else:
                        command.data = None
                    if command.callback:
                        command.callback(command)
            # print 'SWI: Command response with ID ' + str(parsed['id'])

    def open_callback(self, ws):
        if self.on_open:
            self.on_open()
        logger.debug('SWI: WebSocket opened')

    def close_callback(self, ws):
        if self.on_close:
            self.on_close()
        logger.debug('SWI: WebSocket closed')

