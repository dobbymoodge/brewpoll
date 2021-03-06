import time
import koji
import json
import argparse
import sys
import os
import smtplib
import rpm
from email.mime.text import MIMEText

import pprint

def set_defaults(config):
    subj_line   = '[brewpoll-OSE]'

    if not 'subj_line' in config:
        config['subj_line'] = subj_line
    config['time_run'] = time.time()

def create_subject_line(total_out_of_date, critical_out_of_date):
    time_run = time.strftime("%F %T %Z", time.localtime(config['time_run']))
    subj_line = "%s Report generated %s"%(config['subj_line'], time_run)
    if 0 < total_out_of_date:
        subj_line += " - %d critical packages out of date"%critical_out_of_date
        if 0 < critical_out_of_date:
            subj_line += "! "
        else:
            subj_line += ". "
        subj_line += "(%d total)"%total_out_of_date
    return subj_line

def send_report(config, msg, subj_line):
    time_run = time.strftime("%F %T %Z", time.localtime(config['time_run']))
    debug("Subject: %s" % subj_line)
    debug('From: %s' % config['from_addr'])
    debug('To: %s' % config['dest_addr'])
    debug('')
    if opts.dontsend:
        return
    payload = MIMEText(msg)
    payload['Subject'] = subj_line
    payload['From'] = config['from_addr']
    if isinstance(config['dest_addr'], (str, unicode)):
        payload['To'] = config['dest_addr']
    else:
        payload['To'] = ', '.join(config['dest_addr'])
    s = smtplib.SMTP(config['smtp_server'])
    s.sendmail(config['from_addr'], config['dest_addr'], payload.as_string())
    s.quit()

default_config = '%s/app-root/data/brewpoll.json'%os.environ['HOME']

opt_parser = argparse.ArgumentParser()
opt_parser.add_argument('-d', '--debug', action='store_true', help='Enable debugging output')
opt_parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
# opt_parser.add_argument('-c', '--config', default=default_config, type=argparse.FileType('r'), help='Specify a config file')
opt_parser.add_argument('-c', '--config', type=argparse.FileType('r'), help='Specify a config file')
opt_parser.add_argument('-n', '--dontsend', action='store_true', help="Don't actually send the report via email")

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

fmt             = "Package: %s%s Build(s): %s"
up_to_date      = {}
out_of_date     = {}
non_critical    = {}
blacklist       = {}
upstream_builds = {}
our_builds      = {}
our_pkgnames    = {}
local_time      = time_run = time.strftime("%F %T %Z", time.localtime(config['time_run']))
gmt_time        = time_run = time.strftime("%F %T", time.gmtime(config['time_run']))

report = """\
Report generated at local time: %s
                           GMT: %s

"""%(local_time, gmt_time)

# Check if version-release of upstream build is > version-release of
# cooresponding OSE package
# for pkg_tag in config['tags']:
#     verbose("Checking package tag %s"%pkg_tag)
#     if not up_to_date.has_key(pkg_tag):
#         up_to_date[pkg_tag] = []
#     if not out_of_date.has_key(pkg_tag):
#         out_of_date[pkg_tag] = []
#     for pkg_build in config['packages'][pkg_tag]:
#     # for arch in ['x86_64', 'noarch']:
#         build = pkg_build['upstream_build'][0]
#         pkg = pkg_build['our_pkg'][0]
#         pkg_nvr = "%s-%s-%s"%tuple(pkg_build['our_pkg'])
#         debug("session.getLatestBuilds(%s, %s, %s)"%(pkg_tag, None, build))
#         res = session.getLatestBuilds(pkg_tag, None, build)
#         if res:
#             debug(pprint.pformat(res))
#             our_vr = (None, pkg_build['our_pkg'][1], pkg_build['our_pkg'][2])
#             their_vr = (None, res[0]['version'], res[0]['release'])
#             if rpm.labelCompare(our_vr, their_vr) < 0:
#                 out_of_date[pkg_tag].append([pkg_nvr, res[0]['nvr']])
#             else:
#                 up_to_date[pkg_tag].append([pkg_nvr, res[0]['nvr']])
#     debug("up to date:")
#     debug(pprint.pformat(up_to_date))
#     debug("out of date:")
#     debug(pprint.pformat(out_of_date))


def make_nvr(build):
    return (build['package_name'], build['version'], build['release'])

verbose("Getting list of latest version builds in tag %s and inherited tags"%config['our_tag'])
our_builds = dict([(x['package_name'], x) for x in
                   session.listTagged(config['our_tag'], inherit=True, latest=True)])
