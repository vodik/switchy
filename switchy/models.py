# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Models representing freeSWITCH entities
"""
import time
from utils import dirinfo
from collections import deque
from multiproc import mp
from utils import ESLError


class JobError(ESLError):
    pass


class Events(object):
    """Event collection which for most intents and purposes should quack like
    a collections.deque. Data lookups are delegated to the internal
    deque of events in lilo order.
    """
    def __init__(self, event=None):
        self._events = deque()
        if event is not None:
            # add initial event to our queue
            self.update(event)

    def __repr__(self):
        return repr(self._events)

    def update(self, event):
        '''Append an ESL.ESLEvent
        '''
        self._events.appendleft(event)

    def __len__(self):
        return len(self._events)

    def __iter__(self):
        for ev in self._events:
            yield ev

    def get(self, key, default=None):
        """Return default if not found
        Should be faster then handling the key error?
        """
        # XXX would a map() be faster here?
        # iterate from most recent event
        for ev in self._events:
            value = ev.getHeader(str(key))
            if value:
                return value
        return default

    def __getitem__(self, key):
        '''Return either the value corresponding to variable 'key'
        or if type(key) == (int or slice) then return the corresponding
        event from the internal deque
        '''
        value = self.get(key)
        if value:
            return value
        else:
            if isinstance(key, (int, slice)):
                return self._events[key]
            raise KeyError(key)

    def show(self, index=0):
        """Print data for index'th event to console.
        Default is most recent.
        """
        print(self._events[index].serialize())


class Session(object):
    '''Type to represent FS Session state
    '''
    create_ev = 'CHANNEL_CREATE'

    # TODO: eventually uuid should be removed
    def __init__(self, uuid=None, event=None, con=None):

        self.events = Events(event)
        self.uuid = self.events['Unique-ID']
        if uuid:
            self.uuid = uuid
        self.con = con
        # sub-namespace for apps to set/get state
        self.vars = {}
        # external attributes
        self.duration = 0
        self.bg_job = None
        self.answered = False
        self.num_sessions = None
        self.call = None
        self.hungup = False
        # time stamps
        self.create_time = float('inf')
        self.answer_time = float('inf')
        self.originate_time = float('inf')

    def __str__(self):
        return str(self.uuid)

    def __dir__(self):
        # TODO: use a transform func to provide __getattr__
        # access to event data
        return dirinfo(self)

    def __getattr__(self, name):
        if 'variable' in name:
            try:  # to acquire from channel variables
                return self.events[name]
            except KeyError:
                pass
        return object.__getattribute__(self, name)

    def __getitem__(self, key):
        try:
            return self.events[key]
        except KeyError:
            raise KeyError("'{}' not found for session '{}'"
                           .format(key, self.uuid))

    def get(self, key, default=None):
        '''Get data pertaining to session state as updated via events

        Parameters
        ----------
        name : string
            name of the variable to return the value for
        '''
        return self.events.get(key, default)

    def update(self, event):
        '''Update state/data using an ESL.ESLEvent
        '''
        self.events.update(event)

    def show(self):
        """Print data for most recent event to console
        """
        self.events.show()

    # FIXME: should we keep weakrefs to a partner session interally?
    # modify these props to utilize the partner session
    @property
    def invite_latency(self):
        return self.create_time_bleg - self.create_time_aleg

    @property
    def answer_latency(self):
        return self.answer_time_aleg - self.answer_time_bleg

    def __enter__(self, connection):
        self.con = connection
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.con = None

    # call control / 'mod_commands' methods
    # TODO: dynamically add @decorated functions to this class
    # and wrap them using functools.update_wrapper ...?

    def setvar(self, var, value):
        """Set variable to value
        """
        self.broadcast("set::{}={}".format(var, value))

    def setvars(self, params):
        """Set all variables in map `params` with a single command
        """
        pairs = ('='.join(map(str, pair)) for pair in pairs.iteritems())
        self.api("uuid_setvar_multi {} {}".format(self.uuid, ';'.join(pairs)))

    def unsetvar(self, var):
        """Unset a channel var
        """
        self.broadcast("unset::{}".format(var))

    def answer(self):
        self.broadcast("answer::")

    def hangup(self, cause='NORMAL_CLEARING'):
        '''Hangup this session with the given cause

        Parameters
        ----------
        cause : string
            hangup type keyword
        '''
        self.con.api(str('uuid_kill %s %s' % (self.uuid, cause)))

    def sched_hangup(self, timeout, cause='NORMAL_CLEARING'):
        '''Schedule this session to hangup after timeout seconds

        Parameters
        ----------
        timeout : float
            timeout in seconds
        cause : string
            hangup cause code
        '''
        self.con.api('sched_hangup +{} {} {}'.format(timeout,
                     self.uuid, cause))

    def sched_dtmf(self, delay, sequence, tone_duration=None):
        '''Schedule dtmf sequence to be played on this channel

        Parameters
        ----------
        delay : float
            scheduled future time when dtmf tones should play
        sequence : string
            sequence of dtmf digits to play
        '''
        cmd = 'sched_api +{} none uuid_send_dtmf {} {}'.format(
            delay, self.uuid, sequence)
        if tone_duration is not None:
            cmd += ' @{}'.format(tone_duration)
        self.con.api(cmd)

    def playback(self, file_path, leg='aleg'):
        '''Playback a file on this session

        Parameters
        ----------
        file_path : string
            path to audio file to playback
        leg : string
            call leg to transmit the audio on.
        '''
        self.con.api('uuid_broadcast {} playback::{} aleg'.format(
                     self.uuid, file_path))

    def bypass_media(self, state):
        '''Re-invite a bridged node out of the media path for this session
        '''
        if state:
            self.con.api('uuid_media off {}'.format(self.uuid))
        else:
            self.con.api('uuid_media {}'.format(self.uuid))

    def app_break(self):
        '''Stop playback of media on this session and move on in the dialplan
        '''
        self.con.api('uuid_break {}'.format(self.uuid))

    def start_amd(self, timeout=None):
        # self.con.api('avmd %s start' % (self.uuid))
        self.con.api('avmd {} start'.format(self.uuid))
        if timeout is not None:
            # self.con.api('sched_api +%d none avmd %s stop'
            #              % (int(timeout), self.uuid))
            self.con.api('sched_api +{} none avmd {} stop'.format(
                         int(timeout), self.uuid))

    def stop_amd(self):
        self.con.api('avmd %s stop' % (self.uuid))

    def park(self):
        '''Park this session
        '''
        self.con.api('uuid_park {}'.format(self.uuid))

    def broadcast(self, path, leg=''):
        """Usage:
            uuid_broadcast <uuid> <path> [aleg|bleg|both]

        Execute an application on a chosen leg(s) with optional hangup
        afterwards:
        Usage:
            uuid_broadcast <uuid> app[![hangup_cause]]::args [aleg|bleg|both]
        """
        # FIXME: this should use the EventListener SOCKET_DATA handler!!
        #       so that we are actually alerted of cmd errors!
        self.con.api('uuid_broadcast {} {} {}'.format(self.uuid, path, leg))

    def bridge(self, profile="${sofia_profile_name}",
               dest_url="${sip_req_user}",
               params=False):
        """Bridge this session using `uuid_broadcast`.
        By default the current profile is used to bridge to the requested user.
        """
        pairs = ('='.join(map(str, pair))
                 for pair in params.iteritems()) if params else ''
        self.broadcast("bridge::{{{varset}}}sofia/{}/{}"
                       .format(profile, dest_url, varset=','.join(pairs)))

    def is_inbound(self):
        """Return bool indicating whether this is an inbound session
        """
        return self['Call-Direction'] == 'inbound'

    def is_outbound(self):
        """Return bool indicating whether this is an outbound session
        """
        return self['Call-Direction'] == 'outbound'


class Call(object):
    '''A deque of sessions which  a call
    '''
    def __init__(self, uuid, session):
        self.uuid = uuid
        self.sessions = deque()
        self.sessions.append(session)

    def __repr__(self):
        return "<{}({}, {} sessions)>".format(
            type(self).__name__, self.uuid, len(self.sessions))

    def hangup(self):
        self.sessions[0].hangup()


class Job(object):
    '''Type to hold data and deferred execution for a background job.
    The interface closely matches `multiprocessing.pool.AsyncResult`.

    Parameters
    ----------
    uuid : string
        job uuid returned directly by SOCKET_DATA event
    sess_uuid : string
        optional session uuid if job is associated with an active
        FS session
    '''
    class TimeoutError(Exception):
        pass

    def __init__(self, event, sess_uuid=None, callback=None, client_id=None,
                 kwargs={}):
        self.events = Events(event)
        self.uuid = self.events['Job-UUID']  # event.getHeader('Job-UUID')
        self.sess_uuid = sess_uuid
        self.launch_time = time.time()
        self.cid = client_id  # placeholder for client ident
        self._sig = mp.Event()  # signal/sync job completion

        # when the job returns use this callback
        self._cb = callback
        self.kwargs = kwargs
        self._result = None
        self._failed = False

    @property
    def result(self):
        '''The final result
        '''
        return self.get()

    def __call__(self, resp, *args, **kwargs):
        if self._cb:
            self.kwargs.update(kwargs)
            self._result = self._cb(resp, *args, **self.kwargs)
        else:
            self._result = resp
        self._sig.set()  # signal job completion
        return self._result

    def fail(self, resp, *args, **kwargs):
        '''Fail this job optionally adding an exception for its result
        '''
        self._failed = True
        self._result = JobError(self(resp, *args, **kwargs))

    def get(self, timeout=None):
        '''Get the result for this job waiting up to `timeout` seconds.
        Raises `TimeoutError` on if job does complete within alotted time.
        '''
        ready = self._sig.wait(timeout)
        if ready:
            return self._result
        elif timeout:
            raise TimeoutError("Job not complete after '{}' seconds"
                               .format(timeout))

    def ready(self):
        '''Return bool indicating whether job has completed
        '''
        return self._sig.is_set()

    def wait(self, timeout=None):
        '''Wait until job has completed or `timeout` has expired
        '''
        self._sig.wait(timeout)

    def successful(self):
        '''Return bool determining whether job completed without error
        '''
        assert self.ready(), 'Job has not completed yet'
        return not self._failed

    def update(self, event):
        '''Update job state/data using an event
        '''
        self.events.update(event)
