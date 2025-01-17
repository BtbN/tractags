# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2014 Jun Omae <jun66j5@gmail.com>
# Copyright (C) 2011-2014 Steffen Hoffmann <hoff.st@web.de>
# Copyright (C) 2021 Cinc
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import collections
import re

from trac.config import BoolOption
from trac.core import Component, implements
from trac.resource import Resource, render_resource_link, get_resource_url
from trac.util import lazy
from trac.util.datefmt import to_utimestamp
from trac.util.html import Fragment, Markup, tag
from trac.util.text import to_unicode
from trac.util.translation import tag_
from trac.web.api import IRequestFilter
from trac.web.chrome import add_script, add_script_data, add_stylesheet, web_context
from trac.wiki.api import IWikiChangeListener, IWikiPageManipulator
from trac.wiki.api import IWikiSyntaxProvider
from trac.wiki.formatter import format_to_oneliner
from trac.wiki.model import WikiPage
from trac.wiki.parser import WikiParser
from trac.wiki.web_ui import WikiModule

from tractags.api import DefaultTagProvider, TagSystem, _, requests
from tractags.macros import TagTemplateProvider
from tractags.model import delete_tags, tag_changes
from tractags.web_ui import render_tag_changes
from tractags.util import JTransformer, MockReq, query_realms, split_into_tags
from tractags.query import InvalidQuery


try:
    unicode
except NameError:
    # Python 3
    def next_iter(i):
        return next(i)
else:
    def next_iter(i):
        return i.next()

class WikiTagProvider(DefaultTagProvider):
    """[main] Tag provider for Trac wiki."""

    realm = 'wiki'

    exclude_templates = BoolOption('tags', 'query_exclude_wiki_templates',
        default=True,
        doc="Whether tagged wiki page templates should be queried.")

    first_head = re.compile(r'=\s+([^=\n]*)={0,1}')

    def check_permission(self, perm, action):
        map = {'view': 'WIKI_VIEW', 'modify': 'WIKI_MODIFY'}
        return super(WikiTagProvider, self).check_permission(perm, action) \
            and map[action] in perm

    def get_tagged_resources(self, req, tags=None, filter=None):
        if self.exclude_templates:
            with self.env.db_query as db:
                like_templates = ''.join(
                    ["'", db.like_escape(WikiModule.PAGE_TEMPLATES_PREFIX),
                     "%%'"])
                filter = (' '.join(['name NOT', db.like() % like_templates]),)
        return super(WikiTagProvider, self).get_tagged_resources(req, tags,
                                                                 filter)

    def get_all_tags(self, req, filter=None):
        if not self.check_permission(req.perm, 'view'):
            return collections.Counter()
        if self.exclude_templates:
            with self.env.db_transaction as db:
                like_templates = ''.join(
                    ["'", db.like_escape(WikiModule.PAGE_TEMPLATES_PREFIX),
                     "%%'"])
                filter = (' '.join(['name NOT', db.like() % like_templates]),)
        return super(WikiTagProvider, self).get_all_tags(req, filter)

    def describe_tagged_resource(self, req, resource):
        if not self.check_permission(req.perm(resource), 'view'):
            return ''
        page = WikiPage(self.env, resource.id)
        if page.exists:
            ret = self.first_head.search(page.text)
            return ret and ret.group(1) or ''
        return ''


