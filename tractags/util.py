# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2013,2014 Steffen Hoffmann <hoff.st@web.de>
# Copyright (C) 2014 Ryan J Ollos <ryan.j.ollos@gmail.com>
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
