# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2008 Dmitry Dianov
# Copyright (C) 2011 Itamar Ostricher <itamarost@gmail.com>
# Copyright (C) 2011-2012 Ryan J Ollos <ryan.j.ollos@gmail.com>
# Copyright (C) 2011-2014 Steffen Hoffmann <hoff.st@web.de>
# Copyright (C) 2021 Cinc
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re

from trac.config import BoolOption, ListOption, Option
from trac.core import implements
from trac.resource import (
    Resource, ResourceSystem, get_resource_name, get_resource_url)
from trac.test import MockRequest
from trac.timeline.api import ITimelineEventProvider
from trac.util.html import Markup, html as builder
from trac.util.text import javascript_quote, to_unicode, unicode_quote_plus
from trac.web.api import IRequestFilter, IRequestHandler
from trac.web.chrome import (
    Chrome, INavigationContributor, add_ctxtnav, add_script, add_script_data,
    add_stylesheet, add_warning, web_context)
from trac.wiki.formatter import Formatter
from trac.wiki.model import WikiPage

from tractags.api import REALM_RE, TagSystem, _, tag_, tagn_
from tractags.macros import TagTemplateProvider, TagWikiMacros, as_int
from tractags.macros import query_realms
from tractags.model import tag_changes
from tractags.query import InvalidQuery, Query
from tractags.util import JTransformer, split_into_tags


class TagInputAutoComplete(TagTemplateProvider):
    """[opt] Provides auto-complete functionality for tag input fields.

    This module is based on KeywordSuggestModule from KeywordSuggestPlugin
    0.5dev.
    """

    implements(IRequestFilter)

    field_opt = Option('tags', 'complete_field', 'keywords',
        "Ticket field to which a drop-down tag list should be attached.")

    help_opt = Option('tags', 'ticket_help', None,
        "If specified, 'keywords' label on ticket view will be turned into a "
        "link to this URL.")

    help_new_window_opt = BoolOption('tags', 'ticket_help_newwindow', False,
        "If true and keywords_help specified, wiki page will open in a new "
        "window. Default is false.")

    # Needs to be reimplemented, refs th:#8141.
    #mustmatch = BoolOption('tags', 'complete_mustmatch', False,
    #    "If true, input fields accept values from the word list only.")

    match_contains_opt = BoolOption('tags', 'complete_matchcontains', True,
        "Include partial matches in suggestion list. Default is true.")

    separator_opt = Option('tags', 'separator', ' ',
        "Character(s) to use as separators between tags. Default is a "
        "single whitespace.")

    sticky_tags_opt = ListOption('tags', 'complete_sticky_tags', '', ',',
        doc="A list of comma separated values available for input.")

    def __init__(self):
        self.tags_enabled = self.env.is_enabled(TagSystem)

    @property
    def separator(self):
        return self.separator_opt.strip('\'') or ' '

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if template == 'ticket.html' or \
                (self.tags_enabled and template == 'wiki_edit.html'):
            keywords = self._get_keywords(req)
            if not keywords:
                self.log.debug("No keywords found. TagInputAutoComplete is "
                               "disabled.")
                return template, data, content_type

            def add_autocomplete_script(field, help_href=None):
                match_from_start = '' if self.match_contains_opt else '"^" +'
                add_script_data(req, tags={
                    'autocomplete_field': field,
                    'keywords': keywords,
                    'match_from_start': match_from_start,
                    'separator': self.separator,
                    'help_href': help_href,
                    'help_new_window': self.help_new_window_opt,
                })
                add_script(req, 'tags/js/autocomplete_tags.js')

            if template == 'ticket.html':
                help_href = self._get_help_href(req)
                add_autocomplete_script('field-' + self.field_opt, help_href)
            elif self.tags_enabled and template == 'wiki_edit.html':
                add_autocomplete_script('tags')

            Chrome(self.env).add_jquery_ui(req)
        return template, data, content_type

    # Private methods

    def _get_keywords(self, req):
        keywords = set(self.sticky_tags_opt)  # prevent duplicates
        if self.tags_enabled:
            # Use TagsPlugin >= 0.7 performance-enhanced API.
            tags = TagSystem(self.env).get_all_tags(req)
            keywords.update(tags.keys())
        return sorted(keywords) if keywords else []


    def _get_help_href(self, req):
        if not self.help_opt:
            return None
        link = resource_id = None
        if self.help_opt.startswith('/'):
            # Assume valid URL to arbitrary resource inside
            #   of the current Trac environment.
            link = req.href(self.help_opt)
        if not link and ':' in self.help_opt:
            realm, resource_id = self.help_opt.split(':', 1)
            # Validate realm-like prefix against resource realm list,
            #   but exclude 'wiki' to allow deferred page creation.
            rsys = ResourceSystem(self.env)
            if realm in set(rsys.get_known_realms()) - set('wiki'):
                mgr = rsys.get_resource_manager(realm)
                # Handle optional IResourceManager method gracefully.
                try:
                    if mgr.resource_exists(Resource(realm, resource_id)):
                        link = mgr.get_resource_url(resource_id, req.href)
                except AttributeError:
                    # Assume generic resource URL build rule.
                    link = req.href(realm, resource_id)
        if not link:
            if not resource_id:
                # Assume wiki page name for backwards-compatibility.
                resource_id = self.help_opt
            if '#' in resource_id:
                path, anchor = resource_id.split('#', 1)
                anchor = unicode_quote_plus(anchor, safe="?!~*'()")
                link = '#'.join((req.href.wiki(path), anchor))
            else:
                link = req.href.wiki(resource_id)
        return link


