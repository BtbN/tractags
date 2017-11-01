# -*- coding: utf-8 -*-
#
# Copyright (C) 2011 Odd Simon Simonsen <oddsimons@gmail.com>
# Copyright (C) 2012-2014 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.perm import PermissionError, PermissionSystem
from trac.resource import Resource
from trac.test import EnvironmentStub, MockRequest
from trac.wiki.test import wikisyntax_test_suite

from tractags.api import TagSystem
from tractags.db import TagSetup
from tractags.wiki import WikiTagProvider


def _revert_tractags_schema_init(env):
    with env.db_transaction as db:
        db("DROP TABLE IF EXISTS tags")
        db("DROP TABLE IF EXISTS tags_change")
        db("DELETE FROM system WHERE name='tags_version'")
        db("DELETE FROM permission WHERE action %s" % db.like(),
           ('TAGS_%',))


def _insert_tags(env, tagspace, name, tags):
    args = [(tagspace, name, tag) for tag in tags]
    with env.db_transaction as db:
        db.executemany("""
            INSERT INTO tags (tagspace,name,tag) VALUES (%s,%s,%s)
            """, args)


TEST_NOPERM = u"""
============================== link rendering without view permission
tag:onetag
------------------------------
<p>
<a href="/tags/onetag">tag:onetag</a>
</p>
------------------------------
"""

TEST_CASES = u"""
============================== tag: link resolver for single tag
tag:onetag
tag:2ndtag n' more
tag:a.really?_\wild-thing!
# regression test for ticket !#9057
tag:single'quote
------------------------------
<p>
<a href="/tags/onetag">tag:onetag</a>
<a href="/tags/2ndtag">tag:2ndtag</a> n' more
<a href="/tags/a.really%3F_%5Cwild-thing">tag:a.really?_\wild-thing</a>!
# regression test for ticket #9057
<a href="/tags/single\'quote">tag:single\'quote</a>
</p>
------------------------------
============================== tagged: alternative link markup
tagged:onetag
tagged:tagged:
------------------------------
<p>
<a href="/tags/onetag">tagged:onetag</a>
<a href="/tags/tagged">tagged:tagged</a>:
</p>
------------------------------
============================== tag extraction from tag links
# Trailing non-letter character must be ignored.
tag:onetag,
tag:onetag.
tag:onetag;
tag:onetag:
tag:onetag!
tag:onetag?
# Multiple trailing non-letter characters should be removed too.
tag:onetag..
tag:onetag...
------------------------------
<p>
# Trailing non-letter character must be ignored.
<a href="/tags/onetag">tag:onetag</a>,
<a href="/tags/onetag">tag:onetag</a>.
<a href="/tags/onetag">tag:onetag</a>;
<a href="/tags/onetag">tag:onetag</a>:
<a href="/tags/onetag">tag:onetag</a>!
<a href="/tags/onetag">tag:onetag</a>?
# Multiple trailing non-letter characters should be removed too.
<a href="/tags/onetag">tag:onetag</a>..
<a href="/tags/onetag">tag:onetag</a>...
</p>
------------------------------
============================== bracketed TracWiki tag links
[tagged:onetag]
[tag:onetag label]
[tag:onetag multi-word tag: label]
[tag:onetag   surrounding  whitespace stripped ]
[tag:' onetag  '  " 'surrounding  whitespace stripped '"]
# Trailing non-letter character
moved to [tag:'onetag'. label] too, if quoted
![tag:disabled link]
------------------------------
<p>
<a href="/tags/onetag">onetag</a>
<a href="/tags/onetag">label</a>
<a href="/tags/onetag">multi-word tag: label</a>
<a href="/tags/onetag">surrounding  whitespace stripped</a>
<a href="/tags/onetag">surrounding  whitespace stripped</a>
# Trailing non-letter character
moved to <a href="/tags/onetag">. label</a> too, if quoted
[tag:disabled link]
</p>
------------------------------
============================== link to non-existent tag
tag:missing
[tag:missing]
[tag:missing wanted tag]
------------------------------
<p>
<a class="missing tags" href="/tags/missing" rel="nofollow">tag:missing?</a>
<a class="missing tags" href="/tags/missing" rel="nofollow">missing?</a>
<a class="missing tags" href="/tags/missing" rel="nofollow">wanted tag?</a>
</p>
------------------------------
============================== quoting in tag link resolver
tagged:'onetag'
tag:'"heavily-quoted"'
------------------------------
<p>
<a href="/tags/onetag">tagged:'onetag'</a>
<a href="/tags/heavily-quoted">tag:'"heavily-quoted"'</a>
</p>
------------------------------
============================== query expression in tag: link resolver
tag:'onetag 2ndtag'
tag:"onetag 2ndtag"
------------------------------
<p>
<a href="/tags/onetag%202ndtag">tag:\'onetag 2ndtag\'</a>
<a href="/tags/onetag%202ndtag">tag:\"onetag 2ndtag\"</a>
</p>
------------------------------
============================== query with realm in tag: link resolver
tag:'onetag realm:wiki 2ndtag'
[tagged:'realm:wiki onetag' label]
------------------------------
<p>
<a href="/tags?wiki=on&amp;q=onetag+2ndtag">tag:\'onetag realm:wiki 2ndtag\'</a>
<a href="/tags?wiki=on&amp;q=onetag">label</a>
</p>
------------------------------
============================== tag links in complex wiki markup
Linking to a list of resources [tagged with onetag] requires valid syntax
to get [tagged:onetag rendered].
Some [tag:"onetag or single'quote "wir]edly"'
[labeled tag] wiki link is still allowed.
------------------------------
<p>
Linking to a list of resources [tagged with onetag] requires valid syntax
to get <a href="/tags/onetag">rendered</a>.
Some <a href="/tags/onetag%20or%20single'quote">wir</a>edly"'
[labeled tag] wiki link is still allowed.
</p>
------------------------------
"""


class WikiTagProviderTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   path=tempfile.mkdtemp(),
                                   enable=['trac.*', 'tractags.*'])
        setup = TagSetup(self.env)
        # Current tractags schema is partially setup with enabled component.
        #   Revert these changes for getting a clean setup.
        self._revert_tractags_schema_init()
        setup.upgrade_environment()

        self.perms = PermissionSystem(self.env)
        self.tag_s = TagSystem(self.env)
        self.tag_wp = WikiTagProvider(self.env)

        # Populate table with initial test data.
        self.env.db_transaction("""
            INSERT INTO tags (tagspace, name, tag)
            VALUES ('wiki', 'WikiStart', 'tag1')
            """)

        self.realm = 'wiki'
        self.tags = ['tag1']

    def tearDown(self):
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    # Helpers

    def _revert_tractags_schema_init(self):
        _revert_tractags_schema_init(self.env)

    # Tests

    def test_get_tags(self):
        resource = Resource('wiki', 'WikiStart')
        req = MockRequest(self.env, authname='editor')
        self.assertEquals([tag for tag in
                           self.tag_wp.get_resource_tags(req, resource)],
                          self.tags)

    def test_exclude_template_tags(self):
        # Populate table with more test data.
        req = MockRequest(self.env, authname='editor')
        self.env.db_transaction("""
            INSERT INTO tags (tagspace, name, tag)
            VALUES ('wiki', 'PageTemplates/Template', 'tag2')
            """)
        tags = ['tag1', 'tag2']
        self.assertEquals(self.tag_s.get_all_tags(req).keys(), self.tags)
        self.env.config.set('tags', 'query_exclude_wiki_templates', False)
        self.assertEquals(self.tag_s.get_all_tags(req).keys(), tags)

    def test_set_tags_no_perms(self):
        resource = Resource('wiki', 'TaggedPage')
        req = MockRequest(self.env, authname='anonymous')
        self.assertRaises(PermissionError, self.tag_wp.set_resource_tags,
                          req, resource, self.tags)

    def test_set_tags(self):
        resource = Resource('wiki', 'TaggedPage')
        req = MockRequest(self.env, authname='editor')
        # Shouldn't raise an error with appropriate permission.
        self.tag_wp.set_resource_tags(req, resource, self.tags)
        self.tag_wp.set_resource_tags(req, resource, ['tag2'])
        # Check change records.
        rows = self.env.db_query("""
            SELECT author,oldtags,newtags FROM tags_change
            WHERE tagspace=%s AND name=%s
            ORDER by time DESC
            """, ('wiki', 'TaggedPage'))
        self.assertEqual(rows[0], ('editor', 'tag1', 'tag2'))
        self.assertEqual(rows[1], ('editor', '', 'tag1'))


def wiki_setup(tc):
    tc.env.enable_component('tractags')
    tc.env.path = tempfile.mkdtemp()
    _revert_tractags_schema_init(tc.env)
    TagSetup(tc.env).upgrade_environment()

    tags = ('2ndtag', 'a.really?_\wild-thing', 'heavily-quoted',
            'onetag', 'tagged', "single'quote")
    _insert_tags(tc.env, 'wiki', 'TestPage', tags)

    # Enable big diff output.
    tc.maxDiff = None


def wiki_setup_no_perm(tc):
    wiki_setup(tc)
    with tc.env.db_transaction as db:
        tc.env.db_transaction("DELETE FROM permission WHERE action %s"
                              % db.like(), ('TAGS_%',))


def wiki_teardown(tc):
    tc.env.reset_db()
    tc.env.shutdown()
    shutil.rmtree(tc.env.path)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(WikiTagProviderTestCase))
    suite.addTest(wikisyntax_test_suite(TEST_CASES, wiki_setup,
                                        __file__, wiki_teardown))
    suite.addTest(wikisyntax_test_suite(TEST_NOPERM, wiki_setup_no_perm,
                                        __file__, wiki_teardown))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
