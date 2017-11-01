# -*- coding: utf-8 -*-
#
# Copyright (C) 2011 Odd Simon Simonsen <oddsimons@gmail.com>
# Copyright (C) 2012-2015 Steffen Hoffmann <hoff.st@web.de>
# Copyright (C) 2014 Jun Omae <jun66j5@gmail.com>
# Copyright (C) 2015 Ryan J Ollos <ryan.j.ollos@gmail.com>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.test import EnvironmentStub, Mock, MockRequest
from trac.web.chrome import Chrome
from trac.web.href import Href
from trac.wiki.test import wikisyntax_test_suite

from tractags.db import TagSetup
from tractags.macros import TagWikiMacros, query_realms


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


class _BaseTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()

        setup = TagSetup(self.env)
        # Current tractags schema is setup with enabled component anyway.
        #   Revert these changes for getting default permissions inserted.
        self._revert_tractags_schema_init()
        setup.upgrade_environment()

    def tearDown(self):
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    def _revert_tractags_schema_init(self):
        _revert_tractags_schema_init(self.env)

    def _insert_tags(self, tagspace, name, tags):
        _insert_tags(self.env, tagspace, name, tags)


class TagTemplateProviderTestCase(_BaseTestCase):

    def setUp(self):
        _BaseTestCase.setUp(self)

        # TagTemplateProvider is abstract, test using a subclass
        self.tag_wm = TagWikiMacros(self.env)

    def test_template_dirs_added(self):
        self.assertTrue(self.tag_wm in Chrome(self.env).template_providers)


class ListTaggedMacroTestCase(_BaseTestCase):

    def setUp(self):
        _BaseTestCase.setUp(self)
        self.req = MockRequest(self.env, path_info='/wiki/ListTaggedPage',
                               authname='user')

        self.tag_twm = TagWikiMacros(self.env)

    def test_empty_content(self):
        context = Mock(env=self.env, href=Href('/'), req=self.req)
        formatter = Mock(context=context, req=self.req)
        self.assertTrue('No resources found' in
                        str(self.tag_twm.expand_macro(formatter,
                                                      'ListTagged', '')))

    def test_listtagged_exclude(self):
        self._insert_tags('wiki', 'InterTrac', ('blah',))
        self._insert_tags('wiki', 'InterWiki', ('blah',))
        self._insert_tags('wiki', 'WikiStart', ('blah',))
        context = Mock(env=self.env, href=Href('/'), req=self.req)
        formatter = Mock(context=context, req=self.req)
        result = unicode(self.tag_twm.expand_macro(formatter, 'ListTagged',
                                                   'blah,exclude=Inter*'))
        self.assertFalse('InterTrac' in result)
        self.assertFalse('InterWiki' in result)
        self.assertTrue('WikiStart' in result)

        result = unicode(self.tag_twm.expand_macro(formatter, 'ListTagged',
                                                   'blah,exclude=Wi*:*ki'))
        self.assertTrue('InterTrac' in result)
        self.assertFalse('InterWiki' in result)
        self.assertFalse('WikiStart' in result)

    def _test_listtagged_paginate(self, page, per_page=2):
        self._insert_tags('wiki', 'InterTrac', ('blah',))
        self._insert_tags('wiki', 'InterWiki', ('blah',))
        self._insert_tags('wiki', 'WikiStart', ('blah',))
        self.req.args['listtagged_per_page'] = per_page
        self.req.args['listtagged_page'] = page
        context = Mock(env=self.env, href=Href('/'), req=self.req)
        formatter = Mock(context=context, req=self.req)
        result = \
            unicode(self.tag_twm.expand_macro(formatter, 'ListTagged', 'blah'))
        return result

    def test_listtagged_paginate_page1(self):
        """Paginate results for page 1 has two items."""
        result = self._test_listtagged_paginate(1)
        self.assertTrue('InterTrac' in result)
        self.assertTrue('InterWiki' in result)
        self.assertFalse('WikiStart' in result)

    def test_listtagged_paginate_page2(self):
        """Paginate results for page 2 has one item."""
        result = self._test_listtagged_paginate(2)
        self.assertFalse('InterTrac' in result)
        self.assertFalse('InterWiki' in result)
        self.assertTrue('WikiStart' in result)

    def test_listtagged_paginate_page_out_of_range(self):
        """Out of range page defaults to 1."""
        result = self._test_listtagged_paginate(3)
        self.assertTrue('InterTrac' in result)
        self.assertTrue('InterWiki' in result)
        self.assertFalse('WikiStart' in result)

    def test_listtagged_paginate_page_invalid(self):
        """Invalid page default to 1."""
        result = self._test_listtagged_paginate(-1)
        self.assertTrue('InterTrac' in result)
        self.assertTrue('InterWiki' in result)
        self.assertFalse('WikiStart' in result)

    def test_listtagged_paginate_per_page_invalid(self):
        """Invalid per_page defaults to items_per_page (100)."""
        result = self._test_listtagged_paginate(2, -1)
        self.assertTrue('InterTrac' in result)
        self.assertTrue('InterWiki' in result)
        self.assertTrue('WikiStart' in result)


