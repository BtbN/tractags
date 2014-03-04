# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2011-2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re

from genshi.builder import Fragment, Markup, tag
from genshi.filters.transform import Transformer

from trac.config import BoolOption
from trac.core import Component, ExtensionPoint, implements
from trac.mimeview.api import Context
from trac.resource import Resource, render_resource_link, get_resource_url
from trac.util.compat import sorted
from trac.web.api import IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import add_stylesheet
from trac.wiki.api import IWikiChangeListener, IWikiPageManipulator
from trac.wiki.api import IWikiSyntaxProvider
from trac.wiki.formatter import format_to_oneliner
from trac.wiki.model import WikiPage
from trac.wiki.web_ui import WikiModule

from tractags.api import Counter, DefaultTagProvider, TagSystem, _, ngettext, \
                         tag_
from tractags.compat import to_utimestamp
from tractags.macros import TagTemplateProvider
from tractags.model import delete_tags, tag_changes
from tractags.query import Query
from tractags.util import split_into_tags


class WikiTagProvider(DefaultTagProvider):
    """Tag provider for Trac wiki."""

    realm = 'wiki'

    exclude_templates = BoolOption('tags', 'query_exclude_wiki_templates',
        default=True,
        doc="Whether tagged wiki page templates should be queried.")

    first_head = re.compile('=\s+([^=\n]*)={0,1}')

    def check_permission(self, perm, action):
        map = {'view': 'WIKI_VIEW', 'modify': 'WIKI_MODIFY'}
        return super(WikiTagProvider, self).check_permission(perm, action) \
            and map[action] in perm

    def get_tagged_resources(self, req, tags=None, filter=None):
        if self.exclude_templates:
            db = self.env.get_db_cnx()
            like_templates = ''.join(
                ["'", db.like_escape(WikiModule.PAGE_TEMPLATES_PREFIX), "%%'"])
            filter = (' '.join(['name NOT', db.like() % like_templates]),)
        return super(WikiTagProvider, self).get_tagged_resources(req, tags,
                                                                 filter)

    def get_all_tags(self, req, filter=None):
        if not self.check_permission(req.perm, 'view'):
            return
        if self.exclude_templates:
            db = self.env.get_db_cnx()
            like_templates = ''.join(
                ["'", db.like_escape(WikiModule.PAGE_TEMPLATES_PREFIX), "%%'"])
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
    """Implement the user interface for tagging Wiki pages."""
    implements(IRequestFilter, ITemplateStreamFilter,
               IWikiChangeListener, IWikiPageManipulator)

    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if req.method == 'GET' and req.path_info.startswith('/wiki/'):
            if req.args.get('action') == 'edit' and \
                    req.args.get('template') and 'tags' not in req.args:
                # Retrieve template resource to be queried for tags.
                template_page = WikiPage(self.env,''.join(
                                         [WikiModule.PAGE_TEMPLATES_PREFIX,
                                          req.args.get('template')]))
                if template_page and template_page.exists and \
                        'TAGS_VIEW' in req.perm(template_page.resource):
                    ts = TagSystem(self.env)
                    tags = sorted(ts.get_tags(req, template_page.resource))
                    # Prepare tags as content for the editor field.
                    tags_str = ' '.join(tags)
                    self.env.log.debug("Tags retrieved from template: '%s'" \
                                       % unicode(tags_str).encode('utf-8'))
                    # DEVEL: More arguments need to be propagated here?
                    req.redirect(req.href(req.path_info,
                                          action='edit', tags=tags_str,
                                          template=req.args.get('template')))
            if req.args.get('action') == 'history' and data and \
                    'history' in data:
                history = []
                page_history = data.get('history', [])
                resource = data['resource']
                tags_history = tag_changes(self.env, data['resource'])
                for i in range(len(page_history)):
                    while tags_history and \
                            tags_history[0][0] > page_history[i]['date']:
                        old_tags = split_into_tags(tags_history[0][2] or '')
                        new_tags = split_into_tags(tags_history[0][3] or '')
                        added = sorted(new_tags - old_tags)
                        removed = sorted(old_tags - new_tags)
                        comment = tag(tag.strong(_("Tags")), ' ')
                        if added:
                            comment.append(tag_(ngettext("%(tags)s added",
                                                         "%(tags)s added",
                                                         len(added)),
                                                tags=tag.em(', '.join(added))))
                        # TRANSLATOR: How to delimit added and removed tags.
                        if added and removed:
                            comment.append(_("; "))
                        if removed:
                            comment.append(tag_(ngettext("%(tags)s removed",
                                                         "%(tags)s removed",
                                                         len(removed)),
                                                tags=tag.em(', '.join(removed))))
                        date = tags_history[0][0]
                        history.append({
                            'version': '*',
                            'url': req.href(resource.realm, resource.id,
                                            version=page_history[i]['version'],
                                            tags_version=to_utimestamp(date)),
                            'date': date,
                            'author': tags_history[0][1],
                            'comment': comment,
                            'ipnr': ''
                        })
                        tags_history.pop(0)
                    history.append({
                        'version': page_history[i]['version'],
                        'date': page_history[i]['date'],
                        'author': page_history[i]['author'],
                        'comment': page_history[i]['comment'],
                        'ipnr': page_history[i]['ipnr']
                    })
                data.update(dict(history=history,
                                 wiki_to_oneliner=self._wiki_to_oneliner))
        return (template, data, content_type)

    # ITemplateStreamFilter methods
    def filter_stream(self, req, method, filename, stream, data):
        page_name = req.args.get('page', 'WikiStart')
        resource = Resource('wiki', page_name)
        if filename == 'wiki_view.html' and 'TAGS_VIEW' in req.perm(resource):
            return self._wiki_view(req, stream)
        elif filename == 'wiki_edit.html' and \
                         'TAGS_MODIFY' in req.perm(resource):
            return self._wiki_edit(req, stream)
        elif filename == 'history_view.html' and \
                         'TAGS_VIEW' in req.perm(resource):
            return self._wiki_history(req, stream)
        return stream

    # IWikiPageManipulator methods
    def prepare_wiki_page(self, req, page, fields):
        pass

    def validate_wiki_page(self, req, page):
        # If we're saving the wiki page, and can modify tags, do so.
        if req and 'TAGS_MODIFY' in req.perm(page.resource) \
                and req.path_info.startswith('/wiki') and 'save' in req.args:
            page_modified = req.args.get('text') != page.old_text or \
                    page.readonly != int('readonly' in req.args)
            # Always save tags if the page has been otherwise modified.
            if page_modified:
                self._update_tags(req, page)
            elif page.version > 0:
                # If the page hasn't been otherwise modified, save tags and
                # redirect to avoid the "page has not been modified" warning.
                if self._update_tags(req, page):
                    req.redirect(get_resource_url(self.env, page.resource,
                                                  req.href, version=None))
        return []

    # IWikiChangeListener methods
    def wiki_page_added(self, page):
        pass

    def wiki_page_changed(self, page, version, t, comment, author, ipnr):
        pass

    def wiki_page_renamed(self, page, old_name):
        """Called when a page has been renamed (since Trac 0.12)."""
        self.log.debug("Moving wiki page tags from %s to %s",
                       old_name, page.name)
        tag_system = TagSystem(self.env)
        # XXX Ugh. Hopefully this will be sufficient to fool any endpoints.
        from trac.test import Mock, MockPerm
        req = Mock(authname='anonymous', perm=MockPerm())
        tag_system.reparent_tags(req, Resource('wiki', page.name), old_name)

    def wiki_page_deleted(self, page):
        # Page gone, so remove all records on it.
        delete_tags(self.env, page.resource)

    def wiki_page_version_deleted(self, page):
        pass

    # Internal methods
    def _page_tags(self, req):
        pagename = req.args.get('page', 'WikiStart')
        version = req.args.get('version')
        tags_version = req.args.get('tags_version')

        page = WikiPage(self.env, pagename, version=version)
        resource = page.resource
        if version and not tags_version:
            tags_version = page.time
        tag_system = TagSystem(self.env)
        tags = sorted(tag_system.get_tags(req, resource, when=tags_version))
        return tags

    def _wiki_view(self, req, stream):
        add_stylesheet(req, 'tags/css/tractags.css')
        tags = self._page_tags(req)
        if not tags:
            return stream
        tag_system = TagSystem(self.env)
        li = []
        for tag_ in tags:
            resource = Resource('tag', tag_)
            anchor = render_resource_link(self.env,
                Context.from_request(req, resource), resource)
            anchor = anchor(rel='tag')
            li.append(tag.li(anchor, ' '))

        # TRANSLATOR: Header label text for tag list at wiki page bottom.
        insert = tag.ul(class_='tags')(tag.li(_("Tags"), class_='header'), li)
        return stream | Transformer('//div[contains(@class,"wikipage")]').after(insert)

    def _update_tags(self, req, page):
        tag_system = TagSystem(self.env)
        newtags = split_into_tags(req.args.get('tags', ''))
        oldtags = tag_system.get_tags(req, page.resource)

        if oldtags != newtags:
            tag_system.set_tags(req, page.resource, newtags)
            return True
        return False

    def _wiki_edit(self, req, stream):
        # TRANSLATOR: Label text for link to '/tags'.
        link = tag.a(_("view all tags"), href=req.href.tags())
        # TRANSLATOR: ... (view all tags)
        insert = tag(Markup(_("Tag under: (%(tags_link)s)", tags_link=link)))
        insert(
            tag.br(),
            tag.input(id='tags', type='text', name='tags', size='50',
                value=req.args.get('tags', ' '.join(self._page_tags(req))))
        )
        insert = tag.div(tag.label(insert), class_='field')
        return stream | Transformer('//div[@id="changeinfo1"]').append(insert)

    def _wiki_history(self, req, stream):
        xpath = '//input[@type="radio" and @value="*"]'
        stream = stream | Transformer(xpath).remove()
        # Remove invalid links to wiki page revisions (fix for Trac < 0.12).
        xpath = '//a[contains(@href,"%2A")]'
        return stream | Transformer(xpath).remove()

    def _wiki_to_oneliner(self, context, wiki, shorten=None):
        if isinstance(wiki, Fragment):
            return wiki
        return format_to_oneliner(self.env, context, wiki, shorten=shorten)


