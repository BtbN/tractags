# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2011 Itamar Ostricher <itamarost@gmail.com>
# Copyright (C) 2011-2015 Steffen Hoffmann <hoff.st@web.de>
# Copyright (C) 2015 Ryan J Ollos <ryan.j.ollos@gmail.com>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re

from fnmatch import fnmatchcase
from pkg_resources import resource_filename

from trac.config import BoolOption, ListOption, Option
from trac.core import Component, TracError, implements
from trac.resource import Resource, get_resource_url, render_resource_link
from trac.ticket.api import TicketSystem
from trac.ticket.model import Ticket
from trac.util import as_int, embedded_numbers
from trac.util.html import html as builder
from trac.util.presentation import Paginator
from trac.util.text import shorten_line, to_unicode
from trac.web.chrome import Chrome, ITemplateProvider, add_link, \
                            add_stylesheet
from trac.wiki.api import IWikiMacroProvider, parse_args
from trac.wiki.formatter import format_to_oneliner, system_message

from tractags.api import Counter, InvalidTagRealm, TagSystem, N_, _, gettext
from tractags.query import InvalidQuery
from tractags.util import query_realms

# Check for unsupported pre-tags-0.6 macro keyword arguments.
_OBSOLETE_ARGS_RE = re.compile(r"""
    (expression|operation|showheadings|tagspace|tagspaces)=
    """, re.VERBOSE)


class TagTemplateProvider(Component):
    """Provides templates and static resources for the tags plugin."""

    implements(ITemplateProvider)

    abstract = True

    # ITemplateProvider methods
    def get_templates_dirs(self):
        """Return the absolute path of the directory containing the provided
        Genshi templates.
        """
        return [resource_filename(__name__, 'templates')]

    def get_htdocs_dirs(self):
        """Return the absolute path of a directory containing additional
        static resources (such as images, style sheets, etc).
        """
        return [('tags', resource_filename(__name__, 'htdocs'))]


