# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from trac.core import Component, implements
from trac.resource import Resource, ResourceNotFound, resource_exists

from tracrpc.api import IXMLRPCHandler

from tractags.api import TagSystem
from tractags.util import split_into_tags


class TagRPC(Component):
    """[extra] RPC interface for the tag system.

    Access Trac resource tagging system through methods provided by
    [https://trac-hacks.org/wiki/XmlRpcPlugin XmlRpcPlugin].
    """

    implements(IXMLRPCHandler)

    def __init__(self):
        self.tag_system = TagSystem(self.env)

    # IXMLRPCHandler methods

    def xmlrpc_namespace(self):
        return 'tags'

    def xmlrpc_methods(self):
        yield (None, ((list, str),), self.splitIntoTags)
        yield ('TAGS_VIEW', ((list,),), self.getTaggableRealms)
        yield ('TAGS_VIEW', ((dict,), (dict, list)), self.getAllTags)
        yield ('TAGS_VIEW', ((list, str, str),), self.getTags)
        yield ('TAGS_VIEW', ((list, str),), self.query)
        yield ('TAGS_MODIFY', ((list, str, str, list),
                               (list, str, str, list, str)), self.addTags)
        yield ('TAGS_MODIFY', ((list, str, str, list),
                               (list, str, str, list, str)), self.setTags)

    # Exported functions and TagSystem methods

    def addTags(self, req, realm, id, tags, comment=u''):
        """Add the supplied list of tags to a taggable Trac resource.

        Returns the updated list of resource tags.
        """
        resource = Resource(realm, id)
        # Replicate TagSystem.add_tags() method due to xmlrpclib issue.
        tags = set(tags)
        tags.update(self._get_tags(req, resource))
        self.tag_system.set_tags(req, resource, tags, comment)
        return self._get_tags(req, resource)

    def getAllTags(self, req, realms=[]):
        """Returns a dict of all tags as keys and occurrences as values.

        If a realm list is supplied, only tags from these taggable realms
        are shown.
        """
        # Type conversion needed for content transfer of Counter object.
        return dict(self.tag_system.get_all_tags(req, realms))

    def getTaggableRealms(self, req):
        """Returns the list of taggable Trac realms."""
        return list(self.tag_system.get_taggable_realms())

    def getTags(self, req, realm, id):
        """Returns the list of tags for a Trac resource."""
        return self._get_tags(req, Resource(realm, id))

    def query(self, req, query_str):
        """Returns a list of tagged Trac resources, whose tags match the
        supplied tag query expression.
        """
        # Type conversion needed for content transfer of Python set objects.
        return [(resource.realm, resource.id, list(tags))
                for resource, tags in self.tag_system.query(req, query_str)]

    def setTags(self, req, realm, id, tags, comment=u''):
        """Replace tags for a Trac resource with the supplied list of tags.

        Returns the updated list of resource tags.
        """
        resource = Resource(realm, id)
        self._get_tags(req, resource) # Trac resource exists?
        self.tag_system.set_tags(req, resource, tags, comment)
        return self._get_tags(req, resource)

    def splitIntoTags(self, req, tag_str):
        """Returns a list of tags from a string.

        Comma, whitespace and combinations of these characters are recognized
        as delimiter, that get stripped from the output.
        """
        return split_into_tags(tag_str)

    # Private methods

    def _get_tags(self, req, resource):
        if not resource_exists(self.env, resource):
            raise ResourceNotFound('Resource "%r" does not exists' % resource)
        # Workaround for ServiceException when calling TagSystem.get_tags().
        provider = [p for p in self.tag_system.tag_providers
                    if p.get_taggable_realm() == resource.realm][0]
        # Type conversion needed for content transfer of Python set objects.
        return list(provider.get_resource_tags(req, resource))
