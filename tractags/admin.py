# -*- coding: utf-8 -*-
#
# Copyright (C) 2011 Itamar Ostricher <itamarost@gmail.com>
# Copyright (C) 2011-2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#


from trac.admin import IAdminPanelProvider
from trac.core import Component, ExtensionPoint, implements
from trac.util.compat import sorted
from trac.web.chrome import Chrome
from tractags.api import TagSystem, ITagProvider, _


class TagChangeAdminPanel(Component):

    implements(IAdminPanelProvider)

    tag_providers = ExtensionPoint(ITagProvider)

    # AdminPanelProvider methods
    def get_admin_panels(self, req):
        if 'TAGS_ADMIN' in req.perm:
            yield ('tags', _('Tag System'), 'replace', _('Replace'))

    def render_admin_panel(self, req, cat, page, version):
        req.perm.require('TAGS_ADMIN')

        realms = [p.get_taggable_realm() for p in self.tag_providers
                  if (not hasattr(p, 'check_permission') or \
                      p.check_permission(req.perm, 'view'))]
        # Check request for enabled filters, or use default.
        if [r for r in realms if r in req.args] == []:
            for realm in realms:
                req.args[realm] = 'on'
        checked_realms = [r for r in realms if r in req.args]
        data = dict(checked_realms=checked_realms,
                    tag_realms=list(dict(name=realm,
                                         checked=realm in checked_realms)
                                    for realm in realms))

        tag_system = TagSystem(self.env)
        if req.method == 'POST':
            # Replace Tag
            allow_delete = req.args.get('allow_delete')
            new_tag = req.args.get('tag_new_name').strip()
            new_tag =  not new_tag == u'' and new_tag or None
            if not (allow_delete or new_tag):
                data['error'] = _("Selected current tag(s) and either "
                                  "new tag or delete approval are required")
            else:
                comment = req.args.get('comment', u'')
                old_tags = req.args.get('tag_name')
                if old_tags:
                    # Provide list regardless of single or multiple selection.
                    old_tags = isinstance(old_tags, list) and old_tags or \
                               [old_tags]
                    tag_system.replace_tag(req, old_tags, new_tag, comment,
                                           allow_delete, filter=checked_realms)
                data['selected'] = new_tag

        query = ' or '.join(['realm:%s' % r for r in checked_realms])
        all_tags = sorted(tag_system.get_all_tags(req, query))
        data['tags'] = all_tags
        try:
            Chrome(self.env).add_textarea_grips(req)
        except AttributeError:
            # Element modifiers unavailable before Trac 0.12, skip gracefully.
            pass
        return 'admin_tag_change.html', data

