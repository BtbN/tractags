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

try:
    from babel import Locale
    locale_en = Locale.parse('en_US')
except ImportError:
    Locale = None
    locale_en = None

from datetime import datetime

from trac.db.api import DatabaseManager
from trac.mimeview import Context
from trac.perm import PermissionCache, PermissionError, PermissionSystem
from trac.resource import Resource
from trac.test import EnvironmentStub, Mock, MockPerm
from trac.util.datefmt import utc
from trac.web.href import Href
from trac.wiki.model import WikiPage

from tractags.api import TagSystem
from tractags.db import TagSetup
from tractags.tests import formatter
from tractags.wiki import WikiTagProvider


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
# regression test for ticket `#9057`
tag:single'quote
------------------------------
<p>
<a href="/tags/onetag">tag:onetag</a>
<a href="/tags/2ndtag">tag:2ndtag</a> n' more
<a href="/tags/a.really%3F_%5Cwild-thing">tag:a.really?_\wild-thing</a>!
# regression test for ticket <tt>#9057</tt>
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
                                   enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()
        self.db = self.env.get_db_cnx()
        setup = TagSetup(self.env)
        # Current tractags schema is partially setup with enabled component.
        #   Revert these changes for getting a clean setup.
        self._revert_tractags_schema_init()
        setup.upgrade_environment(self.db)

        self.perms = PermissionSystem(self.env)
        self.tag_s = TagSystem(self.env)
        self.tag_wp = WikiTagProvider(self.env)

        cursor = self.db.cursor()
        # Populate table with initial test data.
        cursor.execute("""
            INSERT INTO tags
                   (tagspace, name, tag)
            VALUES ('wiki', 'WikiStart', 'tag1')
        """)

        self.req = Mock(authname='editor')
        # Mock an anonymous request.
        self.req.perm = PermissionCache(self.env)
        self.realm = 'wiki'
        self.tags = ['tag1']

    def tearDown(self):
        self.db.close()
        # Really close db connections.
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    # Helpers

    def _revert_tractags_schema_init(self):
        cursor = self.db.cursor()
        cursor.execute("DROP TABLE IF EXISTS tags")
        cursor.execute("DROP TABLE IF EXISTS tags_change")
        cursor.execute("DELETE FROM system WHERE name='tags_version'")
        cursor.execute("DELETE FROM permission WHERE action %s"
                       % self.db.like(), ('TAGS_%',))

    # Tests

    def test_get_tags(self):
        resource = Resource('wiki', 'WikiStart')
        self.assertEquals([tag for tag in
                           self.tag_wp.get_resource_tags(self.req, resource)],
                          self.tags)

    def test_exclude_template_tags(self):
        cursor = self.db.cursor()
        # Populate table with more test data.
        cursor.execute("""
            INSERT INTO tags
                   (tagspace, name, tag)
            VALUES ('wiki', 'PageTemplates/Template', 'tag2')
        """)
        tags = ['tag1', 'tag2']
        self.assertEquals(self.tag_s.get_all_tags(self.req).keys(), self.tags)
        self.env.config.set('tags', 'query_exclude_wiki_templates', False)
        self.assertEquals(self.tag_s.get_all_tags(self.req).keys(), tags)

    def test_set_tags_no_perms(self):
        resource = Resource('wiki', 'TaggedPage')
        self.assertRaises(PermissionError, self.tag_wp.set_resource_tags,
                          self.req, resource, self.tags)

    def test_set_tags(self):
        resource = Resource('wiki', 'TaggedPage')
        self.req.perm = PermissionCache(self.env, username='editor')
        # Shouldn't raise an error with appropriate permission.
        self.tag_wp.set_resource_tags(self.req, resource, self.tags)
        self.tag_wp.set_resource_tags(self.req, resource, ['tag2'])
        cursor = self.db.cursor()
        # Check change records.
        cursor.execute("""
            SELECT *
              FROM tags_change
             WHERE tagspace=%s
               AND name=%s
             ORDER by time DESC
        """, ('wiki', 'TaggedPage'))
        row = cursor.fetchone()
        self.assertEqual([v for v in row[-3:]], ['editor', 'tag1', 'tag2'])
        row = cursor.fetchone()
        self.assertEqual([v for v in row[-3:]], ['editor', '', 'tag1'])


def wiki_setup(tc):
    tc.env = EnvironmentStub(default_data=True,
                             enable=['trac.*', 'tractags.*'])
    tc.env.path = tempfile.mkdtemp()
    tc.db_mgr = DatabaseManager(tc.env)
    tc.db = tc.env.get_db_cnx()

    cursor = tc.db.cursor()
    cursor.execute("DROP TABLE IF EXISTS tags")
    cursor.execute("DROP TABLE IF EXISTS tags_change")
    cursor.execute("DELETE FROM system WHERE name='tags_version'")
    cursor.execute("DELETE FROM permission WHERE action %s"
                   % tc.db.like(), ('TAGS_%',))

    TagSetup(tc.env).upgrade_environment(tc.db)

    now = datetime.now(utc)
    wiki = WikiPage(tc.env)
    wiki.name = 'TestPage'
    wiki.text = '--'
    wiki.save('joe', 'TagsPluginTestPage', '::1', now)

    cursor = tc.db.cursor()
    # Populate table with initial test data.
    cursor.executemany("""
        INSERT INTO tags
               (tagspace, name, tag)
        VALUES (%s,%s,%s)
    """, [('wiki', 'TestPage', '2ndtag'),
          ('wiki', 'TestPage', 'a.really?_\wild-thing'),
          ('wiki', 'TestPage', 'heavily-quoted'),
          ('wiki', 'TestPage', 'onetag'),
          ('wiki', 'TestPage', 'tagged'),
          ('wiki', 'TestPage', "single'quote"),
         ])

    req = Mock(href=Href('/'), abs_href=Href('http://www.example.com/'),
               authname='anonymous', perm=MockPerm(), tz=utc, args={},
               locale=locale_en)
    tc.env.href = req.href
    tc.env.abs_href = req.abs_href
    tc.context = Context.from_request(req)
    # Enable big diff output.
    tc.maxDiff = None

def wiki_setup_no_perm(tc):
    wiki_setup(tc)
    tc.db = tc.env.get_db_cnx()

    cursor = tc.db.cursor()
    cursor.execute("DELETE FROM permission WHERE action %s"
                   % tc.db.like(), ('TAGS_%',))

def wiki_teardown(tc):
    tc.env.reset_db()
    tc.db.close()
    # Really close db connections.
    tc.env.shutdown()
    shutil.rmtree(tc.env.path)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(WikiTagProviderTestCase, 'test'))
    suite.addTest(formatter.suite(TEST_CASES, wiki_setup, __file__,
                                  wiki_teardown))
    suite.addTest(formatter.suite(TEST_NOPERM, wiki_setup_no_perm, __file__,
                                  wiki_teardown))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
TEST_NOPERM
