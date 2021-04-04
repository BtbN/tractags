# -*- coding: utf-8 -*-
#
# Copyright (C) 2006 Alec Thomas <alec@swapoff.org>
# Copyright (C) 2012-2014 Steffen Hoffmann <hoff.st@web.de>
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

"""
See tractags.api for detailed information.
"""

import pkg_resources
pkg_resources.require('Trac >= 1.4')


import tractags.api
import tractags.db
import tractags.wiki
import tractags.ticket
import tractags.macros
import tractags.web_ui
import tractags.admin
