# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Marks for annotating callback functions
"""
from functools import partial


def marker(event_type, cb_type='callback'):
    """Decorator to mark a callback function
    for handling events of a particular type
    """
    et_attr = '_switchy_event'
    cbt_attr = '_switchy_cb_type'

    def inner(callback):
        try:
            getattr(callback, et_attr).append(event_type)
        except AttributeError:
            setattr(callback, et_attr, [event_type])
        setattr(callback, cbt_attr, cb_type)
        return callback
    return inner


event_callback = marker
handler = partial(marker, cb_type='handler')


def has_callbacks(ns):
    """Check if this namespace contains switchy callbacks

    :param ns namespace: the namespace object containing marked callbacks
    :rtype: bool
    """
    return any(getattr(obj, '_switchy_event', False) for obj in
               vars(ns).values())


def get_callbacks(ns, skip=(), only=False):
    """Deliver all switchy callbacks found in a namespace object

    :param ns namespace: the namespace object containing marked callbacks
    :yields: event_type, callback_type, callback_obj
    """
    for name in (name for name in dir(ns) if name not in skip):
        try:
            obj = object.__getattribute__(ns, name)
        except AttributeError:
            continue
        ev_types = getattr(obj, '_switchy_event', False)
        cb_type = getattr(obj, '_switchy_cb_type', None)
        if ev_types:
            if not only or cb_type == only:
                for ev in ev_types:
                    yield ev, cb_type, obj
