# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2011 Itamar Ostricher <itamarost@gmail.com>
# Copyright (C) 2011-2014 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re
import math

from genshi.builder import tag as builder

from trac.config import ListOption, Option
from trac.core import ExtensionPoint, implements
from trac.mimeview import Context
from trac.resource import Resource, get_resource_name, get_resource_url
from trac.timeline.api import ITimelineEventProvider
from trac.util import to_unicode
from trac.util.text import CRLF
from trac.web.api import IRequestHandler
from trac.web.chrome import INavigationContributor
from trac.web.chrome import add_stylesheet, add_ctxtnav
from trac.wiki.formatter import Formatter
from trac.wiki.model import WikiPage

from tractags.api import TagSystem, ITagProvider, _, tag_, tagn_
from tractags.macros import TagTemplateProvider, TagWikiMacros, as_int
from tractags.macros import query_realms
from tractags.model import tag_changes
from tractags.query import InvalidQuery
from tractags.util import split_into_tags


class TagRequestHandler(TagTemplateProvider):
    """Implements the /tags handler."""

    implements(INavigationContributor, IRequestHandler)

    tag_providers = ExtensionPoint(ITagProvider)

    cloud_mincount = Option('tags', 'cloud_mincount', 1,
        doc="""Integer threshold to hide tags with smaller count.""")
    default_cols = Option('tags', 'default_table_cols', 'id|description|tags',
        doc="""Select columns and order for table format using a "|"-separated
            list of column names.

            Supported columns: realm, id, description, tags
            """)
    default_format = Option('tags', 'default_format', 'oldlist',
        doc="""Set the default format for the handler of the `/tags` domain.

            || `oldlist` (default value) || The original format with a
            bulleted-list of "linked-id description (tags)" ||
            || `compact` || bulleted-list of "linked-description" ||
            || `table` || table... (see corresponding column option) ||
            """)
    exclude_realms = ListOption('tags', 'exclude_realms', [],
        doc="""Comma-separated list of realms to exclude from tags queries
            by default, unless specifically included using "realm:realm-name"
            in a query.""")

    # INavigationContributor methods
    def get_active_navigation_item(self, req):
        if 'TAGS_VIEW' in req.perm:
            return 'tags'

    def get_navigation_items(self, req):
        if 'TAGS_VIEW' in req.perm:
            label = tag_("Tags")
            yield ('mainnav', 'tags',
                   builder.a(label, href=req.href.tags(), accesskey='T'))

    # IRequestHandler methods
    def match_request(self, req):
        return 'TAGS_VIEW' in req.perm and req.path_info.startswith('/tags')

    def process_request(self, req):
        req.perm.require('TAGS_VIEW')

        match = re.match(r'/tags/?(.*)', req.path_info)
        tag_id = match.group(1) and match.group(1) or None
        query = req.args.get('q', '')

        # Consider only providers, that are permitted for display.
        realms = [p.get_taggable_realm() for p in self.tag_providers
                  if (not hasattr(p, 'check_permission') or \
                      p.check_permission(req.perm, 'view'))]
        if not (tag_id or query) or [r for r in realms if r in req.args] == []: 
            for realm in realms:
                if not realm in self.exclude_realms:
                    req.args[realm] = 'on'
        checked_realms = [r for r in realms if r in req.args]
        if query:
            # Add permitted realms from query expression.
            checked_realms.extend(query_realms(query, realms))
        realm_args = dict(zip([r for r in checked_realms],
                              ['on' for r in checked_realms]))
        # Switch between single tag and tag query expression mode.
        if tag_id and not re.match(r"""(['"]?)(\S+)\1$""", tag_id, re.UNICODE):
            # Convert complex, invalid tag ID's --> query expression.
            req.redirect(req.href.tags(realm_args, q=tag_id))
        elif query:
            single_page = re.match(r"""(['"]?)(\S+)\1$""", query, re.UNICODE)
            if single_page:
                # Convert simple query --> single tag.
                req.redirect(req.href.tags(single_page.group(2), realm_args))

        data = dict(page_title=_("Tags"), checked_realms=checked_realms)
        # Populate the TagsQuery form field.
        data['tag_query'] = tag_id and tag_id or query
        data['tag_realms'] = list(dict(name=realm,
                                       checked=realm in checked_realms)
                                  for realm in realms)
        if tag_id:
            data['tag_page'] = WikiPage(self.env,
                                        TagSystem(self.env).wiki_page_prefix \
                                        + tag_id)
        if query or tag_id:
            macro = 'ListTagged'
            # TRANSLATOR: The meta-nav link label.
            add_ctxtnav(req, _("Back to Cloud"), req.href.tags())
            args = "%s,format=%s,cols=%s" % \
                   (tag_id and tag_id or query, self.default_format,
                    self.default_cols)
            data['mincount'] = None
        else:
            macro = 'TagCloud'
            mincount = as_int(req.args.get('mincount', None),
                              self.cloud_mincount)
            args = mincount and "mincount=%s" % mincount or None
            data['mincount'] = mincount
        formatter = Formatter(self.env, Context.from_request(req,
                                                             Resource('tag')))
        self.env.log.debug(
            "%s macro arguments: %s" % (macro, args and args or '(none)'))
        macros = TagWikiMacros(self.env)
        try:
            # Query string without realm throws 'NotImplementedError'.
            data['tag_body'] = checked_realms and \
                               macros.expand_macro(formatter, macro, args,
                                                   realms=checked_realms) \
                               or ''
        except InvalidQuery, e:
            data['tag_query_error'] = to_unicode(e)
            data['tag_body'] = macros.expand_macro(formatter, 'TagCloud', '')
        add_stylesheet(req, 'tags/css/tractags.css')
        return 'tag_view.html', data, None


