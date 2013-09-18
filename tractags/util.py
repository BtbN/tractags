# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2013 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import re

_TAG_SPLIT = re.compile('[,\s]+')


def split_into_tags(text):
    """Split plain text into tags."""
    return set([tag.strip() for tag in _TAG_SPLIT.split(text)
               if tag.strip()])

