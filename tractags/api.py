# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2011-2014 Steffen Hoffmann <hoff.st@web.de>
# Copyright (C) 2014 Jun Omae <jun66j5@gmail.com>
# Copyright (C) 2014 Ryan J Ollos <ryan.j.ollos@gmail.com>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import collections
import pkg_resources
import re
import threading

from trac.config import BoolOption, ListOption, Option
from trac.core import Component, ExtensionPoint, Interface, TracError
from trac.core import implements
from trac.perm import IPermissionPolicy, IPermissionRequestor
from trac.perm import PermissionError, PermissionSystem
from trac.resource import IResourceManager, get_resource_url
from trac.resource import get_resource_description
from trac.util import get_reporter_id
from trac.util.text import to_unicode
from trac.util.translation import domain_functions
from trac.wiki.model import WikiPage

# Import translation functions.
add_domain, _, N_, gettext, ngettext, tag_, tagn_ = \
    domain_functions('tractags', ('add_domain', '_', 'N_', 'gettext',
                                  'ngettext', 'tag_', 'tagn_'))
dgettext = None

from tractags.model import resource_tags, tag_frequency, tag_resource
from tractags.model import tagged_resources
# Now call module importing i18n methods from here.
from tractags.query import *

REALM_RE = re.compile('realm:(\w+)', re.U | re.I)


class InvalidTagRealm(TracError):
    pass


class ITagProvider(Interface):
    """The interface for Components providing per-realm tag storage and
    manipulation methods.

    Change comments and reparenting are supported since tags-0.7.
    """
    def get_taggable_realm():
        """Return the realm this provider supports tags on."""

    def get_tagged_resources(req, tags=None, filter=None):
        """Return a sequence of resources and *all* their tags.

        :param tags: If provided, return only those resources with the given
                     tags.
        :param filter: If provided, skip matching resources.

        :rtype: Sequence of (resource, tags) tuples.
        """

    def get_all_tags(req, filter=None):
        """Return all tags with numbers of occurance.

        :param filter: If provided, skip matching resources.

        :rtype: Counter object (dict sub-class: {tag_name: tag_frequency} ).

        """

    def get_resource_tags(req, resource, when=None):
        """Get tags for a Resource object."""

    def resource_tags(resource):
        """Get tags for a Resource object skipping permission checks."""

    def set_resource_tags(req, resource, tags, comment=u'', when=None):
        """Set tags for a resource."""

    def reparent_resource_tags(req, resource, old_id, comment=u''):
        """Move tags, typically when renaming an existing resource."""

    def remove_resource_tags(req, resource, comment=u''):
        """Remove all tags from a resource."""

    def describe_tagged_resource(req, resource):
        """Return a one line description of the tagged resource."""


