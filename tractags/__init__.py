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
trac_version_min = '0.11'
pkg_resources.require('Trac >= %s' % trac_version_min)


import api
import db
import wiki
import ticket
import macros
import web_ui
import admin