LISTTAGGED_MACRO_TEST_CASES = u"""
============================== invalid operator
[[ListTagged(xyz:wiki xyz)]]
------------------------------
<p>
</p><div class="system-message">\
<strong>ListTagged macro error</strong>\
<pre>Invalid attribute \'xyz\'</pre>\
</div><p>
</p>
============================== invalid realm
[[ListTagged(realm:xyz blah)]]
------------------------------
<p>
</p><div class="system-message">\
<strong>ListTagged macro error</strong>\
<pre>Tags are not supported on the \'xyz\' realm</pre>\
</div><p>
</p>
"""


def listtagged_setup(tc):
    _revert_tractags_schema_init(tc.env)
    TagSetup(tc.env).upgrade_environment()
    _insert_tags(tc.env, 'wiki', 'WikiStart', ('abc', 'xyz'))


def listtagged_teardown(tc):
    _revert_tractags_schema_init(tc.env)


class TagCloudMacroTestCase(_BaseTestCase):

    def setUp(self):
        _BaseTestCase.setUp(self)
        self.req = MockRequest(self.env, path_info='/wiki/TagCloudPage',
                               authname='user')
        self.context = Mock(env=self.env, href=self.req.href, req=self.req)
        self.formatter = Mock(context=self.context, req=self.req)

        self.tag_twm = TagWikiMacros(self.env)

    # Helpers

    def _expand_macro(self, content):
        return self.tag_twm.expand_macro(self.formatter, 'TagCloud', content)

    # Tests

    def test_normal(self):
        self._insert_tags('wiki',   'CamelCase',     ('blah', 'foo', 'bar'))
        self._insert_tags('wiki',   'InterMapTxt',   ('blah', 'foo', 'bar'))
        self._insert_tags('wiki',   'InterTrac',     ('blah',))
        self._insert_tags('wiki',   'InterWiki',     ('blah',))
        self._insert_tags('wiki',   'PageTemplates', ('blah',))
        self._insert_tags('wiki',   'RecentChanges', ('blah', 'foo'))
        self._insert_tags('wiki',   'SandBox',       ('blah', 'foo'))
        self._insert_tags('ticket', '1',             ('blah',))
        self._insert_tags('ticket', '2',             ('blah', 'bar'))
        self._insert_tags('ticket', '3',             ('blah', 'bar'))
        self._insert_tags('ticket', '4',             ('blah', 'bar'))

        result = unicode(self._expand_macro(''))
        self.assertTrue('">blah</a>' in result, repr(result))
        self.assertTrue('">foo</a>' in result, repr(result))
        self.assertTrue('">bar</a>' in result, repr(result))

        result = unicode(self._expand_macro('mincount=5'))
        self.assertTrue('">blah</a>' in result, repr(result))
        self.assertFalse('">foo</a>' in result, repr(result))
        self.assertTrue('">bar</a>' in result, repr(result))

        result = unicode(self._expand_macro('mincount=6'))
        self.assertTrue('">blah</a>' in result, repr(result))
        self.assertFalse('">foo</a>' in result, repr(result))
        self.assertFalse('">bar</a>' in result, repr(result))

        result = unicode(self._expand_macro('realm=ticket|wiki'))
        self.assertTrue('">blah</a>' in result, repr(result))
        self.assertTrue('">foo</a>' in result, repr(result))
        self.assertTrue('">bar</a>' in result, repr(result))

        result = unicode(self._expand_macro('realm=ticket'))
        self.assertTrue('">blah</a>' in result, repr(result))
        self.assertFalse('">foo</a>' in result, repr(result))
        self.assertTrue('">bar</a>' in result, repr(result))

        result = unicode(self._expand_macro('realm=ticket,mincount=4'))
        self.assertTrue('">blah</a>' in result, repr(result))
        self.assertFalse('">foo</a>' in result, repr(result))
        self.assertFalse('">bar</a>' in result, repr(result))

        result = unicode(self._expand_macro('realm=unknown'))
        self.assertEquals('No tags found', result)

        result = unicode(self._expand_macro('mincount=100'))
        self.assertEquals('No tags found', result)


class QueryRealmsTestCase(unittest.TestCase):
    def test_query_realms(self):
        all_realms = ['ticket', 'wiki']
        # No tag providers detected.
        self.assertFalse('ticket' in query_realms('', []))
        # No tags query statement used.
        self.assertFalse('ticket' in query_realms('', all_realms))
        self.assertFalse('ticket' in query_realms('ticket', all_realms))
        self.assertFalse('ticket' in query_realms('realm:ticket', ['wiki']))
        self.assertTrue('ticket' in query_realms('realm:ticket', all_realms))
        self.assertFalse('wiki' in query_realms('realm:ticket', all_realms))
        self.assertTrue('wiki' in
                        query_realms('onetag realm:wiki 2ndtag', all_realms))
        self.assertFalse('wiki' in
                         query_realms('onetag realm=wiki 2ndtag', all_realms))


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TagTemplateProviderTestCase))
    suite.addTest(unittest.makeSuite(ListTaggedMacroTestCase))
    suite.addTest(
        wikisyntax_test_suite(LISTTAGGED_MACRO_TEST_CASES, listtagged_setup,
                              __file__, listtagged_teardown,
                              enable_components=('trac.*', 'tractags.*')))
    suite.addTest(unittest.makeSuite(TagCloudMacroTestCase))
    suite.addTest(unittest.makeSuite(QueryRealmsTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