class WikiTagInterface(TagTemplateProvider):
    """[main] Implements the user interface for tagging Wiki pages."""

    implements(IRequestFilter, IWikiChangeListener, IWikiPageManipulator)

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if template is not None:
            if req.method == 'GET' and req.path_info.startswith('/wiki/'):
                if req.args.get('action') == 'edit' and \
                        req.args.get('template') and 'tags' not in req.args:
                    self._post_process_request_edit(req)
                if req.args.get('action') == 'history' and \
                        data and 'history' in data:
                    self._post_process_request_history(req, data)
            elif req.method == 'POST' and \
                    req.path_info.startswith('/wiki/') and \
                    'save' in req.args:
                requests.reset()

            # Insert the tags information and controls into
            # the wiki page
            if data and 'page' in data:
                if template == 'wiki_view.html' and \
                        'TAGS_VIEW' in req.perm(data['page'].resource):
                    self._post_process_request_wiki_view(req)
                elif template == 'wiki_edit.html' and \
                        'TAGS_MODIFY' in req.perm(data['page'].resource):
                    self._post_process_request_wiki_edit(req)
                elif template == 'history_view.html' and \
                        'TAGS_VIEW' in req.perm(data['page'].resource):
                    self._post_process_request_wiki_history(req)

        return template, data, content_type

    # IWikiPageManipulator methods
    def prepare_wiki_page(self, req, page, fields):
        pass

    def validate_wiki_page(self, req, page):
        # If we're saving the wiki page, and can modify tags, do so.
        if req and 'TAGS_MODIFY' in req.perm(page.resource) \
                and req.path_info.startswith('/wiki') and 'save' in req.args:
            page_modified = req.args.get('text') != page.old_text or \
                    page.readonly != int('readonly' in req.args)
            if page_modified:
                requests.set(req)
                req.add_redirect_listener(self._redirect_listener)
            elif page.version > 0:
                # If the page hasn't been otherwise modified, save tags and
                # redirect to avoid the "page has not been modified" warning.
                if self._update_tags(req, page):
                    req.redirect(get_resource_url(self.env, page.resource,
                                                  req.href, version=None))
        return []

    # IWikiChangeListener methods
    def wiki_page_added(self, page):
        req = requests.get()
        if req:
            self._update_tags(req, page, page.time)

    def wiki_page_changed(self, page, version, t, comment, author):
        req = requests.get()
        if req:
            self._update_tags(req, page, page.time)

    def wiki_page_renamed(self, page, old_name):
        """Called when a page has been renamed (since Trac 0.12)."""
        self.log.debug("Moving wiki page tags from %s to %s",
                       old_name, page.name)
        req = MockReq()
        self.tag_system.reparent_tags(req, Resource('wiki', page.name),
                                      old_name)

    def wiki_page_deleted(self, page):
        # Page gone, so remove all records on it.
        delete_tags(self.env, page.resource, purge=True)

    def wiki_page_version_deleted(self, page):
        pass

    # Internal methods

    @lazy
    def tag_system(self):
        return TagSystem(self.env)

    def _page_tags(self, req):
        pagename = req.args.get('page', 'WikiStart')
        # 'version' and 'tags_version' are part of the url
        # whrn coming from the history
        version = req.args.get('version')
        tags_version = req.args.get('tags_version')

        page = WikiPage(self.env, pagename, version=version)
        resource = page.resource
        if version and not tags_version:
            tags_version = page.time
        tags = sorted(self.tag_system.get_tags(req, resource,
                                               when=tags_version))
        return tags

    def _redirect_listener(self, req, url, permanent):
        requests.reset()

    def _post_process_request_edit(self, req):
        # Retrieve template resource to be queried for tags.
        template_pagename = ''.join([WikiModule.PAGE_TEMPLATES_PREFIX,
                                     req.args.get('template')])
        template_page = WikiPage(self.env, template_pagename)
        if template_page.exists and \
                'TAGS_VIEW' in req.perm(template_page.resource):
            tags = sorted(self.tag_system.get_tags(req,
                                                   template_page.resource))
            # Prepare tags as content for the editor field.
            tags_str = ' '.join(tags)
            self.env.log.debug("Tags retrieved from template: '%s'",
                               to_unicode(tags_str).encode('utf-8'))
            # DEVEL: More arguments need to be propagated here?
            req.redirect(req.href(req.path_info,
                                  action='edit', tags=tags_str,
                                  template=req.args.get('template')))

    def _post_process_request_history(self, req, data):
        history = []
        page_histories = data.get('history', [])
        resource = data['resource']
        tags_histories = tag_changes(self.env, resource)

        for page_history in page_histories:
            while tags_histories and \
                    tags_histories[0][0] >= page_history['date']:
                tags_history = tags_histories.pop(0)
                date = tags_history[0]
                author = tags_history[1]
                comment = render_tag_changes(tags_history[2], tags_history[3])
                url = req.href(resource.realm, resource.id,
                               version=page_history['version'],
                               tags_version=to_utimestamp(date))
                history.append({'version': '*', 'url': url, 'date': date,
                                'author': author, 'comment': comment})
            history.append(page_history)

        data.update(dict(history=history,
                         wiki_to_oneliner=self._wiki_to_oneliner))

    def _post_process_request_wiki_view(self, req):
        add_stylesheet(req, 'tags/css/tractags.css')
        tags = self._page_tags(req)
        if not tags:
            return
        li = []
        for t in tags:
            resource = Resource('tag', t)
            anchor = render_resource_link(self.env,
                                          web_context(req, resource),
                                          resource)
            anchor = anchor(rel='tag')
            li.append(tag.li(anchor, ' '))

        # TRANSLATOR: Header label text for tag list at wiki page bottom.
        insert = tag.ul(class_='tags')(tag.li(_("Tags"), class_='header'), li)

        filter_lst = []
        # xpath = //div[contains(@class,"wikipage")]
        xform = JTransformer('div[class*=wikipage]')
        filter_lst.append(xform.after(Markup(insert)))

        self._add_jtransform(req, filter_lst)
        return

    def _update_tags(self, req, page, when=None):
        newtags = split_into_tags(req.args.get('tags', ''))
        oldtags = self.tag_system.get_tags(req, page.resource)

        if oldtags != newtags:
            self.tag_system.set_tags(req, page.resource, newtags, when=when)
            return True
        return False

    def _add_jtransform(self, req, filter_lst):
        add_script_data(req, {'tags_filter': filter_lst})
        add_script(req, 'tags/js/tags_jtransform.js')

    def _post_process_request_wiki_edit(self, req):
        tags = ' '.join(self._page_tags(req))
        # TRANSLATOR: Label text for link to '/tags'.
        link = tag.a(_("view all tags"), href=req.href.tags())
        # TRANSLATOR: ... (view all tags)
        insert = tag(
            tag_("Tag under: (%(tags_link)s)", tags_link=link),
            tag.br(),
            tag.input(id='tags', type='text', name='tags', size='50',
                      value=req.args.get('tags', tags))
        )
        insert = tag.div(tag.label(insert), class_='field')
        filter_lst = []
        # xpath = //div[@id="changeinfo1"]
        xform = JTransformer('div#changeinfo1')
        filter_lst.append(xform.append(Markup(insert)))
        self._add_jtransform(req, filter_lst)

    def _post_process_request_wiki_history(self, req):
        filter_lst = []
        # xpath = '//input[@type="radio" and @value="*"]'
        xform = JTransformer('input[type="radio"][value="*"]')
        filter_lst.append(xform.remove())
        self._add_jtransform(req, filter_lst)

    def _wiki_to_oneliner(self, context, wiki, shorten=None):
        if isinstance(wiki, Fragment):
            return wiki
        return format_to_oneliner(self.env, context, wiki, shorten=shorten)