class DefaultTagProvider(Component):
    """An abstract base tag provider that stores tags in the database.

    Use this if you need storage for your tags. Simply set the class variable
    `realm` and optionally `check_permission()`.

    See tractags.wiki.WikiTagProvider for an example.
    """

    implements(ITagProvider)

    abstract = True

    # Resource realm this provider manages tags for. Set this.
    realm = None

    revisable = False

    def __init__(self):
        # Do this once, because configuration lookups are costly.
        cfg = self.env.config
        self.revisable = self.realm in cfg.getlist('tags', 'revisable_realms')

    # Public methods

    def check_permission(self, perm, action):
        """Delegate function for checking permissions.

        Override to implement custom permissions. Defaults to TAGS_VIEW and
        TAGS_MODIFY.
        """
        map = {'view': 'TAGS_VIEW', 'modify': 'TAGS_MODIFY'}
        return map[action] in perm('tag')

    # ITagProvider methods

    def get_taggable_realm(self):
        return self.realm

    def get_tagged_resources(self, req, tags=None, filter=None):
        if not self.check_permission(req.perm, 'view'):
            return
        return tagged_resources(self.env, self.check_permission, req.perm,
                                self.realm, tags, filter)

    def get_all_tags(self, req, filter=None):
        all_tags = collections.Counter()
        for tag, count in tag_frequency(self.env, self.realm, filter):
            all_tags[tag] = count
        return all_tags

    def get_resource_tags(self, req, resource, when=None):
        assert resource.realm == self.realm
        if not self.check_permission(req.perm(resource), 'view'):
            return
        return resource_tags(self.env, resource, when=when)

    def resource_tags(self, resource):
        assert resource.realm == self.realm
        return resource_tags(self.env, resource)

    def set_resource_tags(self, req, resource, tags, comment=u'', when=None):
        assert resource.realm == self.realm
        if not self.check_permission(req.perm(resource), 'modify'):
            raise PermissionError(resource=resource, env=self.env)
        tag_resource(self.env, resource, author=self._get_author(req),
                     tags=tags, log=self.revisable, when=when)

    def reparent_resource_tags(self, req, resource, old_id, comment=u''):
        assert resource.realm == self.realm
        if not self.check_permission(req.perm(resource), 'modify'):
            raise PermissionError(resource=resource, env=self.env)
        tag_resource(self.env, resource, old_id, self._get_author(req),
                     log=self.revisable)

    def remove_resource_tags(self, req, resource, comment=u''):
        assert resource.realm == self.realm
        if not self.check_permission(req.perm(resource), 'modify'):
            raise PermissionError(resource=resource, env=self.env)
        tag_resource(self.env, resource, author=self._get_author(req),
                     log=self.revisable)

    def describe_tagged_resource(self, req, resource):
        raise NotImplementedError

    def _get_author(self, req):
        return get_reporter_id(req, 'author')


class TagPolicy(Component):
    """[extra] Security policy based on tags."""

    implements(IPermissionPolicy)

    def check_permission(self, action, username, resource, perm):
        if resource is None or action.split('_')[0] != resource.realm.upper():
            return None

        from tractags.api import TagSystem

        class FakeRequest(object):
            def __init__(self, perm):
                self.perm = perm

        permission = action.lower().split('_')[1]
        req = FakeRequest(perm)
        tags = TagSystem(self.env).get_tags(None, resource)

        # Explicitly denied?
        if ':-'.join((username, permission)) in tags:
            return False

        # Find all granted permissions for the requesting user from
        # tagged permissions by expanding any meta action as well.
        if action in set(PermissionSystem(self.env).expand_actions(
                         ['_'.join([resource.realm, t.split(':')[1]]).upper()
                          for t in tags if t.split(':')[0] == username])):
            return True


