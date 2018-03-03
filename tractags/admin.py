# -*- coding: utf-8 -*-
#
# Copyright (C) 2011 Itamar Ostricher <itamarost@gmail.com>
# Copyright (C) 2011-2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from pkg_resources import parse_version

from trac import __version__
from trac.admin import IAdminPanelProvider
from trac.core import Component, implements
from trac.web.chrome import Chrome, add_warning

from tractags.api import TagSystem, _


class TagChangeAdminPanel(Component):
    """[opt] Admin web-UI providing administrative tag system actions."""

    implements(IAdminPanelProvider)

    # AdminPanelProvider methods
    def get_admin_panels(self, req):
        if 'TAGS_ADMIN' in req.perm:
            yield 'tags', _('Tag System'), 'replace', _('Replace')

    def render_admin_panel(self, req, cat, page, version):
        req.perm.require('TAGS_ADMIN')

        tag_system = TagSystem(self.env)
        all_realms = tag_system.get_taggable_realms(req.perm)
        # Check request for enabled filters, or use default.
        if not [r for r in all_realms if r in req.args]:
            for realm in all_realms:
                req.args[realm] = 'on'
        checked_realms = [r for r in all_realms if r in req.args]
        data = dict(checked_realms=checked_realms,
                    tag_realms=list(dict(name=realm,
                                         checked=realm in checked_realms)
                                    for realm in all_realms))

        if req.method == 'POST':
            # Replace Tag
            allow_delete = req.args.get('allow_delete')
            new_tag = req.args.get('tag_new_name').strip()
            new_tag = not new_tag == u'' and new_tag or None
            if not (allow_delete or new_tag):
                add_warning(req, _("Selected current tag(s) and either "
                                   "new tag or delete approval are required"))
            else:
                comment = req.args.get('comment', u'')
                old_tags = req.args.getlist('tag_name')
                if old_tags:
                    tag_system.replace_tag(req, old_tags, new_tag, comment,
                                           allow_delete, filter=checked_realms)
                data['selected'] = new_tag
            req.redirect(req.href.admin('tags', 'replace'))

        query = ' or '.join('realm:%s' % r for r in checked_realms)
        all_tags = sorted(tag_system.get_all_tags(req, query))
        data['tags'] = all_tags
        chrome = Chrome(self.env)
        chrome.add_textarea_grips(req)
        if hasattr(chrome, 'jenv'):
            return 'admin_tag_change.html', data, None
        else:
            return 'admin_tag_change.html', data
