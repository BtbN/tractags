# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2013,2014 Steffen Hoffmann <hoff.st@web.de>
# Copyright (C) 2014 Ryan J Ollos <ryan.j.ollos@gmail.com>
# Copyright (C) 2021 Cinc
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re
from functools import partial

from trac.test import Mock, MockPerm
from trac.web.api import _RequestArgs

_TAG_SPLIT = re.compile('[,\s]+')


# DEVEL: This needs monitoring for possibly varying endpoint requirements.
MockReq = partial(Mock, args=_RequestArgs(), authname='anonymous',
                  perm=MockPerm(), session=dict(),
                  is_authenticated=lambda a: a != 'anonymous')


def query_realms(query, all_realms):
    realms = []
    for realm in all_realms:
        if re.search('(^|\W)realm:%s(\W|$)' % realm, query):
            realms.append(realm)
    return realms


def split_into_tags(text):
    """Split plain text into tags."""
    return set(filter(None, [tag.strip() for tag in _TAG_SPLIT.split(text)]))

class JTransformer(object):
    """Class modelled after the Genshi Transformer class. Instead of an xpath it uses a
       selector usable by jQuery.
       You may use cssify (https://github.com/santiycr/cssify) to convert a xpath to a selector."""

    def __init__(self, xpath):
        self.css = xpath  # xpath must be a css selector for jQuery

    def after(self, html):
        return {'pos': 'after', 'css': self.css, 'html': html}

    def before(self, html):
        return {'pos': 'before', 'css': self.css, 'html': html}

    def prepend(self, html):
        return {'pos': 'prepend', 'css': self.css, 'html': html}

    def append(self, html):
        return {'pos': 'append', 'css': self.css, 'html': html}

    def remove(self):
        return {'pos': 'remove', 'css': self.css, 'html': ''}

    def replace(self, html):
        return {'pos': 'replace', 'css': self.css, 'html': html}