class TagRequestHandler(TagTemplateProvider):
    """[main] Implements the /tags handler."""

    implements(INavigationContributor, IRequestHandler)

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
        return req.path_info.startswith('/tags')

    def process_request(self, req):
        req.perm.require('TAGS_VIEW')

        match = re.match(r'/tags/?(.*)', req.path_info)
        tag_id = match.group(1) and match.group(1) or None
        query = req.args.get('q', '')

        # Consider only providers, that are permitted for display.
        tag_system = TagSystem(self.env)
        all_realms = tag_system.get_taggable_realms(req.perm)
        if not (tag_id or query) or [r for r in all_realms
                                     if r in req.args] == []:
            for realm in all_realms:
                if realm not in self.exclude_realms:
                    req.args[realm] = 'on'
        checked_realms = [r for r in all_realms if r in req.args]
        if query:
            # Add permitted realms from query expression.
            checked_realms.extend(query_realms(query, all_realms))
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
                                  for realm in all_realms)
        if tag_id:
            data['tag_page'] = WikiPage(self.env,
                                        tag_system.wiki_page_prefix + tag_id)
        if query or tag_id:
            macro = 'ListTagged'
            # TRANSLATOR: The meta-nav link label.
            add_ctxtnav(req, _("Back to Cloud"), req.href.tags())
            args = "%s,format=%s,cols=%s" % \
                   (tag_id and tag_id or query, self.default_format,
                    self.default_cols)
            data['mincount'] = 0
        else:
            macro = 'TagCloud'
            mincount = as_int(req.args.get('mincount', 0),
                              self.cloud_mincount)
            args = mincount and "mincount=%s" % mincount or None
            data['mincount'] = mincount

        # When using the given req the page isn't rendered properly. The call
        # to expand_macro() leads to Chrome().render_template(req, ...).
        # The function render_template() breaks something in the request handling.
        # That used to work with Genshi.
        #
        # With this mocked req everything is just fine.
        mock_req = MockRequest(self.env, path_info=req.path_info,
                           authname=req.authname, script_name=req.href())
        formatter = Formatter(self.env, web_context(mock_req, Resource('tag')))
        self.env.log.debug("%s macro arguments: %s", macro,
                           args and args or '(none)')
        macros = TagWikiMacros(self.env)
        try:
            # Query string without realm throws 'NotImplementedError'.
            data['tag_body'] = checked_realms and \
                               macros.expand_macro(formatter, macro, args,
                                                   realms=checked_realms) \
                               or ''
            data['tag_body'] = Markup(to_unicode(data['tag_body']))
        except InvalidQuery as e:
            data['tag_query_error'] = to_unicode(e)
            data['tag_body'] = macros.expand_macro(formatter, 'TagCloud', '')

        data['realm_args'] = realm_args
        add_stylesheet(req, 'tags/css/tractags.css')
        return 'tag_view.html', data, {'domain': 'tractags'}


