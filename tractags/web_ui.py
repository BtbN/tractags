# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2008 Dmitry Dianov
# Copyright (C) 2011 Itamar Ostricher <itamarost@gmail.com>
# Copyright (C) 2011-2012 Ryan J Ollos <ryan.j.ollos@gmail.com>
# Copyright (C) 2011-2014 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re
import math

from genshi.builder import tag as builder
from genshi.core import Markup
from genshi.filters.transform import Transformer

from trac import __version__ as trac_version
from trac.config import BoolOption, ListOption, Option
from trac.core import ExtensionPoint, implements
from trac.mimeview import Context
from trac.resource import Resource, ResourceSystem, get_resource_name
from trac.resource import get_resource_url
from trac.timeline.api import ITimelineEventProvider
from trac.util import to_unicode
from trac.util.text import CRLF, unicode_quote_plus
from trac.web import IRequestFilter
from trac.web.api import IRequestHandler, ITemplateStreamFilter
from trac.web.api import ITemplateStreamFilter
from trac.web.chrome import Chrome, INavigationContributor
from trac.web.chrome import add_script, add_stylesheet, add_ctxtnav
from trac.wiki.formatter import Formatter
from trac.wiki.model import WikiPage

from tractags.api import TagSystem, ITagProvider, _, tag_, tagn_
from tractags.compat import is_enabled
from tractags.macros import TagTemplateProvider, TagWikiMacros, as_int
from tractags.macros import query_realms
from tractags.model import tag_changes
from tractags.query import InvalidQuery
from tractags.util import split_into_tags

try:
    from trac.util.text import javascript_quote
except ImportError:
    # Fallback for Trac<0.11.3 - verbatim copy from Trac 1.0.
    _js_quote = {'\\': '\\\\', '"': '\\"', '\b': '\\b', '\f': '\\f',
                 '\n': '\\n', '\r': '\\r', '\t': '\\t', "'": "\\'"}
    for i in range(0x20) + [ord(c) for c in '&<>']:
        _js_quote.setdefault(chr(i), '\\u%04x' % i)
    _js_quote_re = re.compile(r'[\x00-\x1f\\"\b\f\n\r\t\'&<>]')

    def javascript_quote(text):
        """Quote strings for inclusion in javascript."""
        if not text:
            return ''
        def replace(match):
            return _js_quote[match.group(0)]
        return _js_quote_re.sub(replace, text)


