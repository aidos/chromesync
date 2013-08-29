
"""
ChromeSync - Update Google Chrome with changed files

Copyright (C) 2010 Aidan Kane (aidos)

    This library is free software; you can redistribute it and/or
    modify it under the terms of the GNU Lesser General Public
    License as published by the Free Software Foundation; either
    version 2.1 of the License, or (at your option) any later version.

    This library is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
    Lesser General Public License for more details.

    You should have received a copy of the GNU Lesser General Public
    License along with this library; if not, write to the Free Software
    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""

import logging
import os.path
import threading
import json
import requests
import pyinotify

import websocket
import wip
import wip.Debugger
import config



logging.basicConfig()
logger = logging.getLogger('ChromeSync')
logger.setLevel(logging.INFO)




def get_page_list(port=9222):
    """Find pages in the active brower."""
    tabs = requests.get('http://localhost:%s/json' % port).json()
    pages = [t for t in tabs if t['type'] == 'page']
    return pages



class ChromeWatch():
    """Going to watch over the whole Chrome instance."""

    def __init__(self, port=9222):
        self.port = port
        c = config.Config()
        self.mappings = c.mappings
        self.protocols = dict()

        # create a protocol for every page / tab
        self.pages = get_page_list(self.port)
        for p in self.pages:
            ws = p['webSocketDebuggerUrl']
            self.protocols[ws] = TabWatch(ws, self.mappings)

        # TODO: need to poll Chrome to find new tabs

    def stop(self):
        """You really need to do this to stop things from hanging on exit."""
        for p in self.protocols.values():
            p.stop()




class TabWatch(object):
    """Watch a Tab in the browser. Keep a list of scripts that have
    been parsed and push updates back out."""

    def __init__(self, websocket, url_to_path):
        self.websocket = websocket
        self.url_to_path = url_to_path

        self.protocol = None
        self.file_manager = None
        self.path_to_script = dict()
        self.watching = dict()

        # we need to lock access around state
        self.chrome_lock = threading.RLock()
        self.fs_lock = threading.RLock()

        self.create_chrome_watcher()
        # note: we actually have to watch the directory above the file
        self.create_file_watcher()


    def create_file_watcher(self):
        """Seperate thread to track files being modified."""

        class FileModified(pyinotify.ProcessEvent):
            """Used for tracking files modified in the system."""

            def __init__(self, callback):
                self.callback = callback

            def process_IN_MODIFY(self, event):
                self.callback(event.pathname)

        wm = pyinotify.WatchManager()
        handler = FileModified(self.on_script_modified)
        self.file_notifier = pyinotify.ThreadedNotifier(wm, handler)
        self.file_notifier.start()
        self.file_manager = wm

    def start_watching_script(self, path):
        """Start watching a file for modifications."""

        with self.fs_lock:
            directory = os.path.dirname(path)

            if directory in self.watching:
                # already watching the directory
                watched_paths = self.watching[directory]
                if path not in watched_paths:
                    watched_paths.append(path)
            else:
                self.watching[directory] = [path]
                self.file_manager.add_watch(directory, pyinotify.IN_MODIFY)

    def stop_watching_script(self, path):
        """Stop watching a file for modifications."""

        with self.fs_lock:
            directory = os.path.dirname(path)
            if directory not in self.watching:
                return

            watched_paths = self.watching[directory]
            if path in watched_paths:
                watched_paths.remove(path)

            if len(watched_paths) == 0:
                wd = self.file_manager.get_wd(directory)
                self.file_manager.rm_watch(wd)
                self.watching.remove(directory)

    def clear_all_watches(self):
        with self.fs_lock:
            wm = self.file_manager
            wm.rm_watch(wm.watches.keys())
            self.watching = dict()


    def on_script_modified(self, path):
        """Called whenever a watched script on the filesystem is updated."""

        logger.debug('File Modified: %s' % path)

        # because we're watching a whole directory we'll be notified about
        # files we don't actually want to watch
        directory = os.path.dirname(path)
        with self.fs_lock:
            if directory not in self.watching:
                return
            if path not in self.watching[directory]:
                return

        # TODO: should really have a Queue in here because Chrome may be
        # in a disconnected state at the time (inspector running)

        with self.chrome_lock:
            _, script_id = self.path_to_script[path]
        src = ''
        with open(path) as f:
            src = f.read()

        # TODO: do I need a callback in here...??
        self.protocol.send(wip.Debugger.setScriptSource(script_id, src))


    def create_chrome_watcher(self):
        """Create the websocket connection to Chrome."""

        # TODO: what to do about existing
        if self.protocol:
            self.protocol.disconnect()

        p = Protocol()
        p.subscribe(wip.Debugger.scriptParsed(), self.on_script_parsed)
        p.subscribe(wip.Debugger.globalObjectCleared(), self.on_page_reloaded)
        p.connect(self.websocket, self.on_chrome_connected,
                  self.on_chrome_disconnected)
        self.protocol = p

    def stop(self):
        """Kill off the child threads (watching chrome and watching files)."""

        if self.protocol:
            self.protocol.disconnect()

        self.clear_all_watches()
        if self.file_notifier:
            self.file_notifier.stop()

    def on_chrome_connected(self):
        self.protocol.send(wip.Debugger.enable())

    def on_chrome_disconnected(self):
        # TODO: need to track the disconnect
        # parent will need to reconnect us - can we reuse the same protocol?
        pass

    def on_page_reloaded(self, data, notification):
        """Called from Chrome everytime the page is reloaded."""
        # reset the scripts / watchers
        with self.chrome_lock:
            self.path_to_script = dict()
        self.clear_all_watches()

    def on_script_parsed(self, data, notification):
        """Called from Chrome everytime it parses a new script."""

        url = data['url']
        script_id = data['scriptId'].value

        local_path = self.get_local_path_of_url(url)

        if local_path:
            # TODO: could be two urls mapping to the same local_path
            with self.chrome_lock:
                self.path_to_script[local_path] = (url, script_id)
            self.start_watching_script(local_path)

    def get_local_path_of_url(self, url):
        """Check if the given url is one that we have mapped."""

        longest_common = ''

        with self.chrome_lock:
            paths = self.url_to_path.keys()
            for p in paths:
                common = os.path.commonprefix([p, url])
                if common and len(common) > len(longest_common):
                    longest_common = common

            if longest_common not in self.url_to_path:
                return None

            base = self.url_to_path[longest_common]

            return base + url.replace(longest_common, '')











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

