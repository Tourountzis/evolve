__author__ = 'james.habben'

evolveVersion = '1.2'

import sys
import argparse
argParser = argparse.ArgumentParser(description='Web interface for Volatility Framework.')
argParser.add_argument('-d', '--dbfolder', help='Optional database location')
argParser.add_argument('-f', '--file', help='RAM dump to analyze')
argParser.add_argument('-l', '--local', help='Restrict webserver to serving \'localhost\' only')
argParser.add_argument('-w', '--webport', help='Port to bind Web Server on', default=8080)
argParser.add_argument('-p', '--profile', help='Memory profile to use with Volatility')
argParser.add_argument('-r', '--run', help='Give a comma separated list of plugins to run on startup')
args = argParser.parse_args()
sys.argv = []

if not args.file:
    #raise BaseException("RAM dump file is required.")
    print "RAM dump file is required."
    exit()

import os
#import volatility
import bottle
import sqlite3
import json
import multiprocessing
import hashlib
#import threading

import volatility.constants as constants
import volatility.registry as registry
import volatility.commands as commands
import volatility.conf as conf
import volatility.obj as obj
#import volatility.plugins.taskmods as taskmods
import volatility.addrspace as addrspace
#import volatility.utils as utils
#import volatility.renderers as render
#import volatility.plugins as plugins

from bottle import route, Bottle, run, request

results = multiprocessing.Queue()

Plugins = dict(plugins=[], hash=0)
def BuildPluginList():
    Plugins['plugins'] = []
    for cmdname in sorted(cmds):
        command = cmds[cmdname]
        if command.is_valid_profile(profile):
            Plugins['plugins'].append({'name':cmdname,'help':command.help(), 'data':0, 'error':''})
    Plugins['hash'] = hash(json.dumps(Plugins['plugins'], sort_keys=True))

def UpdatePluginList():
    con = sqlite3.connect(config.OUTPUT_FILE)
    curs = con.cursor()
    curs.execute("select name from sqlite_master where type = 'table';")
    tables = []
    for tab in curs.fetchall():
        tables.append(tab[0].lower())
    jobs = []
    while not results.empty():
        jobs.append(results.get())
    curs.close()
    con.close()
    for cmdname in Plugins['plugins']:
        if cmdname['data'] == 1 and cmdname['name'] not in tables:
            cmdname['data'] = 0
        if cmdname['error'] == '' and cmdname['data'] != 2 and cmdname['name'] in tables:
            cmdname['data'] = 1
        if cmdname['data'] == 2 and cmdname['name'] in jobs:
            if cmdname['name'] in tables:
                cmdname['data'] = 1
            else:
                cmdname['data'] = 0
    Plugins['hash'] = hash(json.dumps(Plugins['plugins'], sort_keys=True))


config = conf.ConfObject()
registry.PluginImporter()
#config = conf.ConfObject()
registry.register_global_options(config, addrspace.BaseAddressSpace)
registry.register_global_options(config, commands.Command)
config.parse_options(False)

profs = registry.get_plugin_classes(obj.Profile)
if args.profile:
    config.PROFILE = args.profile
else:
    config.PROFILE = "WinXPSP2x86"
if config.PROFILE not in profs:
    #raise BaseException("Invalid profile " + config.PROFILE + " selected")
    print "Invalid profile " + config.PROFILE + " selected"
    exit()

config.LOCATION = "file://" + args.file
config.OUTPUT_FILE = args.file + ".sqlite"
if args.dbfolder:
    print "Hashing input file...",
    config.OUTPUT_FILE = os.path.join(args.dbfolder, hashlib.md5(open(args.file).read()).hexdigest() + ".sqlite")
    print "done"
config.parse_options()
profile = profs[config.PROFILE]()


cmds = registry.get_plugin_classes(commands.Command, lower = True)
BuildPluginList()
UpdatePluginList()

print "Volatility Version: " + constants.VERSION

#test = ""

@route('/')
def index():
    return bottle.static_file('evolve.htm',root='web')

@route('/web/:path#.+#', name='web')
def static(path):
    return bottle.static_file(path, root='web')

@route('/data/plugins')
def ajax_plugins():
    UpdatePluginList()
    return json.dumps(Plugins)

@route('/data/volversion')
def vol_version():
    return constants.VERSION

@route('/data/evolveversion')
def evolve_version():
    return evolveVersion

@route('/data/filepath')
def evolve_version():
    return config.LOCATION

@route('/data/profilename')
def evolve_version():
    return config.PROFILE

@route('/data/view/<name>', method='GET')
@route('/data/view/<name>', method='POST')
def plugin_data(name):
    result = {"columns":[],"data":[]}
    con = sqlite3.connect(config.OUTPUT_FILE)
    if request.method == 'POST' and request.forms.get('query'):
        query = request.forms.get('query')
    else:
        query = "SELECT * FROM " + name
    curs = con.cursor()
    try:
        curs.execute(query)
        result["data"] = curs.fetchall()
        result["columns"] = [i[0] for i in curs.description]
    except Exception as err:
        result["error"] = err.message
    result["name"] = name
    result["query"] = query
    return json.dumps(result)

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

@route('/data2/plugin/<name>')
def plugin_data2(name):
    con = sqlite3.connect(config.OUTPUT_FILE)
    con.row_factory = dict_factory
    cur = con.cursor()
    cur.execute("SELECT * FROM " + name)
    return json.dumps( cur.fetchall())

@route('/run/plugin/<name>')
def run_plugin(name):
    for cmdname in Plugins['plugins']:
        if cmdname['name'] == name:
            cmdname['data'] = 2 # running
    p = multiprocessing.Process(target=run_plugin_process, kwargs=dict(name=name, queue=results,))
    #p.daemon = True
    p.start()
    return

def run_plugin_process(name, queue):
    config.parse_options()
    command = cmds[name](config)
    try:
        calc = command.calculate()
        command.render_sqlite(config.OUTPUT_FILE, calc)
    except Exception as err:
        print name + ": " + err.message
    finally:
        queue.put(name)
    return

if args.run:
    runlist = args.run.split(',')
    for runplug in runlist:
        for plug in Plugins['plugins']:
            if plug['name'] == runplug and plug['data'] == 0:
                plug['data'] = 2 # running
                p = multiprocessing.Process(target=run_plugin_process, kwargs=dict(name=runplug, queue=results,))
                p.daemon = True
                p.start()

app = Bottle()
hostip = '0.0.0.0'
if args.local:
    hostip = '127.0.0.1'
run(host=hostip, port=args.webport)

