
# ChromeSync
Keep scripts in Google Chrome in sync with your filesystem

You can add feature requests or bugs to https://github.com/aidos/ChromeSync/issues


## Note
This is in very eary stages - use at your own risk. It could totally
kill your cat.

The main gist of the code come from the Sublime Plugin that interfaces
with Chrome. We're using their WIP and websocket code.

This uses inotify which is a linux only api. It's not going to work on any
other platform.


## Install
pip install -r requirements.txt

Edit config.py to add the paths on your local system (make sure your trailing
slashes are the same).


## Run
Start Chrome with the remote debugger
On a mac it's the following (not sure on linux):
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
--remote-debugging-port=9222

    $ ipython
    >>> # At the moment just run for a single tab
    >>> import sync
    >>> cw = sync.ChromeWatch()
    
    >>> # To stop you need to run this before leaving ipython
    >>> # otherwise the threads will hang and you'll have to manually kill
    >>> cw.stop()


## TODO
Handle websocket connections breaking (because someone uses the inspector)

