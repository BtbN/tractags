# -*- coding: utf-8 -*-
#
# Copyright (C) 2011 Odd Simon Simonsen <oddsimons@gmail.com>
# Copyright (C) 2012,2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.util.compat import sorted
from trac.perm import PermissionCache, PermissionError, PermissionSystem
from trac.resource import Resource, ResourceNotFound
from trac.test import EnvironmentStub, Mock
from trac.ticket.model import Ticket
from trac.util.text import to_unicode

from tractags.api import TagSystem
from tractags.db import TagSetup
from tractags.ticket import TicketTagProvider


class TicketTagProviderTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()
        self.perms = PermissionSystem(self.env)

        self.db = self.env.get_db_cnx()
        setup = TagSetup(self.env)
        # Current tractags schema is setup with enabled component anyway.
        #   Revert these changes for getting default permissions inserted.
        self._revert_tractags_schema_init()
        setup.upgrade_environment(self.db)

        self.provider = TicketTagProvider(self.env)
        self.realm = 'ticket'
        self.tag_sys = TagSystem(self.env)
        self.tags = ['tag1', 'tag2']

        cursor = self.db.cursor()
        # Populate tables with initial test data.
        self._create_ticket(self.tags)

        # Mock an anonymous request.
        self.anon_req = Mock()
        self.anon_req.perm = PermissionCache(self.env)

        self.req = Mock(authname='editor')
        self.req.authname = 'editor'
        self.req.perm = PermissionCache(self.env, username='editor')

    def tearDown(self):
        self.db.close()
        # Really close db connections.
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    # Helpers

    def _create_ticket(self, tags):
        ticket = Ticket(self.env)
        ticket['keywords'] = u' '.join(sorted(map(to_unicode, tags)))
        ticket['summary'] = 'summary'
        ticket.insert()

    def _revert_tractags_schema_init(self):
        cursor = self.db.cursor()
        cursor.execute("DROP TABLE IF EXISTS tags")
        cursor.execute("DROP TABLE IF EXISTS tags_change")
        cursor.execute("DELETE FROM system WHERE name='tags_version'")
        cursor.execute("DELETE FROM permission WHERE action %s"
                       % self.db.like(), ('TAGS_%',))

    def _tags(self):
        tags = {}
        cursor = self.db.cursor()
        cursor.execute("SELECT name,tag FROM tags")
        for name, tag in cursor:
            if name in tags:
                tags[name].add(tag)
            else:
                tags[name] = set([tag])
        return tags

    # Tests

    def test_get_tagged_resources(self):
        # No tags, no restrictions, all resources.
        self.assertEquals(
            [r for r in
             self.provider.get_tagged_resources(self.req, None)][0][1],
            set(self.tags))
        # Force fine-grained perm-check check for all tags, not just the one
        # from query.
        self.provider.fast_permcheck = False
        self.assertEquals(
            [r for r in
             self.provider.get_tagged_resources(self.req,
                                                set(self.tags[:1]))][0][1],
            set(self.tags))

    def test_get_tags(self):
        resource = Resource('ticket', 2)
        self.assertRaises(ResourceNotFound, self.provider.get_resource_tags,
                          self.req, resource)
        self._create_ticket(self.tags)
        self.assertEquals(
            [tag for tag in
             self.provider.get_resource_tags(self.req, resource)], self.tags)
        #ignore_closed_tickets

    def test_set_tags(self):
        tags = ['tag3']
        ticket = Ticket(self.env, 1)
        ticket['keywords'] = tags[0]
        # Tags get updated by TicketChangeListener method.
        ticket.save_changes(self.req.authname)
        self.assertEquals(self.tag_sys.get_all_tags(self.req).keys(), tags)

    def test_remove_tags(self):
        resource = Resource('ticket', 1)
        # Anonymous lacks required permissions.
        self.assertRaises(PermissionError, self.provider.remove_resource_tags,
                          self.anon_req, resource)
        # Shouldn't raise an error with appropriate permission.
        self.provider.remove_resource_tags(self.req, resource, 'comment')
        ticket = Ticket(self.env, 1)
        self.assertEquals(ticket['keywords'], '')

    def test_describe_tagged_resource(self):
        resource = Resource('ticket', 1)
        self.assertEquals(
            self.provider.describe_tagged_resource(self.req, resource),
            'defect: summary')


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TicketTagProviderTestCase, 'test'))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