class TagTimelineEventProvider(TagTemplateProvider):
    """Delivers recorded tag change events to the timeline."""

    implements(ITimelineEventProvider)

    # ITimelineEventProvider methods

    def get_timeline_filters(self, req):
        if 'TAGS_VIEW' in req.perm('tags'):
            yield ('tags', _("Tag changes"))

    def get_timeline_events(self, req, start, stop, filters):
        if 'tags' in filters:
            tags_realm = Resource('tags')
            if not 'TAGS_VIEW' in req.perm(tags_realm):
                return
            add_stylesheet(req, 'tags/css/tractags.css')
            for time, author, tagspace, name, old_tags, new_tags in \
                    tag_changes(self.env, None, start, stop):
                tagged_resource = Resource(tagspace, name)
                if 'TAGS_VIEW' in req.perm(tagged_resource):
                    yield ('tags', time, author,
                           (tagged_resource, old_tags, new_tags), self) 

    def render_timeline_event(self, context, field, event):
        resource = event[3][0]
        if field == 'url':
            return get_resource_url(self.env, resource, context.href)
        elif field == 'title':
            name = builder.em(get_resource_name(self.env, resource))
            return tag_("Tag change on %(resource)s", resource=name)
        elif field == 'description':
            return render_tag_changes(event[3][1], event[3][2])


def render_tag_changes(old_tags, new_tags):
        old_tags = split_into_tags(old_tags or '')
        new_tags = split_into_tags(new_tags or '')
        added = sorted(new_tags - old_tags)
        added = added and \
                tagn_("%(tags)s added", "%(tags)s added",
                      len(added), tags=builder.em(', '.join(added)))
        removed = sorted(old_tags - new_tags)
        removed = removed and \
                  tagn_("%(tags)s removed", "%(tags)s removed",
                        len(removed), tags=builder.em(', '.join(removed)))
        # TRANSLATOR: How to delimit added and removed tags.
        delim = added and removed and _("; ")
        return builder(builder.strong(_("Tags")), ' ', added,
                       delim, removed)