verbose("%d builds to be checked from tag %s and inherited tags"%(len(our_builds), config['our_tag']))

for pkg_tag in config['tags']:
    verbose("Checking package tag %s"%pkg_tag)
    # I tried building ublist by querying individual package names,
    # but querying for all packages and filtering is much faster
    ublist = session.listTagged(pkg_tag, inherit=True, latest=True)
    upstream_builds[pkg_tag] = dict([(x['package_name'], x) for x in
                                     ublist if x['package_name'] in our_builds])
    debug("upstream_builds: %s"%(pprint.pformat(upstream_builds)))
    if not up_to_date.has_key(pkg_tag):
        up_to_date[pkg_tag] = []
    if not out_of_date.has_key(pkg_tag):
        out_of_date[pkg_tag] = []
    if not non_critical.has_key(pkg_tag):
        non_critical[pkg_tag] = []
    if not blacklist.has_key(pkg_tag):
        blacklist[pkg_tag] = []
    for pkg_name, build in upstream_builds[pkg_tag].iteritems():
        if rpm.labelCompare(make_nvr(our_builds[pkg_name]),
                            make_nvr(build)) < 0:
            if 'non_critical' in config and pkg_name in config['non_critical']:
                non_critical[pkg_tag].append([our_builds[pkg_name]['nvr'], build['nvr']])
            elif 'blacklist' in config and pkg_name in config['blacklist']:
                blacklist[pkg_tag].append([our_builds[pkg_name]['nvr'], build['nvr']])
                # up_to_date[pkg_tag].append([our_builds[pkg_name]['nvr'], build['nvr']])
            else:
                out_of_date[pkg_tag].append([our_builds[pkg_name]['nvr'], build['nvr']])
        else:
            up_to_date[pkg_tag].append([our_builds[pkg_name]['nvr'], build['nvr']])
    debug("up to date:")
    debug(pprint.pformat(up_to_date))
    debug("out of date:")
    debug(pprint.pformat(out_of_date))
    debug("non-critical:")
    debug(pprint.pformat(non_critical))
    debug("blacklist:")
    debug(pprint.pformat(blacklist))

critical_out_of_date = sum((len(ii) for ii in out_of_date.values()))
total_out_of_date = sum((len(ii) for ii in non_critical.values())) + critical_out_of_date
report += output("Summary")
report += output("Our tag name:                 %s"%config['our_tag'])
report += output("Total packages in our tag:    %d"%len(our_builds))
report += output("Total out of date:            %d"%total_out_of_date)
report += output("Blacklisted:                  %d"%len(blacklist.values()))
width = 2+max((len(ii) for ii in config['tags']))
for pkg_tag in config['tags']:
    non_crit_out=""
    if 0 < len(non_critical[pkg_tag]):
        non_crit_out="(%d non-critical)"%len(non_critical[pkg_tag])
    report += output("Out of date for tag:          %s:%s %d %s" %
                     (pkg_tag,
                      ' '*(width - len(pkg_tag)),
                      len(out_of_date[pkg_tag]),
                      non_crit_out))
report += output("")
report += output("="*MAX_WIDTH)
report += output("")

for pkg_tag in config['tags']:    
    report += output("Results for tag:                      %s"%pkg_tag)
    report += output("Packages matching OSE builds in tag:  %d" %
                     (len(up_to_date[pkg_tag]) + len(out_of_date[pkg_tag]) + len(non_critical[pkg_tag])))
    report += output("Packages up to date:                  %d"%len(up_to_date[pkg_tag]))
    non_crit_out=""
    if 0 < len(non_critical[pkg_tag]):
        non_crit_out="(%d non-critical)"%len(non_critical[pkg_tag])
    report += output("Packages out of date:                 %d %s"%(len(out_of_date[pkg_tag]), non_crit_out))
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
        for ii in non_critical[pkg_tag]:
            report += output(fmt%(ii[0], ' '*(width-len(ii[0])-1)+'*', ii[1]))
        report += output("")
    if up_to_date[pkg_tag] and opts.verbose:
        report += output("Up to date builds:")
        report += output("-"*MAX_WIDTH)
        for ii in up_to_date[pkg_tag]:
            spacer = ' '*((width-len(ii[0])))
            # if ii in non_critical[pkg_tag]:
            #     spacer += '*'
            # else:
            #     spacer += ' '
            utd_out = fmt%(ii[0], spacer, ii[1])
            report += output(utd_out)
        report += output("")
    report += output("="*MAX_WIDTH)
    report += output("")

send_report(config, report, create_subject_line(total_out_of_date, critical_out_of_date))
debug(report)