class TagSystem(Component):
    """[main] Tagging system for Trac.

    Associating resources with tags is easy, faceted content classification.

    Available components are marked according to their relevance as follows:

     `[main]`:: provide core with a generic tagging engine as well as support
     for common realms 'ticket' (TracTickets) and 'wiki' (TracWiki).
     `[opt]`:: add more features to improve user experience and maintenance
     `[extra]`:: enable advanced features for specific use cases

    Make sure to understand their purpose before deactivating `[main]` or
    activating `[extra]` components.
    """

    implements(IPermissionRequestor, IResourceManager)

    tag_providers = ExtensionPoint(ITagProvider)

    revisable = ListOption('tags', 'revisable_realms', 'wiki',
        doc="Comma-separated list of realms requiring tag change history.")
    wiki_page_link = BoolOption('tags', 'wiki_page_link', True,
        doc="Link a tag to the wiki page with same name, if it exists.")
    wiki_page_prefix = Option('tags', 'wiki_page_prefix', '',
        doc="Prefix for tag wiki page names.")

    # Internal variables
    _realm_provider_map = None

    def __init__(self):
        # Bind the 'tractags' catalog to the specified locale directory.
        locale_dir = pkg_resources.resource_filename(__name__, 'locale')
        add_domain(self.env.path, locale_dir)

        self._populate_provider_map()

    # Public methods

    def query(self, req, query='', attribute_handlers=None):
        """Returns a sequence of (resource, tags) tuples matching a query.

        Query syntax is described in tractags.query.

        :param attribute_handlers: Register additional query attribute
                                   handlers. See Query documentation for more
                                   information.
        """
        def realm_handler(_, node, context):
            return query.match(node, [context.realm])

        all_attribute_handlers = {
            'realm': realm_handler,
        }
        all_attribute_handlers.update(attribute_handlers or {})
        query = Query(query, attribute_handlers=all_attribute_handlers)
        providers = set()
        for m in REALM_RE.finditer(query.as_string()):
            realm = m.group(1)
            providers.add(self._get_provider(realm))
        if not providers:
            providers = self.tag_providers

        query_tags = set(query.terms())
        for provider in providers:
            self.env.log.debug('Querying ' + repr(provider))
            for resource, tags in provider.get_tagged_resources(req,
                                                          query_tags) or []:
                if query(tags, context=resource):
                    yield resource, tags

    def get_taggable_realms(self, perm=None):
        """Returns the names of available taggable realms as set.

        If a `PermissionCache` object is passed as optional `perm` argument,
        permission checks will be done for tag providers that have a
        `check_permission` method.
        """
        return set(p.get_taggable_realm()
                   for p in self.tag_providers
                   if perm is None or not hasattr(p, 'check_permission') or
                       p.check_permission(perm, 'view'))

    def get_all_tags(self, req, realms=[]):
        """Get all tags for all supported realms or only for specified ones.

        Returns a Counter object (special dict) with tag name as key and tag
        frequency as value.
        """
        all_tags = collections.Counter()
        all_realms = self.get_taggable_realms(req.perm)
        if not realms or set(realms) == all_realms:
            realms = all_realms
        for provider in self.tag_providers:
            if provider.get_taggable_realm() in realms:
                try:
                    all_tags += provider.get_all_tags(req)
                except AttributeError:
                    # Fallback for older providers.
                    try:
                        for resource, tags in \
                            provider.get_tagged_resources(req):
                                all_tags.update(tags)
                    except TypeError:
                        # Defense against loose ITagProvider implementations,
                        # that might become obsolete in the future.
                        self.env.log.warning('ITagProvider %r has outdated'
                                             'get_tagged_resources() method' %
                                             provider)
        return all_tags

    def get_tags(self, req, resource, when=None):
        """Get tags for resource."""
        if not req:
            # Bypass permission checks as required i. e. for TagsPolicy,
            # an IPermissionProvider.
            return set(self._get_provider(resource.realm) \
                       .resource_tags(resource))
        return set(self._get_provider(resource.realm) \
                   .get_resource_tags(req, resource, when=when))

    def set_tags(self, req, resource, tags, comment=u'', when=None):
        """Set tags on a resource.

        Existing tags are replaced.
        """
        try:
            return self._get_provider(resource.realm) \
                   .set_resource_tags(req, resource, set(tags), comment, when)
        except TypeError:
            # Handle old style tag providers gracefully.
            return self._get_provider(resource.realm) \
                   .set_resource_tags(req, resource, set(tags))

    def add_tags(self, req, resource, tags, comment=u''):
        """Add to existing tags on a resource."""
        tags = set(tags)
        tags.update(self.get_tags(req, resource))
        try:
            self.set_tags(req, resource, tags, comment)
        except TypeError:
            # Handle old style tag providers gracefully.
            self.set_tags(req, resource, tags)

    def reparent_tags(self, req, resource, old_name, comment=u''):
        """Move tags, typically when renaming an existing resource.

        Tags can't be moved between different tag realms with intention.
        """
        provider = self._get_provider(resource.realm)
        provider.reparent_resource_tags(req, resource, old_name, comment)

    def replace_tag(self, req, old_tags, new_tag=None, comment=u'',
                    allow_delete=False, filter=[]):
        """Replace one or more tags in all resources it exists/they exist in.

        Tagged resources may be filtered by realm and tag deletion is
        optionally allowed for convenience as well.
        """
        # Provide list regardless of attribute type.
        for provider in [p for p in self.tag_providers
                         if not filter or p.get_taggable_realm() in filter]:
            for resource, tags in \
                    provider.get_tagged_resources(req, old_tags):
                old_tags = set(old_tags)
                if old_tags.issuperset(tags) and not new_tag:
                    if allow_delete:
                        self.delete_tags(req, resource, None, comment)
                else:
                    s_tags = set(tags)
                    eff_tags = s_tags - old_tags
                    if new_tag:
                        eff_tags.add(new_tag)
                    # Prevent to touch resources without effective change.
                    if eff_tags != s_tags and (allow_delete or new_tag):
                        self.set_tags(req, resource, eff_tags, comment)

    def delete_tags(self, req, resource, tags=None, comment=u''):
        """Delete tags on a resource.

        If tags is None, remove all tags on the resource.
        """
        provider = self._get_provider(resource.realm)
        if tags is None:
            try:
                provider.remove_resource_tags(req, resource, comment)
            except TypeError:
                 # Handle old style tag providers gracefully.
                provider.remove_resource_tags(req, resource)
        else:
            current_tags = set(provider.get_resource_tags(req, resource))
            current_tags.difference_update(tags)
            try:
                provider.set_resource_tags(req, resource, current_tags,
                                           comment)
            except TypeError:
                 # Handle old style tag providers gracefully.
                provider.set_resource_tags(req, resource, current_tags)

    def describe_tagged_resource(self, req, resource):
        """Returns a short description of a taggable resource."""
        provider = self._get_provider(resource.realm)
        try:
            return provider.describe_tagged_resource(req, resource)
        except (AttributeError, NotImplementedError):
            # Fallback to resource provider method.
            self.env.log.info('ITagProvider %r does not implement '
                              'describe_tagged_resource()' % provider)
            return get_resource_description(self.env, resource, 'summary')

    # IPermissionRequestor method
    def get_permission_actions(self):
        action = ['TAGS_VIEW', 'TAGS_MODIFY']
        actions = [action[0], (action[1], [action[0]]),
                   ('TAGS_ADMIN', action)]
        return actions

    # IResourceManager methods

    def get_resource_realms(self):
        yield 'tag'

    def get_resource_url(self, resource, href, form_realms=None, **kwargs):
        if self.wiki_page_link:
            page = WikiPage(self.env, self.wiki_page_prefix + resource.id)
            if page.exists:
                return get_resource_url(self.env, page.resource, href,
                                        **kwargs)
        if form_realms:
            return href.tags(form_realms, q=unicode(resource.id), **kwargs)
        return href.tags(unicode(resource.id), form_realms, **kwargs)

    def get_resource_description(self, resource, format='default',
                                 context=None, **kwargs):
        if self.wiki_page_link:
            page = WikiPage(self.env, self.wiki_page_prefix + resource.id)
            if page.exists:
                return get_resource_description(self.env, page.resource,
                                                format, **kwargs)
        rid = to_unicode(resource.id)
        if format in ('compact', 'default'):
            return rid
        else:
            return u'tag:%s' % rid

    # Internal methods

    def _populate_provider_map(self):
        if self._realm_provider_map is None:
            # Only use the map once it is fully initialized.
            map = dict((provider.get_taggable_realm(), provider)
                       for provider in self.tag_providers)
            self._realm_provider_map = map

    def _get_provider(self, realm):
        try:
            return self._realm_provider_map[realm]
        except KeyError:
            raise InvalidTagRealm(_("Tags are not supported on the '%s' realm")
                                  % realm)


class RequestsProxy(object):

    def __init__(self):
        self.current = threading.local()

    def get(self):
        try:
            return self.current.req
        except:
            return None

    def set(self, req):
        self.current.req = req

    def reset(self):
        self.current.req = None


requests = RequestsProxy()
