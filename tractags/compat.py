# -*- coding: utf-8 -*-
#
# Copyright (c) 2013,2014 Steffen Hoffmann
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

"""Various classes and functions to provide backwards-compatibility with
previous versions of Python from 2.4 and Trac from 0.11 onwards.
"""

try:
    from functools import partial
except ImportError:
    # Cheap fallback for Python2.4 compatibility.
    # See http://stackoverflow.com/questions/12274814
    def partial(func, *args, **kwds):
        """Emulate Python2.6's functools.partial."""
        return lambda *fargs, **fkwds: func(*(args+fargs),
                                            **dict(kwds, **fkwds))

try:
    from trac.util.datefmt import to_utimestamp
    from trac.util.datefmt import to_datetime
except ImportError:
    # Cheap fallback for Trac 0.11 compatibility.
    from trac.util.datefmt  import to_timestamp
    def to_utimestamp(dt):
        return to_timestamp(dt) * 1000000L

    from trac.util.datefmt import to_datetime as to_dt
    def to_datetime(ts):
        return to_dt(ts / 1000000)

# Compatibility code for `ComponentManager.is_enabled`
# (available since Trac 0.12)
def is_enabled(env, cls):
    """Return whether the given component class is enabled.

    For Trac 0.11 the missing algorithm is included as fallback.
    """
    try:
        return env.is_enabled(cls)
    except AttributeError:
        if cls not in env.enabled:
            env.enabled[cls] = env.is_component_enabled(cls)
        return env.enabled[cls]