class TagInputAutoComplete(TagTemplateProvider):
    """[opt] Provides auto-complete functionality for tag input fields.

    This module is based on KeywordSuggestModule from KeywordSuggestPlugin
    0.5dev.
    """

    implements (IRequestFilter, ITemplateStreamFilter)

    field_opt = Option('tags', 'complete_field', 'keywords',
        "Field to which the drop-down list should be attached.")

    keywords_opt = ListOption('tags', 'sticky_tags', '', ',',
        doc="A list of comma separated values available for input.")

    # Needs to be reimplemented, refs th:#8141.
    #mustmatch = BoolOption('tags', 'complete_mustmatch', False,
    #    "If true, input fields accept values from the word list only.")

    matchcontains_opt = BoolOption('tags','complete_matchcontains_opt', True,
        "Include partial matches in suggestion list. Default is true.")

    multiple_separator_opt = Option('tags','multipleseparator', ' ',
        "Character(s) to use as separators between keywords. Default is a "
        "single whitespace.")

    helppage_opt = Option('tags','helppage_opt', None,
        "If specified, 'keywords' label on ticket view will be turned into a "
        "link to this URL.")

    helppagenewwindow_opt = BoolOption('tags','helppage_opt.newwindow', False,
        "If true and helppage_opt specified, wiki page will open in a new "
        "window. Default is false.")

    def __init__(self):
        self.tags_enabled = is_enabled(self.env, TagSystem)

    @property
    def multiple_separator(self):
        return self.multiple_separator_opt.strip('\'') or ' '

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler
    
    def post_process_request(self, req, template, data, content_type):
        if req.path_info.startswith('/ticket/') or \
           req.path_info.startswith('/newticket') or \
           (self.tags_enabled and req.path_info.startswith('/wiki/')):
                # In Trac 1.0 and later, jQuery-UI is included from the core.
                if trac_version >= '1.0':
                    Chrome(self.env).add_jquery_ui(req)
                else:
                    add_script(req, 'tags/js/jquery-ui-1.8.16.custom.min.js')
                    add_stylesheet(req, 'tags/css/jquery-ui-1.8.16.custom.css')
        return template, data, content_type


    # ITemplateStreamFilter method
    def filter_stream(self, req, method, filename, stream, data):

        if not (filename == 'ticket.html' or
                (self.tags_enabled and filename == 'wiki_edit.html')): 
            return stream
        
        keywords = self._get_keywords_string(req)
        if not keywords:
            self.log.debug(
                "No keywords found. TagInputAutoComplete is disabled.")
            return stream

        matchfromstart = '"^" +'
        if self.matchcontains_opt:
            matchfromstart = ''

        js = """
            jQuery(document).ready(function($) {
                var keywords = [ %(keywords)s ]
                var sep = '%(multipleseparator)s'.trim() + ' '
                function split( val ) {
                    return val.split( /%(multipleseparator)s\s*|\s+/ );
                }
                function extractLast( term ) {
                    return split( term ).pop();
                }                    
                $('%(field)s')
                    // don't navigate away from field on tab when selecting
                    // an item
                    .bind( "keydown", function( event ) {
                        if ( event.keyCode === $.ui.keyCode.TAB &&
                             $( this ).data( "autocomplete" ).menu.active ) {
                            event.preventDefault();
                        }
                    })
                    .autocomplete({
                        delay: 0,
                        minLength: 0,
                        source: function( request, response ) {
                            // delegate back to autocomplete, but extract
                            // the last term
                            response( $.ui.autocomplete.filter(
                                keywords, extractLast( request.term ) ) );
                        },
                        focus: function() {
                            // prevent value inserted on focus
                            return false;
                        },                            
                        select: function( event, ui ) {
                            var terms = split( this.value );
                            // remove the current input
                            terms.pop();
                            // add the selected item
                            terms.push( ui.item.value );
                            // add placeholder to get the comma-and-space at
                            // the end
                            terms.push( "" );
                            this.value = terms.join( sep );
                            return false;
                        }                            
                    });
            });"""

        # Inject transient part of JavaScript into ticket.html template.
        if req.path_info.startswith('/ticket/') or \
           req.path_info.startswith('/newticket'):
            js_ticket =  js % {'field': '#field-' + self.field_opt,
                               'multipleseparator': self.multiple_separator,
                               'keywords': keywords,
                               'matchfromstart': matchfromstart}
            stream = stream | Transformer('.//head').append\
                              (builder.script(Markup(js_ticket),
                               type='text/javascript'))

            # Turn keywords field label into link to an arbitrary resource.
            if self.helppage_opt:
                link = self._get_helppage_link(req)
                if self.helppagenewwindow_opt:
                    link = builder.a(href=link, target='blank')
                else:
                    link = builder.a(href=link)
                stream = stream | Transformer\
                     ('//label[@for="field-keywords"]/text()').wrap(link)

        # Inject transient part of JavaScript into wiki.html template.
        elif self.tags_enabled and req.path_info.startswith('/wiki/'):
            js_wiki =  js % {'field': '#tags',
                             'multipleseparator': self.multiple_separator,
                             'keywords': keywords,
                             'matchfromstart': matchfromstart}
            stream = stream | Transformer('.//head').append \
                              (builder.script(Markup(js_wiki),
                               type='text/javascript'))
        return stream

    # Private methods

    def _get_keywords_string(self, req):
        keywords = set(self.keywords_opt) # prevent duplicates
        if self.tags_enabled:
            # Use TagsPlugin >= 0.7 performance-enhanced API.
            tags = TagSystem(self.env).get_all_tags(req)
            keywords.update(tags.keys())

        if keywords:
            keywords = sorted(keywords)
            keywords = ','.join(("'%s'" % javascript_quote(_keyword)
                                 for _keyword in keywords))
        else:
            keywords = ''
            
        return keywords

    def _get_helppage_link(self, req):
        link = realm = resource_id = None
        if self.helppage_opt.startswith('/'):
            # Assume valid URL to arbitrary resource inside
            #   of the current Trac environment.
            link = req.href(self.helppage_opt)
        if not link and ':' in self.helppage_opt:
            realm, resource_id = self.helppage_opt.split(':', 1)
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
                resource_id = self.helppage_opt
            # Preserve anchor without 'path_safe' arg (since Trac 0.12.2dev).
            if '#' in resource_id:
                path, anchor = resource_id.split('#', 1)
            else:
                anchor = None
                path = resource_id
            if hasattr(unicode_quote_plus, "safe"):
                # Use method for query string quoting (since Trac 0.13dev).
                anchor = unicode_quote_plus(anchor, safe="?!~*'()")
            else:
                anchor = unicode_quote_plus(anchor)
            link = '#'.join([req.href.wiki(path), anchor])
        return link


class TagRequestHandler(TagTemplateProvider):
    """[main] Implements the /tags handler."""

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
    """[opt] Delivers recorded tag change events to timeline view."""

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
