import time
import koji
import json
import argparse
import sys
import os
import smtplib
from email.mime.text import MIMEText

import pprint

def set_defaults(config):
    subj_line   = '[brewpoll-OSE]'

    if not 'subj_line' in config:
        config['subj_line'] = subj_line
    config['time_run'] = time.time()

def send_report(config, msg, total_out_of_date):
    time_run = time.strftime("%F %T %Z", time.localtime(config['time_run']))
    subj_line = "%s Report generated %s"%(config['subj_line'], time_run)
    if 0 < total_out_of_date:
        subj_line += " - %d packages out of date!"%total_out_of_date
    payload = MIMEText(msg)
    payload['Subject'] = subj_line
    payload['From'] = config['from_addr']
    payload['To'] = config['dest_addr']
    s = smtplib.SMTP(config['smtp_server'])
    s.sendmail(config['from_addr'], [config['dest_addr']], payload.as_string())
    s.quit()

default_config = '%s/app-root/data/brewpoll.json'%os.environ['HOME']

opt_parser = argparse.ArgumentParser()
opt_parser.add_argument('-d', '--debug', action='store_true', help='Enable debugging output')
opt_parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
# opt_parser.add_argument('-c', '--config', default=default_config, type=argparse.FileType('r'), help='Specify a config file')
opt_parser.add_argument('-c', '--config', type=argparse.FileType('r'), help='Specify a config file')

MIN_WIDTH = 40
MAX_WIDTH = 80

width     = MIN_WIDTH

try:
    opts = opt_parser.parse_args()
except IOError as ee:
    if 2 == ee.errno:
        sys.stderr.write("Could not open configuration file: %s\n"%ee.filename)
        sys.stderr.write(opt_parser.format_usage())
    sys.exit(1)

def verbose(txt):
    if opts.verbose:
        sys.stderr.write("%s\n"%txt)

def debug(txt):
    if opts.debug:
        sys.stderr.write("%s\n"%txt)

def output(txt):
    msg = "%s\n"%txt
    sys.stdout.write(msg)
    return msg

try:
    config = json.load(opts.config)
except AttributeError:
    try:                        # There's gotta be a better way...
        cfg_file = open(default_config, 'r')
        config = json.load(cfg_file)
    except IOError as ee:
        if 2 == ee.errno:
            sys.stderr.write("Could not open configuration file: %s\n"%ee.filename)
            sys.stderr.write(opt_parser.format_usage())
        sys.exit(1)

set_defaults(config)

verbose("Using base url %s"%config['base_url'])

koji_opts    = {'debug': False, 'password': None, 'debug_xmlrpc': False, 'user': None}

# pkg_tag  = 'RHEL-6.4-Z-candidate'
verbose("Opening koji.ClientSession(%s, %s)"%(config['base_url'], koji_opts))

session  = koji.ClientSession(config['base_url'], koji_opts)
verbose("Koji session created")

fmt = "Package: %s%s Build(s): %s"
up_to_date  = {}
out_of_date = {}

local_time = time_run = time.strftime("%F %T %Z", time.localtime(config['time_run']))
gmt_time = time_run = time.strftime("%F %T", time.gmtime(config['time_run']))

report = """\
Report generated at local time: %s
                           GMT: %s

"""%(local_time, gmt_time)

# Check if version-release of upstream build is > version-release of
# cooresponding OSE package
for pkg_tag in config['tags']:
    verbose("Checking package tag %s"%pkg_tag)
    if not up_to_date.has_key(pkg_tag):
        up_to_date[pkg_tag] = []
    if not out_of_date.has_key(pkg_tag):
        out_of_date[pkg_tag] = []
    for pkg_build in config['packages'][pkg_tag]:
    # for arch in ['x86_64', 'noarch']:
        build = pkg_build['upstream_build'][0]
        pkg = pkg_build['our_pkg'][0]
        pkg_nvr = "%s-%s-%s"%tuple(pkg_build['our_pkg'])
        debug("session.getLatestBuilds(%s, %s, %s)"%(pkg_tag, None, build))
        res = session.getLatestBuilds(pkg_tag, None, build)
        if res:
            debug(pprint.pformat(res))
            if not (res[0]['version'] == pkg_build['our_pkg'][1] 
                    and res[0]['release'] == pkg_build['our_pkg'][2]):
                out_of_date[pkg_tag].append([pkg_nvr, res[0]['nvr']])
            else:
                up_to_date[pkg_tag].append([pkg_nvr, res[0]['nvr']])
    debug("up to date:")
    debug(pprint.pformat(up_to_date))
    debug("out of date:")
    debug(pprint.pformat(out_of_date))

total_out_of_date = sum((len(ii) for ii in out_of_date.values()))
report += output("Summary")
report += output("Total out of date:    %d"%total_out_of_date)
width = 2+max((len(ii) for ii in config['tags']))
for pkg_tag in config['tags']:
    report += output("Out of date for tag:  %s:%s %d"%(pkg_tag, ' '*(width - len(pkg_tag)), len(out_of_date[pkg_tag])))
report += output("")
report += output("="*MAX_WIDTH)
report += output("")

for pkg_tag in config['tags']:    
    report += output("Results for tag:      %s"%pkg_tag)
    report += output("Packages checked:     %d"%len(config['packages'][pkg_tag]))
    report += output("Packages in tag:      %d"%(len(up_to_date[pkg_tag]) + len(out_of_date[pkg_tag])))
    report += output("Packages up to date:  %d"%len(up_to_date[pkg_tag]))
    report += output("Packages out of date: %d"%len(out_of_date[pkg_tag]))
    report += output("")
    
    width = max([MIN_WIDTH,
                 width,
                 2+max((len(x[0]) for x in (up_to_date[pkg_tag] + out_of_date[pkg_tag])))])
    debug("width: %d"%width)
    if out_of_date[pkg_tag]:
        report += output("Out of date builds:")
        report += output("-"*MAX_WIDTH)
        for ii in out_of_date[pkg_tag]:
            report += output(fmt%(ii[0], ' '*(width-len(ii[0])), ii[1]))
            # print ii
        report += output("")
    if up_to_date[pkg_tag]:
        report += output("Up to date builds:")
        report += output("-"*MAX_WIDTH)
        for ii in up_to_date[pkg_tag]:
            report += output(fmt%(ii[0], ' '*(width-len(ii[0])), ii[1]))
        report += output("")
    report += output("="*MAX_WIDTH)
    report += output("")

debug(report)
send_report(config, report, total_out_of_date)