class TagWikiSyntaxProvider(Component):
    """[opt] Provides tag:<expr> links.

    This extends TracLinks via WikiFormatting to point at tag queries or
    at specific tags.
    """

    implements(IWikiSyntaxProvider)

    # IWikiSyntaxProvider methods

    def get_wiki_syntax(self):
        """Additional syntax for quoted tags or tag expression."""
        tag_expr = (
            r"(%s)" % (WikiParser.QUOTED_STRING)
            )

        # Simple (tag|tagged):link syntax
        yield (r'''(?P<qualifier>tag(?:ged)?):(?P<tag_expr>%s)''' % tag_expr,
               lambda f, ns, match: self._format_tagged(
                   f, match.group('qualifier'), match.group('tag_expr'),
                   '%s:%s' % (match.group('qualifier'),
                              match.group('tag_expr'))))

        # [(tag|tagged):link with label]
        yield (r'''\[tag(?:ged)?:'''
               r'''(?P<ltag_expr>%s)\s*(?P<tag_title>[^\]]+)?\]''' % tag_expr,
               lambda f, ns, match: self._format_tagged(f, 'tag',
                                    match.group('ltag_expr'),
                                    match.group('tag_title')))

    def get_link_resolvers(self):
        return [('tag', self._format_tagged),
                ('tagged', self._format_tagged)]

    # Internal methods

    @lazy
    def tag_system(self):
        return TagSystem(self.env)

    def _format_tagged(self, formatter, ns, target, label, fullmatch=None):
        """Tag and tag query expression link formatter."""

        def unquote(text):
            """Strip all matching pairs of outer quotes from string."""
            while re.match(WikiParser.QUOTED_STRING, text):
                # Remove outer whitespace after stripped quotation too.
                text = text[1:-1].strip()
            return text

        label = label and unquote(label.strip()) or ''
        target = unquote(target.strip())

        query = target
        # Pop realms from query expression.
        all_realms = self.tag_system.get_taggable_realms(formatter.perm)
        realms = query_realms(target, all_realms)
        if realms:
            kwargs = dict((realm, 'on') for realm in realms)
            target = re.sub(r'(^|\W)realm:\S+(\W|$)', ' ', target).strip()
        else:
            kwargs = {}

        tag_res = Resource('tag', target)
        if 'TAGS_VIEW' not in formatter.perm(tag_res):
            return tag.span(label, class_='forbidden tags',
                            title=_("no permission to view tags"))

        context = formatter.context
        href = self.tag_system.get_resource_url(tag_res, context.href, kwargs)
        if all_realms and (
                target in self.tag_system.get_all_tags(formatter.req) or
                not iter_is_empty(self.tag_system.query(formatter.req,
                                                        query))):
            # At least one tag provider is available and tag exists or
            # tags query yields at least one match.
            if label:
                return tag.a(label, href=href)
            return render_resource_link(self.env, context, tag_res)

        return tag.a(label+'?', href=href, class_='missing tags',
                     rel='nofollow')


def iter_is_empty(i):
    """Test for empty iterator without consuming more than first element."""
    try:
        next_iter(i)
    except StopIteration:
        return True
    except InvalidQuery:
        return True
    return False
