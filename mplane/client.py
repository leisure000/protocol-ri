#
# mPlane Protocol Reference Implementation
# Simple mPlane client and CLI (JSON over HTTP)
#
# (c) 2013-2014 mPlane Consortium (http://www.ict-mplane.eu)
#               Author: Brian Trammell <brian@trammell.ch>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.
#

import mplane.model
import sys
import cmd
import readline
import urllib.request
import html.parser
import urllib.parse

from datetime import datetime, timedelta

CAPABILITY_PATH_ELEM = "capability"

"""
Generic mPlane client for HTTP component-push workflows.

"""

class CrawlParser(html.parser.HTMLParser):
    """
    HTML parser class to extract all URLS in a href attributes in
    an HTML page. Used to extract links to Capabilities exposed
    as link collections.

    """
    def __init__(self, **kwargs):
        super(CrawlParser, self).__init__(**kwargs)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = {k: v for (k,v) in attrs}
        if tag == "a" and "href" in attrs:
            self.urls.append(attrs["href"])

class HttpClient(object):
    """
    Implements an mPlane HTTP client endpoint for component-push workflows. 
    This client endpoint can retrieve capabilities from a given URL, then post 
    Specifications to the component and retrieve Results or Receipts; it can
    also present Redeptions to retrieve Results.

    Caches retrieved Capabilities, Receipts, and Results.

    """
    def __init__(self, posturl, capurl=None):
        # store urls
        self._posturl = posturl
        if capurl is not None:
            self._capurl = capurl
        else:
            self._capurl = self._posturl
            if self._capurl[-1] != "/":
                self._capurl += "/"
            self._capurl += CAPABILITY_PATH_ELEM

        print("new client: "+self._posturl+" "+self._capurl)

        # empty capability and measurement lists
        self._capabilities = []
        self._receipts = []
        self._results = []

    def get_mplane_reply(self, url=None, postmsg=None):
        """
        Given a URL, parses the object at the URL as an mPlane 
        message and processes it.

        Given a message to POST, sends the message to the given 
        URL and processes the reply as an mPlane message.

        """
        if postmsg is not None:
            if url is None:
                url = self._posturl
            req = urllib.request.Request(url, 
                    data=mplane.model.unparse_json(postmsg).encode("utf-8"),
                    headers={"Content-Type": "application/x-mplane+json"}, 
                    method="POST")
        else:
            req = urllib.request.Request(url)

        with urllib.request.urlopen(req) as res:
            print("get_mplane_reply "+url+" "+str(res.status)+
                  " Content-Type "+res.getheader("Content-Type"))
            if res.status == 200 and \
               res.getheader("Content-Type") == "application/x-mplane+json":
                print("parsing json")
                return mplane.model.parse_json(res.read().decode("utf-8"))
            else:
                print("giving up")
                return None

    def handle_message(self, msg):
        """
        Processes a message. Caches capabilities, receipts, 
        and results, and handles Exceptions.

        """
        print("got message:")
        print(mplane.model.unparse_yaml(msg))

        if isinstance(msg, mplane.model.Capability):
            self.add_capability(msg)
        elif isinstance(msg, mplane.model.Receipt):
            self.add_receipt(msg)
        elif isinstance(msg, mplane.model.Result):
            self.add_result(msg)
        elif isinstance(msg, mplane.model.Exception):
            self._handle_exception(msg)
        else:
            # FIXME do something diagnostic here
            pass

    def capabilities(self):
        """Iterate over capabilities"""
        yield from self._capabilities

    def capability_at(self, index):
        """Retrieve a capability at a given index"""
        return self._capabilities[index]

    def add_capability(self, cap):
        """Add a capability to the capability cache"""
        print("adding "+repr(cap))
        self._capabilities.append(cap)

    def clear_capabilities(self):
        """Clear the capability cache"""
        self._capabilities.clear()

    def retrieve_capabilities(self, listurl=None):
        """
        Given a URL, retrieves an object, parses it as an HTML page, 
        extracts links to capabilities, and retrieves and processes them
        into the capability cache.

        """
        if listurl is None:
            listurl = self._capurl
            self.clear_capabilities()

        print("getting capabilities from "+listurl)
        with urllib.request.urlopen(listurl) as res:
            if res.status == 200:
                parser = CrawlParser(strict=False)
                parser.feed(res.read().decode("utf-8"))
                parser.close()
                for capurl in parser.urls:
                    self.handle_message(
                        self.get_mplane_reply(url=urllib.parse.urljoin(listurl, capurl)))
            else:
                print(listurl+": "+str(res.status))
       
    def receipts(self):
        """Iterate over receipts (pending measurements)"""
        yield from self._receipts

    def add_receipt(self, msg):
        """Add a receipt. Check for duplicates."""
        if msg.get_token() not in [receipt.get_token() for receipt in self.receipts()]:
            self._receipts.append(msg)

    def redeem_receipt(self, msg):
        self.handle_message(self.get_mplane_reply(postmsg=mplane.model.Redemption(receipt=msg)))

    def redeem_receipts(self):
        """
        Send all pending receipts to the Component,
        attempting to retrieve results.

        """
        for receipt in self.receipts():
            self.redeem_receipt(receipt)

    def _delete_receipt_for(self, token):
        self._receipts = list(filter(lambda msg: msg.get_token() != token, self._receipts))

    def results(self):
        """Iterate over receipts (pending measurements)"""
        yield from self._results

    def add_result(self, msg):
        """Add a receipt. Check for duplicates."""
        if msg.get_token() not in [result.get_token() for results in self.results()]:
            self._results.append(msg)
            self._delete_receipt_for(msg.get_token())

    def measurements(self):
        """Iterate over all measurements (receipts and results)"""
        yield from self._results
        yield from self._receipts

    def measurement_at(index):
        """Retrieve a measurement at a given index"""
        if index >= len(self._results):
            index -= len(self._results)
            return self._receipts[index]
        else:
            return self._results[index]

    def _handle_exception(self, exc):
        print(repr(exc))