class TagWikiMacros(TagTemplateProvider):
    """[opt] Provides macros, that utilize the tag system in wiki markup."""

    implements(IWikiMacroProvider)

    caseless_sort = BoolOption('tags', 'cloud_caseless_sort', default=False,
        doc="Whether the tag cloud should be sorted case-sensitive.")
    default_cols = Option('tags', 'listtagged_default_table_cols',
        'id|description|tags',
        doc="Select columns and column order for table format.\n\n"
            "See `ListTagged` description (WikiMacros) for supported values.")
    default_format = Option('tags', 'listtagged_default_format', 'oldlist',
        doc="Set default format for the handler of the `/tags` domain.\n\n"
            "See `ListTagged` description (WikiMacros) for supported values.")
    exclude_realms = ListOption('tags', 'listtagged_exclude_realms', [],
        doc="Comma-separated list of realms to exclude from tags queries "
            "by default, unless specifically included using 'realm:<realm>' "
            "in a query.")
    items_per_page = Option('tags', 'listtagged_items_per_page', 100,
        doc="Number of tagged resources displayed per page of tag query "
            "results requested by `ListTagged` macros and from `/tags`.")
    items_per_page = as_int(items_per_page, 100)
    supported_cols = frozenset(['realm', 'id', 'description', 'tags'])

    def __init__(self):
        # TRANSLATOR: Keep macro doc style formatting here, please.
        self.doc_cloud = N_("""Display a tag cloud.

    Show a tag cloud for all tags on resources matching query.

    Usage:

    {{{
    [[TagCloud(<query>[,caseless_sort=<bool>][,mincount=<n>])]]
    }}}
    caseless_sort::
      Whether the tag cloud should be sorted case-sensitive.
    mincount::
      Optional integer threshold to hide tags with smaller count.

    See tags documentation for the query syntax.
    """)
        self.doc_listtagged = N_("""List tagged resources.

    Usage:

    {{{
    [[ListTagged(<query>[,exclude=<list>],[[format=<format>],cols=<columns>])]]
    }}}
    format::
      result list presentation; supported values:

    || `compact` || comma-separated inline list of "linked-description" ||
    || `oldlist` (default) || " * linked-id description (tags)" list ||
    || `table` || table... (see corresponding column option too) ||
    || `short` or other value || bulleted list of "linked-description" ||
    cols::
      columns for 'table' format using a "|"-separated list of column names
      (order matters); supported columns: realm, id, description, tags
    exclude::
      exclude tagged resources that match a name in the colon-separated list
      of resource ids, accepts shell-style patterns

    See tags documentation for the query syntax.
    """)

    # IWikiMacroProvider

    def get_macros(self):
        yield 'ListTagged'
        yield 'TagCloud'

    def get_macro_description(self, name):
        if name == 'ListTagged':
            return gettext(self.doc_listtagged)
        if name == 'TagCloud':
            return gettext(self.doc_cloud)

    def expand_macro(self, formatter, name, content, realms=[]):
        """Evaluate macro call and render results.

        Calls from web-UI come with pre-processed realm selection.
        """
        env = self.env
        req = formatter.req
        tag_system = TagSystem(env)

        all_realms = tag_system.get_taggable_realms()
        if not all_realms:
            # Tag providers are required, no result without at least one.
            return ''
        args, kw = parse_args(content)

        query = args and args[0].strip() or None
        if not realms:
            # Check macro arguments for realms (typical wiki macro call).
            realms = 'realm' in kw and kw['realm'].split('|') or []
        if query:
            # Add realms from query expression.
            realms.extend(query_realms(query, all_realms))
            # Remove redundant realm selection for performance.
            if set(realms) == all_realms:
                query = re.sub('(^|\W)realm:\S+(\W|$)', ' ', query).strip()
        if name == 'TagCloud':
            # Set implicit 'all tagged realms' as default.
            if not realms:
                realms = all_realms
            if query:
                all_tags = Counter()
                # Require per resource query including view permission checks.
                for resource, tags in tag_system.query(req, query):
                    all_tags.update(tags)
            else:
                # Allow faster per tag query, side steps permission checks.
                all_tags = tag_system.get_all_tags(req, realms=realms)
            mincount = 'mincount' in kw and kw['mincount'] or None
            return self.render_cloud(req, all_tags,
                                     caseless_sort=self.caseless_sort,
                                     mincount=mincount, realms=realms)
        elif name == 'ListTagged':
            if content and _OBSOLETE_ARGS_RE.search(content):
                data = {'warning': 'obsolete_args'}
            else:
                data = {'warning': None}
            context = formatter.context
            # Use TagsQuery arguments (most likely wiki macro calls).
            cols = 'cols' in kw and kw['cols'] or self.default_cols
            format = 'format' in kw and kw['format'] or self.default_format
            if not realms:
                # Apply ListTagged defaults to macro call w/o realm.
                realms = list(set(all_realms)-set(self.exclude_realms))
                if not realms:
                    return ''
            query = '(%s) (%s)' % (query or '', ' or '.join(['realm:%s' % (r)
                                                             for r in realms]))
            query_result = tag_system.query(req, query)
            excludes = [exc.strip()
                        for exc in kw.get('exclude', '' ).split(':')
                        if exc.strip()]
            if excludes and query_result:
                filtered_result = [(resource, tags)
                                   for resource, tags in query_result
                                   if not any(fnmatchcase(resource.id, exc)
                                              for exc in excludes)]
                query_result = filtered_result
            if not query_result:
                return ''

            def _link(resource):
                if resource.realm == 'tag':
                    # Keep realm selection in tag links.
                    return builder.a(resource.id,
                                     href=self.get_href(req, realms,
                                                        tag=resource))
                elif resource.realm == 'ticket':
                    # Return resource link including ticket status dependend
                    #   class to allow for common Trac ticket link style.
                    ticket = Ticket(env, resource.id)
                    return builder.a('#%s' % ticket.id,
                                     class_=ticket['status'],
                                     href=formatter.href.ticket(ticket.id),
                                     title=shorten_line(ticket['summary']))
                return render_resource_link(env, context, resource, 'compact')

            if format == 'table':
                cols = [col for col in cols.split('|')
                        if col in self.supported_cols]
                # Use available translations from Trac core.
                try:
                    labels = TicketSystem(env).get_ticket_field_labels()
                    labels['id'] = _('Id')
                except AttributeError:
                    # Trac 0.11 neither has the attribute nor uses i18n.
                    labels = {'id': 'Id', 'description': 'Description'}
                labels['realm'] = _('Realm')
                labels['tags'] = _('Tags')
                headers = [{'label': labels.get(col)}
                           for col in cols]
                data.update({'cols': cols,
                             'headers': headers})

            try:
                results = sorted(query_result, key=lambda r:
                                 embedded_numbers(to_unicode(r[0].id)))
            except (InvalidQuery, InvalidTagRealm), e:
                return system_message(_("ListTagged macro error"), e)
            results = self._paginate(req, results, realms)
            rows = []
            for resource, tags in results:
                desc = tag_system.describe_tagged_resource(req, resource)
                tags = sorted(tags)
                wiki_desc = format_to_oneliner(env, context, desc)
                if tags:
                    rendered_tags = [_link(Resource('tag', tag))
                                     for tag in tags]
                    if 'oldlist' == format:
                        resource_link = _link(resource)
                    else:
                        resource_link = builder.a(wiki_desc,
                                                  href=get_resource_url(
                                                  env, resource, context.href))
                        if 'table' == format:
                            cells = []
                            for col in cols:
                                if col == 'id':
                                    cells.append(_link(resource))
                                # Don't duplicate links to resource in both.
                                elif col == 'description' and 'id' in cols:
                                    cells.append(wiki_desc)
                                elif col == 'description':
                                    cells.append(resource_link)
                                elif col == 'realm':
                                    cells.append(resource.realm)
                                elif col == 'tags':
                                    cells.append(
                                        builder([(tag, ' ')
                                                 for tag in rendered_tags]))
                            rows.append({'cells': cells})
                            continue
                rows.append({'desc': wiki_desc,
                             'rendered_tags': None,
                             'resource_link': _link(resource)})
            data.update({'format': format,
                         'paginator': results,
                         'results': rows,
                         'tags_url': req.href('tags')})

            # Work around a bug in trac/templates/layout.html, that causes a
            # TypeError for the wiki macro call, if we use add_link() alone.
            add_stylesheet(req, 'common/css/search.css')

            return Chrome(env).render_template(
                req, 'listtagged_results.html', data, 'text/html', True)

    def get_href(self, req, realms, query=None, per_page=None, page=None,
                 tag=None, **kwargs):
        """Prepare href objects for tag links and pager navigation.

        Generate form-related arguments, strip arguments with default values.
        """
        # Prepare realm arguments to keep form data consistent.
        form_realms = dict((realm, 'on') for realm in realms)
        if not page and not per_page:
            # We're not serving pager navigation here.
            return get_resource_url(self.env, tag, req.href,
                                    form_realms=form_realms, **kwargs)
        if page == 1:
            page = None
        if per_page == self.items_per_page:
            per_page = None
        return req.href(req.path_info, form_realms, q=query,
                        realms=realms, listtagged_per_page=per_page,
                        listtagged_page=page, **kwargs)

    def render_cloud(self, req, cloud, renderer=None, caseless_sort=False,
                     mincount=None, realms=()):
        """Render a tag cloud.

        :cloud: Dictionary of {object: count} representing the cloud.
        :param renderer: A callable with signature (tag, count, percent)
                         used to render the cloud objects.
        :param caseless_sort: Boolean, whether tag cloud should be sorted
                              case-sensitive.
        :param mincount: Integer threshold to hide tags with smaller count.
        """
        min_px = 10.0
        max_px = 30.0
        scale = 1.0

        if renderer is None:
            def default_renderer(tag, count, percent):
                href = self.get_href(req, realms, tag=Resource('tag', tag))
                return builder.a(tag, rel='tag', title='%i' % count,
                                 href=href, style='font-size: %ipx'
                                 % int(min_px + percent * (max_px - min_px)))
            renderer = default_renderer

        # A LUT from count to n/len(cloud)
        size_lut = dict([(c, float(i)) for i, c in
                         enumerate(sorted(set([r for r in cloud.values()])))])
        if size_lut:
            scale = 1.0 / len(size_lut)

        if caseless_sort:
            # Preserve upper-case precedence within similar tags.
            items = reversed(sorted(cloud.iteritems(),
                                    key=lambda t: t[0].lower(), reverse=True))
        else:
            items = sorted(cloud.iteritems())
        ul = li = None
        for i, (tag, count) in enumerate(items):
            percent = size_lut[count] * scale
            if mincount and count < as_int(mincount, 1):
                # Tag count is too low.
                continue
            if ul:
                # Found new tag for cloud; now add previously prepared one.
                ul('\n', li)
            else:
                # Found first tag for cloud; now create the list.
                ul = builder.ul(class_='tagcloud')
            # Prepare current tag entry.
            li = builder.li(renderer(tag, count, percent))
        if li:
            # All tags checked; mark latest tag as last one (no tailing colon).
            li(class_='last')
            ul('\n', li, '\n')
        return ul and ul or _("No tags found")

    def _paginate(self, req, results, realms):
        query = req.args.get('q', None)
        current_page = as_int(req.args.get('listtagged_page'), 1, min=1)
        items_per_page = as_int(req.args.get('listtagged_per_page'),
                                self.items_per_page)
        if items_per_page < 1:
            items_per_page = self.items_per_page
        try:
            result = Paginator(results, current_page - 1, items_per_page)
        except (AssertionError, TracError), e:
            # AssertionError raised in Trac < 1.0.10, TracError otherwise
            self.log.warn("ListTagged macro: %s", e)
            current_page = 1
            result = Paginator(results, current_page - 1, items_per_page)

        pagedata = []
        shown_pages = result.get_shown_pages(21)
        for page in shown_pages:
            page_href = self.get_href(req, realms, query, items_per_page, page)
            pagedata.append([page_href, None, str(page),
                             _("Page %(num)d", num=page)])

        attributes = ['href', 'class', 'string', 'title']
        result.shown_pages = [dict(zip(attributes, p)) for p in pagedata]

        result.current_page = {'href': None, 'class': 'current',
                               'string': str(result.page + 1), 'title': None}

        if result.has_next_page:
            next_href = self.get_href(req, realms, query, items_per_page,
                                      current_page + 1)
            add_link(req, 'next', next_href, _('Next Page'))

        if result.has_previous_page:
            prev_href = self.get_href(req, realms, query, items_per_page,
                                      current_page - 1)
            add_link(req, 'prev', prev_href, _('Previous Page'))
        return result
