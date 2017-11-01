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

from trac.test import EnvironmentStub

from tractags.util import MockReq


class MockReqTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.env.path)

    def test_init(self):
        req = MockReq()
        self.assertTrue(req.args.get('something') is None)
        req = MockReq(authname='user')
        self.assertEqual('user', req.authname)
        self.assertTrue(req.is_authenticated)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(MockReqTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
