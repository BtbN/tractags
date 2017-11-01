# -*- coding: utf-8 -*-
#
# Copyright (C) 2011 Odd Simon Simonsen <oddsimons@gmail.com>
# Copyright (C) 2012-2014 Steffen Hoffmann <hoff.st@web.de>
# Copyright (C) 2014 Jun Omae <jun66j5@gmail.com>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.perm import PermissionError, PermissionSystem
from trac.resource import Resource, ResourceNotFound
from trac.test import EnvironmentStub, MockRequest
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

        setup = TagSetup(self.env)
        # Current tractags schema is setup with enabled component anyway.
        #   Revert these changes for getting default permissions inserted.
        self._revert_tractags_schema_init()
        setup.upgrade_environment()

        self.provider = TicketTagProvider(self.env)
        self.realm = 'ticket'
        self.tag_sys = TagSystem(self.env)
        self.tags = ['tag1', 'tag2']

        # Populate tables with initial test data.
        self._create_ticket(self.tags)

    def tearDown(self):
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    # Helpers

    def _create_ticket(self, tags, **kwargs):
        ticket = Ticket(self.env)
        ticket['keywords'] = u' '.join(sorted(map(to_unicode, tags)))
        ticket['summary'] = 'summary'
        ticket['reporter'] = 'admin'
        for name, value in kwargs.iteritems():
            ticket[name] = value
        ticket.insert()
        return ticket

    def _revert_tractags_schema_init(self):
        with self.env.db_transaction as db:
            db("DROP TABLE IF EXISTS tags")
            db("DROP TABLE IF EXISTS tags_change")
            db("DELETE FROM system WHERE name='tags_version'")
            db("DELETE FROM permission WHERE action %s" % db.like(),
               ('TAGS_%',))

    def _tags(self):
        tags = {}
        for name, tag in self.env.db_query("""
                SELECT name,tag FROM tags
                """):
            if name in tags:
                tags[name].add(tag)
            else:
                tags[name] = set([tag])
        return tags

    # Tests

    def test_get_tagged_resources(self):
        # No tags, no restrictions, all resources.
        req = MockRequest(self.env, authname='editor')
        self.assertEquals(
            [r for r in
             self.provider.get_tagged_resources(req, None)][0][1],
            set(self.tags))
        # Force fine-grained perm-check check for all tags, not just the one
        # from query.
        self.provider.fast_permcheck = False
        self.assertEquals(
            [r for r in
             self.provider.get_tagged_resources(req,
                                                set(self.tags[:1]))][0][1],
            set(self.tags))

    def test_get_tags(self):
        req = MockRequest(self.env, authname='editor')
        resource = Resource('ticket', 2)
        self.assertRaises(ResourceNotFound, self.provider.get_resource_tags,
                          req, resource)
        self._create_ticket(self.tags)
        self.assertEquals(
            [tag for tag in
             self.provider.get_resource_tags(req, resource)], self.tags)

    def test_set_tags(self):
        req = MockRequest(self.env, authname='editor')
        tags = ['tag3']
        ticket = Ticket(self.env, 1)
        ticket['keywords'] = tags[0]
        # Tags get updated by TicketChangeListener method.
        ticket.save_changes(req.authname)
        self.assertEquals(self.tag_sys.get_all_tags(req).keys(), tags)

    def test_remove_tags(self):
        req = MockRequest(self.env, authname='editor')
        anon_req = MockRequest(self.env, authname='anonymous')
        resource = Resource('ticket', 1)
        # Anonymous lacks required permissions.
        self.assertRaises(PermissionError, self.provider.remove_resource_tags,
                          anon_req, resource)
        # Shouldn't raise an error with appropriate permission.
        self.provider.remove_resource_tags(req, resource, 'comment')
        ticket = Ticket(self.env, 1)
        self.assertEquals(ticket['keywords'], '')

    def test_describe_tagged_resource(self):
        req = MockRequest(self.env, authname='editor')
        resource = Resource('ticket', 1)
        self.assertEquals(
            self.provider.describe_tagged_resource(req, resource),
            'defect: summary')

    def test_create_ticket_by_anonymous(self):
        req = MockRequest(self.env, authname='editor')
        ticket = self._create_ticket(self.tags, reporter='anonymous')
        tags = self.provider.get_resource_tags(req, ticket.resource)
        self.assertEquals(tags, set(self.tags))

    def test_update_ticket_by_anonymous(self):
        req = MockRequest(self.env, authname='editor')
        ticket = self._create_ticket([])
        tags = self.provider.get_resource_tags(req, ticket.resource)
        self.assertEquals(tags, set([]))

        ticket['keywords'] = ', '.join(self.tags)
        ticket.save_changes('anonymous', comment='Adding keywords')
        tags = self.provider.get_resource_tags(req, ticket.resource)
        self.assertEquals(tags, set(self.tags))


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TicketTagProviderTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
