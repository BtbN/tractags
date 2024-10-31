# -*- coding: utf-8 -*-
#
# Copyright (C) 2011 Odd Simon Simonsen <oddsimons@gmail.com>
# Copyright (C) 2012 Ryan J Ollos <ryan.j.ollos@gmail.com>
# Copyright (C) 2012-2014 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.test import EnvironmentStub, MockPerm, MockRequest
from trac.perm import PermissionSystem, PermissionError
from trac.web.api import RequestDone
from trac.web.main import RequestDispatcher

from ..api import TagSystem
from ..db import TagSetup
from ..web_ui import TagInputAutoComplete, TagRequestHandler
from ..web_ui import TagTimelineEventFilter, TagTimelineEventProvider
from . import makeSuite


class _BaseTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.*', 'tractags.*'])
        self.env.path = tempfile.mkdtemp()
        setup = TagSetup(self.env)
        # Current tractags schema is setup with enabled component anyway.
        #   Revert these changes for getting a clean setup.
        self._revert_tractags_schema_init()
        setup.upgrade_environment()

        self.tag_s = TagSystem(self.env)
        self.tag_rh = TagRequestHandler(self.env)

        perms = PermissionSystem(self.env)
        # Revoke default permissions, because more diversity is required here.
        perms.revoke_permission('anonymous', 'TAGS_VIEW')
        perms.revoke_permission('authenticated', 'TAGS_MODIFY')
        perms.grant_permission('reader', 'TAGS_VIEW')
        perms.grant_permission('writer', 'TAGS_MODIFY')
        perms.grant_permission('admin', 'TAGS_ADMIN')

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


class TagInputAutoCompleteTestCase(_BaseTestCase):

    def setUp(self):
        _BaseTestCase.setUp(self)
        self.req = MockRequest(self.env)
        self.req.perm = MockPerm()
        self.tac = TagInputAutoComplete(self.env)

    # Tests

    def test_separator_is_default(self):
        self.assertEqual(' ', self.tac.separator_opt)

    def test_separator_is_empty_quotes(self):
        self.env.config.set('tags', 'separator', "''")
        self.assertEqual(' ', self.tac.separator)

    def test_separator_is_comma(self):
        self.env.config.set('tags', 'separator', ',')
        self.assertEqual(',', self.tac.separator)

    def test_separator_is_quoted_strip_quotes(self):
        self.env.config.set('tags', 'separator', "','")
        self.assertEqual(',', self.tac.separator)

    def test_separator_is_quoted_whitespace_strip_quotes(self):
        self.env.config.set('tags', 'separator', "' '")
        self.assertEqual(' ', self.tac.separator)

    def test_get_keywords_no_keywords(self):
        self.assertEqual([], self.tac._get_keywords(self.req))

    def test_get_keywords_define_in_config(self):
        self.env.config.set('tags', 'complete_sticky_tags',
                            'tag1, tag2, tag3')
        self.assertEqual(['tag1','tag2','tag3'],
                         self.tac._get_keywords(self.req))

    def test_keywords_are_sorted(self):
        self.env.config.set('tags', 'complete_sticky_tags',
                            'tagb, tagc, taga')
        self.assertEqual(['taga','tagb','tagc'],
                         self.tac._get_keywords(self.req))

    def test_keywords_duplicates_removed(self):
        self.env.config.set('tags', 'complete_sticky_tags',
                            'tag1, tag1, tag2')
        self.assertEqual(['tag1','tag2'],
                         self.tac._get_keywords(self.req))

    def test_implements_irequestfilter(self):
        from trac.web.main import RequestDispatcher
        self.assertTrue(self.tac in RequestDispatcher(self.env).filters)

    def test_implements_itemplateprovider(self):
        from trac.web.chrome import Chrome
        self.assertTrue(self.tac in Chrome(self.env).template_providers)


class TagRequestHandlerTestCase(_BaseTestCase):

    def setUp(self):
        _BaseTestCase.setUp(self)

    # Tests

    def test_matches(self):
        req = MockRequest(self.env, path_info='/tags', authname='reader')
        self.assertEqual(True, self.tag_rh.match_request(req))

    def test_get_main_page(self):
        req = MockRequest(self.env, path_info='/tags', authname='reader')
        template, data, content_type = self.tag_rh.process_request(req)
        self.assertEqual('tag_view.html', template)
        self.assertIsInstance(content_type, dict)
        self.assertEqual(['checked_realms', 'mincount', 'page_title',
                          'realm_args',
                           'tag_body', 'tag_query', 'tag_realms'],
                          sorted(data.keys()))

    def test_get_main_page_no_permission(self):
        req = MockRequest(self.env, path_info='/tags', authname='anonymous')
        self.assertRaises(PermissionError, self.tag_rh.process_request, req)


class TagTimelineEventFilterTestCase(_BaseTestCase):

    def setUp(self):
        _BaseTestCase.setUp(self)
        self.tef = TagTimelineEventFilter(self.env)
        self.tep = TagTimelineEventProvider(self.env)

    # Tests

    def test_implements_irequestfilter(self):
        from trac.web.main import RequestDispatcher
        self.assertTrue(self.tef in RequestDispatcher(self.env).filters)

    def test_tag_query_save(self):
        """Save timeline tag query string in session."""
        self.assertEqual('tag_query', self.tef.key)

        from trac.timeline.web_ui import TimelineModule
        TimelineModule(self.env)
        perms = PermissionSystem(self.env)
        perms.grant_permission('anonymous', 'TAGS_VIEW')
        perms.grant_permission('anonymous', 'TIMELINE_VIEW')

        req = MockRequest(self.env, path_info='/timeline',
                          args={'tag_query': 'query_str'})
        dispatcher = RequestDispatcher(self.env)
        self.assertRaises(RequestDone, dispatcher.dispatch, req)
        self.assertEqual('query_str', req.session['timeline.tag_query'])


class TagTimelineEventProviderTestCase(_BaseTestCase):

    def setUp(self):
        _BaseTestCase.setUp(self)
        self.tep = TagTimelineEventProvider(self.env)

    # Tests

    def test_implements_itimelineeventsprovider(self):
        from trac.timeline.web_ui import TimelineModule
        self.assertTrue(self.tep in TimelineModule(self.env).event_providers)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(makeSuite(TagInputAutoCompleteTestCase))
    suite.addTest(makeSuite(TagRequestHandlerTestCase))
    suite.addTest(makeSuite(TagTimelineEventFilterTestCase))
    suite.addTest(makeSuite(TagTimelineEventProviderTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