class TagTimelineEventFilter(TagTemplateProvider):
    """[opt] Filters timeline events by tags associated with listed resources
    mentioned in the event.
    """

    implements(IRequestFilter)

    key = 'tag_query'

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if data and req.path_info == '/timeline' and \
                'TAGS_VIEW' in req.perm(Resource('tags')):

            def realm_handler(_, node, context):
                return query.match(node, [context.realm])

            query_str = req.args.getfirst(self.key)
            if query_str is None and req.args.get('format') != 'rss':
                query_str = req.session.get('timeline.%s' % self.key)
            else:
                query_str = (query_str or '').strip()
                # Record tag query expression between visits.
                req.session['timeline.%s' % self.key] = query_str

            if data.get('events') and query_str:
                tag_system = TagSystem(self.env)
                try:
                    query = Query(query_str,
                                  attribute_handlers={'realm': realm_handler})
                except InvalidQuery as e:
                    add_warning(req, _("Tag query syntax error: %s" % e))
                else:
                    all_realms = tag_system.get_taggable_realms(req.perm)
                    query_realms = set()
                    for m in REALM_RE.finditer(query.as_string()):
                        query_realms.add(m.group(1))
                    # Don't care about resources from non-taggable realms.
                    realms = not query_realms and all_realms or \
                             query_realms.intersection(all_realms)
                    events = []
                    self.log.info("Filtering timeline events by tags '%s'",
                                   query_str)
                    for event in data['events']:
                        resource = resource_from_event(event)
                        if resource and resource.realm in realms:
                            # Shortcut view permission checks here.
                            tags = tag_system.get_tags(None, resource)
                            if query(tags, context=resource):
                                events.append(event)
                    # Overwrite with filtered list.
                    data['events'] = events
            if query_str:
                # Add current value for next form rendering.
                data[self.key] = query_str
            elif self.key in req.session:
                del req.session[self.key]

            filter_lst = []
            # xpath = '//form[@id="prefs"]/div[1]'
            xform = JTransformer('form#prefs > div:nth-of-type(1)')
            insert = builder(Markup('<br />'), tag_("matching tags "),
                             builder.input(type='text', name=self.key,
                                           value=data.get(self.key)))
            filter_lst.append(xform.append(Markup(insert)))
            add_script_data(req, {'tags_filter': filter_lst})
            add_script(req, 'tags/js/tags_jtransform.js')

        return template, data, content_type


def resource_from_event(event):
    resource = None
    event_data = event['data']
    if not isinstance(event_data, (tuple, list)):
        event_data = [event_data]
    for entry in event_data:
        try:
            entry.realm
        except AttributeError:
            pass
        else:
            resource = entry
            break
    return resource


class TagTimelineEventProvider(TagTemplateProvider):
    """[opt] Delivers recorded tag change events to timeline view."""

    implements(ITimelineEventProvider)

    # ITimelineEventProvider methods

    def get_timeline_filters(self, req):
        if 'TAGS_VIEW' in req.perm('tags'):
            yield ('tags', _("Tag changes"))

    def get_timeline_events(self, req, start, stop, filters):
        if 'tags' in filters:
            tags_realm = Resource('tags')
            if 'TAGS_VIEW' not in req.perm(tags_realm):
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
