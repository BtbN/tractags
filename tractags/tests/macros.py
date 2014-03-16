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

from trac.test import EnvironmentStub, Mock, MockPerm
from trac.web.href import Href

from tractags.db import TagSetup
from tractags.macros import TagTemplateProvider, TagWikiMacros


class TagTemplateProviderTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(
                enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()

        # TagTemplateProvider is abstract, test using a subclass
        self.tag_wm = TagWikiMacros(self.env)

    def tearDown(self):
        shutil.rmtree(self.env.path)

    def test_template_dirs_added(self):
        from trac.web.chrome import Chrome
        self.assertTrue(self.tag_wm in Chrome(self.env).template_providers)


class ListTaggedMacroTestCase(unittest.TestCase):
    
    def setUp(self):
        self.env = EnvironmentStub(
                enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()
        self.req = Mock(path_info='/wiki/ListTaggedPage',
                        args={}, authname='user', perm=MockPerm(),
                        href=Href('/'),
                        abs_href=Href('http://example.org/trac/'),
                        chrome={}, session={}, locale='', tz='')

        self.db = self.env.get_db_cnx()
        cursor = self.db.cursor()
        cursor.execute("DROP TABLE IF EXISTS tags")
        cursor.execute("DROP TABLE IF EXISTS tags_change")
        cursor.execute("DELETE FROM system WHERE name='tags_version'")
        cursor.execute("DELETE FROM permission WHERE action %s"
                       % self.db.like(), ('TAGS_%',))

        setup = TagSetup(self.env)
        setup.upgrade_environment(self.db)
        self.tag_twm = TagWikiMacros(self.env)

    def tearDown(self):
        shutil.rmtree(self.env.path)

    def test_empty_content(self):
        context = Mock(env=self.env, href=Href('/'), req=self.req)
        formatter = Mock(context=context, req=self.req)
        self.assertTrue('No resources found' in
                        str(self.tag_twm.expand_macro(formatter,
                                                      'ListTagged', '')))


class TagCloudMacroTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(
                enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()
        self.req = Mock(path_info='/wiki/TagCloudPage',
                        args={}, authname='user', perm=MockPerm(),
                        href=Href('/'),
                        abs_href='http://example.org/trac/',
                        chrome={}, session={}, locale='', tz='')
        self.context = Mock(env=self.env, href=self.req.href, req=self.req)
        self.formatter = Mock(context=self.context, req=self.req)

        self.db = self.env.get_db_cnx()
        cursor = self.db.cursor()
        cursor.execute("DROP TABLE IF EXISTS tags")
        cursor.execute("DROP TABLE IF EXISTS tags_change")
        cursor.execute("DELETE FROM system WHERE name='tags_version'")
        cursor.execute("DELETE FROM permission WHERE action %s"
                       % self.db.like(), ('TAGS_%',))

        setup = TagSetup(self.env)
        setup.upgrade_environment(self.db)

        self.tag_twm = TagWikiMacros(self.env)

    def tearDown(self):
        shutil.rmtree(self.env.path)

    def _insert_tags(self, tagspace, name, tags):
        cursor = self.db.cursor()
        args = [(tagspace, name, tag) for tag in tags]
        cursor.executemany("INSERT INTO tags (tagspace,name,tag) "
                           "VALUES (%s,%s,%s)", args)

    def _expand_macro(self, content):
        return self.tag_twm.expand_macro(self.formatter, 'TagCloud', content)

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


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TagTemplateProviderTestCase, 'test'))
    suite.addTest(unittest.makeSuite(ListTaggedMacroTestCase, 'test'))
    suite.addTest(unittest.makeSuite(TagCloudMacroTestCase, 'test'))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
