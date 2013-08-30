
"""
ChromeSync - Update Google Chrome with changed files

Copyright (C) 2013 Aidan Kane (aidos)

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
from swi import Protocol


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
        self.protocol_lock = threading.RLock()

        self.watch_chrome = True
        self.poll_timer = None
        self.poll_for_pages()

    def poll_for_pages(self):
        """Called periodically - finds news pages/tabs in Chrome."""

        if not self.watch_chrome:
            return

        # create a protocol for every page / tab
        pages = get_page_list(self.port)
        for p in pages:
            if 'webSocketDebuggerUrl' in p:
                ws = p['webSocketDebuggerUrl']
                with self.protocol_lock:
                    if ws not in self.protocols:
                        self.protocols[ws] = TabWatch(ws, self.mappings)

        self.poll_timer = threading.Timer(5.0, self.poll_for_pages)
        self.poll_timer.start()

    def stop(self):
        """You really need to do this to stop things from hanging on exit."""

        self.watch_chrome = False
        if self.poll_timer:
            self.poll_timer.cancel()

        with self.protocol_lock:
            for p in self.protocols.values():
                p.stop()
            p = dict()




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

        # by default we reconnect to Chrome if we los the connection
        self.keep_alive = True
        self.timer_reconnect = None

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

        logger.info('File Modified: %s' % path)

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
        self.protocol = p

        self.protocol_connect()

    def protocol_connect(self):
        self.protocol.connect(self.websocket, self.on_chrome_connected,
                              self.on_chrome_disconnected)

    def stop(self):
        """Kill off the child threads (watching chrome and watching files)."""

        self.keep_alive = False

        if self.timer_reconnect:
            self.timer_reconnect.cancel()

        if self.protocol:
            self.protocol.disconnect()

        self.clear_all_watches()
        if self.file_notifier:
            self.file_notifier.stop()

    def on_chrome_connected(self):
        """Connected to Chrome - make sure it's sending us debug info."""
        self.protocol.send(wip.Debugger.enable())

    def on_chrome_disconnected(self):
        """Our job is to keep the connection to Chrome alive."""

        if not self.keep_alive:
            return

        def attempt_reconnect():
            self.protocol_connect()
        self.timer_reconnect = threading.Timer(2.0, attempt_reconnect)
        self.timer_reconnect.start()

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

