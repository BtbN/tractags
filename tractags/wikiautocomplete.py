# -*- coding: utf-8 -*-
#
# Copyright (C) 2018 Ryan J Ollos <ryan.j.ollos@gmail.com>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from __future__ import absolute_import

from trac.core import Component, implements
from wikiautocomplete.api import IWikiAutoCompleteStrategyProvider

from tractags.api import TagSystem


class TagsWikiAutoComplete(Component):

    implements(IWikiAutoCompleteStrategyProvider)

    # IWikiAutoCompleteStrategyProvider

    def get_wiki_auto_complete_strategies(self):
        return [(
            {
                'match': r'\b(tag:|tagged:)(\S*)$',
                'name': 'tag',
                'index': 2,
                'replace_prefix': '$1',
                'cache': True,
            },
            self._suggest_tags,
        )]

    def _suggest_tags(self, req):
        all_tags = TagSystem(self.env).get_all_tags(req)
        return [{'value': tag} for tag in sorted(all_tags)]
