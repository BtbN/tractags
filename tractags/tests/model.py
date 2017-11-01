# -*- coding: utf-8 -*-
#
# Copyright (C) 2012,2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.perm import PermissionCache, PermissionSystem
from trac.resource import Resource
from trac.test import EnvironmentStub, MockRequest

from tractags.db import TagSetup
from tractags.model import resource_tags, tag_resource, tagged_resources
from tractags.wiki import WikiTagProvider


class TagModelTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()
        self.perms = PermissionSystem(self.env)
        self.req = MockRequest(self.env, authname='editor')

        self.check_perm = WikiTagProvider(self.env).check_permission
        setup = TagSetup(self.env)
        # Current tractags schema is setup with enabled component anyway.
        #   Revert these changes for getting default permissions inserted.
        self._revert_tractags_schema_init()
        setup.upgrade_environment()

        # Populate table with initial test data.
        self.env.db_transaction("""
            INSERT INTO tags (tagspace, name, tag)
            VALUES ('wiki', 'WikiStart', 'tag1')
            """)
        self.realm = 'wiki'

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

    def test_get_tags(self):
        resource = Resource(self.realm, 'WikiStart')
        self.assertEquals([tag for tag in resource_tags(self.env, resource)],
                          ['tag1'])

    def test_get_tagged_resource_no_perm(self):
        self.perms.revoke_permission('anonymous', 'WIKI_VIEW')
        perm = PermissionCache(self.env)
        tags = set(['tag1'])
        # Don't yield resource without permission - 'WIKI_VIEW' here.
        self.assertEqual([(res, tags) for res, tags
                          in tagged_resources(self.env, self.check_perm, perm,
                                              self.realm, tags)], [])

    def test_get_tagged_resource(self):
        perm = PermissionCache(self.env)
        resource = Resource(self.realm, 'WikiStart')
        tags = set(['tag1'])
        self.assertEqual([(res, tags) for res, tags
                          in tagged_resources(self.env, self.check_perm, perm,
                                              self.realm, tags)],
                         [(resource, tags)])

    def test_reparent(self):
        resource = Resource(self.realm, 'TaggedPage')
        old_name = 'WikiStart'
        tag_resource(self.env, resource, 'WikiStart', self.req.authname)
        self.assertEquals(dict(TaggedPage=set(['tag1'])), self._tags())

    def test_tag_changes(self):
        # Add previously untagged resource.
        resource = Resource(self.realm, 'TaggedPage')
        tags = set(['tag1'])
        tag_resource(self.env, resource, author=self.req.authname, tags=tags)
        self.assertEquals(dict(TaggedPage=tags, WikiStart=tags), self._tags())
        # Add new tag to already tagged resource.
        resource = Resource(self.realm, 'WikiStart')
        tags = set(['tag1', 'tag2'])
        tag_resource(self.env, resource, author=self.req.authname, tags=tags)
        self.assertEquals(dict(TaggedPage=set(['tag1']), WikiStart=tags),
                          self._tags())
        # Exchange tags for already tagged resource.
        tags = set(['tag1', 'tag3'])
        tag_resource(self.env, resource, author=self.req.authname, tags=tags)
        self.assertEquals(dict(TaggedPage=set(['tag1']), WikiStart=tags),
                          self._tags())
        # Delete a subset of tags for already tagged resource.
        tags = set(['tag3'])
        tag_resource(self.env, resource, author=self.req.authname, tags=tags)
        self.assertEquals(dict(TaggedPage=set(['tag1']), WikiStart=tags),
                          self._tags())
        # Empty tag iterable deletes all resource tag references.
        tags = tuple()
        tag_resource(self.env, resource, author=self.req.authname, tags=tags)
        self.assertEquals(dict(TaggedPage=set(['tag1'])), self._tags())


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TagModelTestCase))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
