# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.perm import PermissionCache, PermissionSystem
from trac.test import EnvironmentStub, MockRequest

from tractags.api import TagSystem
from tractags.db import TagSetup
from tractags.xmlrpc import TagRPC


class TagRPCTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()
        setup = TagSetup(self.env)
        # Current tractags schema is partially setup with enabled component.
        #   Revert these changes for getting a clean setup.
        self._revert_tractags_schema_init()
        setup.upgrade_environment()

        self.perms = PermissionSystem(self.env)
        self.tag_s = TagSystem(self.env)

        # Populate table with initial test data.
        self.env.db_transaction("""
            INSERT INTO tags (tagspace, name, tag)
            VALUES ('wiki', 'WikiStart', 'tag1')
            """)

        self.req = MockRequest(self.env, authname='editor')

    def tearDown(self):
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    # Helpers

    def _revert_tractags_schema_init(self):
        with self.env.db_transaction as db:
            db("DROP TABLE IF EXISTS tags")
            db("DROP TABLE IF EXISTS tags_change")
            db("DELETE FROM system WHERE name='tags_version'")
            db("DELETE FROM permission WHERE action %s" % db.like(),
               ('TAGS_%',))

    # Tests

    def test_init(self):
        TagRPC(self.env)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TagRPCTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
