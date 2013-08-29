
# Chrome Sync
Keep scripts in Google Chrome in sync with your filesystem. Uses the Chrome
Remote Debugger to check which scripts are in use in the browser and to
update them when the files change.

It's great for those of us who are doing a lot of frontend work. I built it for
my AngularJS projects.

Bug reports to https://github.com/aidos/ChromeSync/issues


## Note
This is in very eary stages - use at your own risk. It could totally
kill your cat. I only just got it working and have barely tested it - there
are bound to be a million issues.

The Chrome interfacing code comes from the Sublime Plugin. We're using their
WIP and websocket code. Do whatever you want with the rest of the code.

This uses inotify which is a linux only api. It's not going to work on any
other platform (without a lot more work).


## Install
pip install -r requirements.txt

Edit config.py to add the paths on your local system (make sure your trailing
slashes are the same).


## Run
Start Chrome with the remote debugger (I run on a virtual machine by
tunnelling the debugger traffic).

On a mac it's the following (not sure on linux):

    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=2100

    ssh -R 2100:localhost:9222 up

    $ ipython
    >>> import sync
    >>> cw = sync.ChromeWatch(2100)
    
    >>> # To stop you need to run this before leaving ipython
    >>> # otherwise the threads will hang and you'll have to manually kill
    >>> cw.stop()


## TODO
Handle websocket connections breaking (because someone uses the inspector)
Watch Chrome for new tabs / tabs closing
Multiple urls could map to the same file (not handled at the moment)