class ClientShell(cmd.Cmd):

    intro = 'Welcome to the mplane client shell.   Type help or ? to list commands.\n'
    prompt = '|mplane| '

    def preloop(self):
        self._client = None
        self._defaults = {}
        self._when = None

    def do_connect(self, arg):
        """Connect to a probe or supervisor via HTTP and retrieve capabilities"""
        args = arg.split()
        if len(args) >= 2:
            self._client = HttpClient(posturl=args[0], capurl=args[1])
        elif len(args) >= 1:
            self._client = HttpClient(posturl=args[0])
        else:
            print("Cannot connect without a url")

        self._client.retrieve_capabilities()

    def do_listcap(self, arg):
        """List available capabilities by index"""
        for i, cap in enumerate(self._client.capabilities()):
            print ("%4u: %s" % (i, repr(cap)))

    def do_listmeas(self, arg):
        """List running/completed measurements by index"""
        for i, meas in enumerate(self._client.measurements()):
            print ("%4u: %s" % (i, repr(meas)))

    def do_showcap(self, arg):
        """
        Show a capability given a capability index; 
        without an index, shows all capabilities

        """
        if len(arg) > 0:
            try:
                self._show_stmt(self._client.capability_at(int(arg.split()[0])))
            except:
                print("No such capability "+arg)
        else:
            for i, cap in enumerate(self._client.capabilities()):
                print ("cap %4u ---------------------------------------" % i)
                self._show_stmt(cap)

    def do_showmeas(self, arg):
        """Show receipt/results for a measurement, given a measurement index"""
        if len(arg) > 0:
            try:
                self._show_stmt(self._client.measurement_at(int(arg.split()[0])))
            except:
                print("No such measurement "+arg)
        else:
            for i, meas in enumerate(self._client.measurements()):
                print ("meas %4u --------------------------------------" % i)
                self._show_stmt(meas)

    def _show_stmt(self, stmt):
        print(mplane.model.unparse_yaml(stmt))

    def do_runcap(self, arg):
        """
        Run a capability given an index, filling in temporal 
        scope and defaults for parameters. Prompts for parameters 
        not yet entered.

        """
        # Retrieve a capability and create a specification
#        try:
        cap = self._client.capability_at(int(arg.split()[0]))
        spec = mplane.model.Specification(capability=cap)
#        except:
#            print ("No such capability "+arg)
#            return

        # Set temporal scope
        spec.set_when(self._when)

        # Fill in single values
        spec.set_single_values()

        # Fill in parameter values
        for pname in spec.parameter_names():
            if spec.get_parameter_value(pname) is None:
                if pname in self._defaults:
                    # set parameter value from defaults
                    print("|param| "+pname+" = "+self._defaults[pname])
                    spec.set_parameter_value(pname, self._defaults[pname])
                else:
                    # set parameter value with input
                    sys.stdout.write("|param| "+pname+" = ")
                    spec.set_parameter_value(pname, input())
            else:
                # FIXME we really want to unparse this
                print("|param| "+pname+" = "+str(spec.get_parameter_value(pname)))

        # Validate specification
        spec.validate()

        # And send it to the server
        self._client.handle_message(self._client.get_mplane_reply(postmsg=spec))
        print("ok")

    def do_redeem(self, arg):
        """Attempt to redeem all outstanding receipts"""
        self._client.redeem_receipts()
        print("ok")

    def do_show(self, arg):
        """Show a default parameter value, or all values if no parameter name given"""
        if len(arg) > 0:
            try:
                key = arg.split()[0]
                val = self._defaults[key]
                print(key + " = " + val)
            except:
                print("No such default "+key)
        else:
            print("%4u defaults" % len(self._defaults))
            for key, val in self._defaults.items():
                print(key + " = " + val)

    def do_set(self, arg):
        """Set a default parameter value"""
        try:
            sarg = arg.split()
            key = sarg.pop(0)
            val = " ".join(sarg)
            self._defaults[key] = val
            print(key + " = " + val)
        except:
            print("Couldn't set default "+arg)

    def do_when(self, arg):
        """Set a default temporal scope"""
        if len(arg) > 0:
            try:
                self._when = mplane.model.When(arg)
            except:
                print("Invalid temporal scope "+arg)
        else:
            print("when = "+str(self._when))

    def do_unset(self, arg):
        """Unset a default parameter value"""
        try:
            keys = arg.split()
            for key in keys:
                del self._defaults[key]
        except:
            print("Couldn't unset default(s) "+arg)

    def do_EOF(self, arg):
        """Exit the shell by typing ^D"""
        print("Ciao!")
        return True

if __name__ == "__main__":
    mplane.model.initialize_registry()
    ClientShell().cmdloop()