class TagWikiSyntaxProvider(Component):
    """Provide tag:<expr> links."""

    implements(IWikiSyntaxProvider)

    # IWikiSyntaxProvider methods
    def get_wiki_syntax(self):
        yield (r'''\[tag(?:ged)?:(?P<tlpexpr>'.*'|".*"|\S+)\s*(?P<tlptitle>[^\]]+)?\]''',
               lambda f, n, m: self._format_tagged(f,
                                    m.group('tlpexpr'),
                                    m.group('tlptitle')))
        yield (r'''(?P<tagsyn>tag(?:ged)?):(?P<texpr>(?:'.*?'|".*?"|\S)+)''',
               lambda f, n, m: self._format_tagged(f,
                                    m.group('texpr'),
                                    '%s:%s' % (m.group('tagsyn'), m.group('texpr'))))

    def get_link_resolvers(self):
        return []

    def _format_tagged(self, formatter, target, label):
        RE = re.compile(r'^(\\[\'"]*\'|\\[\'"]*\"|"|\')(.*)(\1)')
        iter_max = 5
        iter_run = 0
        for iter_run in range(0, iter_max):
            # Reduce outer quotations.
            ctarget = RE.sub(r'\2', target)
            iter_run += 1
            if ctarget == target or iter_run > iter_max:
                self.env.log.debug(' ,'.join([target, ctarget, str(iter_run)]))
                break
            target = ctarget
        if label:
            href = formatter.context.href
            url = get_resource_url(self.env, Resource('tag', target), href)
            return tag.a(label, href=url)
        return render_resource_link(self.env, formatter.context,
                                    Resource('tag', target))

