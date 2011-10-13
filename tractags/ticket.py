# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2011 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re

from trac.config import BoolOption, ListOption
from trac.core import Component, implements
from trac.resource import Resource
from trac.ticket.api import TicketSystem
from trac.ticket.model import Ticket
from trac.util import get_reporter_id
from trac.util.compat import set, sorted
from trac.util.text import to_unicode

from tractags.api import TagSystem, ITagProvider, _


class TicketTagProvider(Component):
    """A tag provider using ticket fields as sources of tags.

    Currently does NOT support custom fields.
    """
    implements(ITagProvider)

    fields = ListOption('tags', 'ticket_fields', 'keywords',
        doc=_("List of ticket fields to expose as tags."))

    ignore_closed_tickets = BoolOption('tags', 'ignore_closed_tickets', True,
        _("Do not collect tags from closed tickets."))

#    custom_fields = ListOption('tags', 'custom_ticket_fields',
#        doc=_("List of custom ticket fields to expose as tags."))

    # ITagProvider methods
    def get_taggable_realm(self):
        return 'ticket'

    def get_tagged_resources(self, req, tags):
        if 'TICKET_VIEW' not in req.perm:
            return

        split_into_tags = TagSystem(self.env).split_into_tags
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        args = []
        ignore = ''
        if self.ignore_closed_tickets:
            ignore = " WHERE status != 'closed'"
        sql = """
            SELECT *
              FROM (SELECT id, %s, %s AS std_fields
                      FROM ticket%s) s
            """ % (','.join(self.fields),
                   '||'.join(["COALESCE(%s, '')" % f for f in self.fields]),
                   ignore)
        constraints = []
        if tags:
            constraints.append(
                "(" + ' OR '.join(["std_fields LIKE %s" for t in tags]) + ")")
            args += ['%' + t + '%' for t in tags]
        else:
            constraints.append("std_fields != ''")

        if constraints:
            sql += " WHERE " + " AND ".join(constraints)
        sql += " ORDER BY id"
        self.env.log.debug(sql)
        cursor.execute(sql, args)
        for row in cursor:
            id, ttags = row[0], ' '.join([f for f in row[1:-1] if f])
            perm = req.perm('ticket', id)
            if 'TICKET_VIEW' not in perm or 'TAGS_VIEW' not in perm:
                continue
            ticket_tags = split_into_tags(ttags)
            tags = set([to_unicode(x) for x in tags])
            if (not tags or ticket_tags.intersection(tags)):
                yield Resource('ticket', id), ticket_tags


    def get_resource_tags(self, req, resource):
        if 'TICKET_VIEW' not in req.perm(resource):
            return
        ticket = Ticket(self.env, resource.id)
        return self._ticket_tags(ticket)

    def set_resource_tags(self, req, resource, tags, comment=u''):
        req.perm.require('TICKET_MODIFY', resource)
        split_into_tags = TagSystem(self.env).split_into_tags
        ticket = Ticket(self.env, resource.id)
        all = self._ticket_tags(ticket)
        keywords = split_into_tags(ticket['keywords'])
        tags.difference_update(all.difference(keywords))
        ticket['keywords'] = u' '.join(sorted(map(to_unicode, tags)))
        ticket.save_changes(get_reporter_id(req), comment)

    def remove_resource_tags(self, req, resource, comment=u''):
        req.perm.require('TICKET_MODIFY', resource)
        ticket = Ticket(self.env, resource.id)
        ticket['keywords'] = u''
        ticket.save_changes(get_reporter_id(req), comment)

    def describe_tagged_resource(self, req, resource):
        if not 'TICKET_VIEW' in req.perm(resource):
            return ''
        ticket = Ticket(self.env, resource.id)
        if ticket.exists:
            ticket_system = TicketSystem(self.env)
            return ticket_system.get_resource_description(ticket.resource,
                                                          format='summary')
        else:
            return ''

    # Private methods
    def _ticket_tags(self, ticket):
        split_into_tags = TagSystem(self.env).split_into_tags
        return split_into_tags(
            ' '.join(filter(None, [ticket[f] for f in self.fields])))
