# Copyright 2010-2014 MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test suite for pymongo, bson, and gridfs.
"""

import os
import sys
if sys.version_info[:2] == (2, 6):
    import unittest2 as unittest
    from unittest2 import SkipTest
else:
    import unittest
    from unittest import SkipTest
import warnings

from functools import wraps

import pymongo

from bson.py3compat import _unicode
from test.version import Version

# hostnames retrieved by MongoReplicaSetClient from isMaster will be of unicode
# type in Python 2, so ensure these hostnames are unicodes, too. It makes tests
# like `test_repr` predictable.
host = _unicode(os.environ.get("DB_IP", 'localhost'))
port = int(os.environ.get("DB_PORT", 27017))
pair = '%s:%d' % (host, port)

host2 = _unicode(os.environ.get("DB_IP2", 'localhost'))
port2 = int(os.environ.get("DB_PORT2", 27018))

host3 = _unicode(os.environ.get("DB_IP3", 'localhost'))
port3 = int(os.environ.get("DB_PORT3", 27019))


class ClientContext(object):

    def __init__(self):
        """Create a client and grab essential information from the server."""
        try:
            self.client = pymongo.MongoClient(host, port)
        except pymongo.errors.ConnectionFailure:
            self.client = None
        else:
            self.ismaster = self.client.admin.command('ismaster')
            self.w = len(self.ismaster.get("hosts", [])) or 1
            self.setname = self.ismaster.get('setName', '')
            self.rs_client = None
            if self.setname:
                self.rs_client = pymongo.MongoReplicaSetClient(
                    pair, replicaSet=self.setname)
            self.cmd_line = self.client.admin.command('getCmdLineOpts')
            self.version = Version.from_client(self.client)
            self.auth_enabled = self._server_started_with_auth()
            self.test_commands_enabled = ('testCommandsEnabled=1'
                                          in self.cmd_line['argv'])
            self.is_mongos = (self.ismaster.get('msg') == 'isdbgrid')

    def _server_started_with_auth(self):
        # MongoDB >= 2.0
        if 'parsed' in self.cmd_line:
            parsed = self.cmd_line['parsed']
            # MongoDB >= 2.6
            if 'security' in parsed:
                security = parsed['security']
                # >= rc3
                if 'authorization' in security:
                    return security['authorization'] == 'enabled'
                # < rc3
                return (security.get('auth', False) or
                        bool(security.get('keyFile')))
            return parsed.get('auth', False) or bool(parsed.get('keyFile'))
        # Legacy
        argv = self.cmd_line['argv']
        return '--auth' in argv or '--keyFile' in argv

    def _require(self, condition, msg, func=None):
        def make_wrapper(f):
            @wraps(f)
            def wrap(*args, **kwargs):
                if condition:
                    return f(*args, **kwargs)
                raise SkipTest(msg)
            return wrap

        if func is None:
            def decorate(f):
                return make_wrapper(f)
            return decorate
        return make_wrapper(func)

    def require_version_min(self, *ver):
        """Run a test only if the server version is at least ``version``."""
        other_version = Version(*ver)
        return self._require(self.version >= other_version,
                             "Server version must be at least %s"
                             % str(other_version))

    def require_version_max(self, *ver):
        """Run a test only if the server version is at most ``version``."""
        other_version = Version(*ver)
        return self._require(self.version <= other_version,
                             "Server version must be at most %s"
                             % str(other_version))

    def require_auth(self, func):
        """Run a test only if the server is running with auth enabled."""
        return self.check_auth_with_sharding(
            self._require(self.auth_enabled,
                          "Authentication is not enabled on the server",
                          func=func))

    def require_replica_set(self, func):
        """Run a test only if the client is connected to a replica set."""
        return self._require(self.rs_client is not None,
                             "Not connected to a replica set",
                             func=func)

    def require_no_mongos(self, func):
        """Run a test only if the client is not connected to a mongos."""
        return self._require(not self.is_mongos,
                             "Must be connected to a mongod, not a mongos",
                             func=func)

    def check_auth_with_sharding(self, func):
        """Skip a test when connected to mongos < 2.0 and running with auth."""
        condition = not (self.auth_enabled and
                         self.is_mongos and self.version < (2,))
        return self._require(condition,
                             "Auth with sharding requires MongoDB >= 2.0.0",
                             func=func)

    def require_test_commands(self, func):
        """Run a test only if the server has test commands enabled."""
        return self._require(self.test_commands_enabled,
                             "Test commands must be enabled",
                             func=func)


# Reusable client context
client_context = ClientContext()


def setup():
    warnings.resetwarnings()
    warnings.simplefilter("always")


def teardown():
    try:
        c = pymongo.MongoClient(host, port)
    except pymongo.errors.ConnectionFailure:
        # Tests where ssl=True can cause connection failures here.
        # Ignore and continue.
        return

    c.drop_database("pymongo-pooling-tests")
    c.drop_database("pymongo_test")
    c.drop_database("pymongo_test1")
    c.drop_database("pymongo_test2")
    c.drop_database("pymongo_test_mike")
    c.drop_database("pymongo_test_bernie")


class PymongoTestRunner(unittest.TextTestRunner):
    def run(self, test):
        setup()
        result = super(PymongoTestRunner, self).run(test)
        try:
            teardown()
        finally:
            return result
