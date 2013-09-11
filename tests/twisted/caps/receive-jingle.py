"""
Test receiving another contact's capabilities.
"""

import dbus

from servicetest import EventPattern, assertEquals, sync_dbus
from gabbletest import exec_test, make_result_iq, make_presence, sync_stream
from caps_helper import (assert_rccs_callable, assert_rccs_not_callable,
        check_rccs_callable)
import constants as cs

from config import VOIP_ENABLED

if not VOIP_ENABLED:
    print "NOTE: built with --disable-voip"
    raise SystemExit(77)

icaps_attr  = cs.CONN_IFACE_CAPS + "/caps"

def test(q, bus, conn, stream):
    bob, = conn.RequestHandles(cs.HT_CONTACT, ['bob@foo.com'])

    presence = make_presence('bob@foo.com/Foo', status='hello')
    stream.send(presence)

    q.expect('dbus-signal', signal='PresencesChanged',
           args=[{bob: (cs.PRESENCE_AVAILABLE, u'available', 'hello')}])

    basic_caps = [(bob, cs.CHANNEL_TYPE_TEXT, 3, 0)]

    # no special capabilities
    assert conn.Capabilities.GetCapabilities([bob]) == basic_caps
    # only Text
    for rcc in conn.ContactCapabilities.GetContactCapabilities([bob])[bob]:
        assertEquals(cs.CHANNEL_TYPE_TEXT, rcc[0].get(cs.CHANNEL_TYPE))

    # holding the handle here: see below
    assert conn.Contacts.GetContactAttributes(
        [bob], [cs.CONN_IFACE_CAPS], True) == \
        { bob: { icaps_attr: basic_caps,
                cs.CONN + '/contact-id': 'bob@foo.com'}}
    assertEquals(
            { bob: {
                cs.ATTR_CONTACT_CAPABILITIES:
                    conn.ContactCapabilities.GetContactCapabilities([bob])[bob],
                cs.CONN + '/contact-id': 'bob@foo.com',
                },
            },
            conn.Contacts.GetContactAttributes([bob], [cs.CONN_IFACE_CONTACT_CAPS], True))

    # send updated presence with Jingle audio/video caps info. we turn on both
    # audio and video at the same time to test that all of the capabilities are
    # discovered before any capabilities change signal is emitted
    presence = make_presence('bob@foo.com/Foo', status='hello',
        caps={
            'node': 'http://telepathy.freedesktop.org/fake-client',
            'ver' : '0.1',
            'ext' : 'video',
        })
    stream.send(presence)

    # Gabble looks up both the version and the video bundles, in any order
    (version_event, video_event) = q.expect_many(
        EventPattern('stream-iq', to='bob@foo.com/Foo',
            query_ns='http://jabber.org/protocol/disco#info',
            query_node='http://telepathy.freedesktop.org/fake-client#0.1'),
        EventPattern('stream-iq', to='bob@foo.com/Foo',
            query_ns='http://jabber.org/protocol/disco#info',
            query_node='http://telepathy.freedesktop.org/fake-client#video'))

    # reply to the video bundle query first - this capability alone is not
    # sufficient to make us callable
    result = make_result_iq(stream, video_event.stanza)
    query = result.firstChildElement()
    feature = query.addElement('feature')
    feature['var'] = 'http://jabber.org/protocol/jingle/description/video'
    stream.send(result)

    # reply to the version bundle query, which should make us audio and
    # video callable
    result = make_result_iq(stream, version_event.stanza)
    query = result.firstChildElement()
    feature = query.addElement('feature')
    feature['var'] = 'http://jabber.org/protocol/jingle'
    feature = query.addElement('feature')
    feature['var'] = 'http://jabber.org/protocol/jingle/description/audio'
    feature = query.addElement('feature')
    feature['var'] = 'http://www.google.com/transport/p2p'
    stream.send(result)

    # we can now do audio and video calls
    old, new = q.expect_many(
        EventPattern('dbus-signal', signal='CapabilitiesChanged',
            args=[[(bob, cs.CHANNEL_TYPE_STREAMED_MEDIA, 0, 3,
                0, cs.MEDIA_CAP_AUDIO | cs.MEDIA_CAP_VIDEO)]]),
        EventPattern('dbus-signal', signal='ContactCapabilitiesChanged',
            predicate=lambda e: check_rccs_callable(e.args[0][bob])),
        )
    assert_rccs_callable(new.args[0][bob], require_video=True,
            mutable_contents=True)

    caps = conn.Contacts.GetContactAttributes([bob], [cs.CONN_IFACE_CAPS], False)
    assert caps.keys() == [bob]
    assert icaps_attr in caps[bob]
    assert len(caps[bob][icaps_attr]) == 2
    assert basic_caps[0] in caps[bob][icaps_attr]
    assert (bob, cs.CHANNEL_TYPE_STREAMED_MEDIA, 3, 3) in caps[bob][icaps_attr]

    assertEquals(
            { bob: {
                cs.ATTR_CONTACT_CAPABILITIES:
                    new.args[0][bob],
                cs.CONN + '/contact-id': 'bob@foo.com',
                },
            },
            conn.Contacts.GetContactAttributes([bob],
                [cs.CONN_IFACE_CONTACT_CAPS], True))

    # send updated presence without video support
    presence = make_presence('bob@foo.com/Foo', status='hello',
        caps={
            'node': 'http://telepathy.freedesktop.org/fake-client',
            'ver' : '0.1',
        })
    stream.send(presence)

    # we can now do only audio calls (and as a result have the ImmutableStreams
    # cap)
    old, new = q.expect_many(
        EventPattern('dbus-signal', signal='CapabilitiesChanged',
            args=[[(bob, cs.CHANNEL_TYPE_STREAMED_MEDIA, 3, 3,
                cs.MEDIA_CAP_AUDIO | cs.MEDIA_CAP_VIDEO,
                cs.MEDIA_CAP_AUDIO | cs.MEDIA_CAP_IMMUTABLE_STREAMS)]]),
        EventPattern('dbus-signal', signal='ContactCapabilitiesChanged'),
        )
    assert_rccs_callable(new.args[0][bob])
    assert_rccs_not_callable(new.args[0][bob], require_audio=False,
            require_video=True, mutable_contents=False)

    caps = conn.Contacts.GetContactAttributes([bob], [cs.CONN_IFACE_CAPS], False)
    assert caps.keys() == [bob]
    assert icaps_attr in caps[bob]
    assert len(caps[bob][icaps_attr]) == 2
    assert basic_caps[0] in caps[bob][icaps_attr]
    assert (bob, cs.CHANNEL_TYPE_STREAMED_MEDIA, 3,
        cs.MEDIA_CAP_AUDIO | cs.MEDIA_CAP_IMMUTABLE_STREAMS) \
        in caps[bob][icaps_attr]

    assertEquals(
            { bob: {
                cs.ATTR_CONTACT_CAPABILITIES:
                    new.args[0][bob],
                cs.CONN + '/contact-id': 'bob@foo.com',
                },
            },
            conn.Contacts.GetContactAttributes([bob],
                [cs.CONN_IFACE_CONTACT_CAPS], True))

    # go offline
    presence = make_presence('bob@foo.com/Foo', type='unavailable')
    stream.send(presence)

    # can't do audio calls any more
    q.expect_many(
            EventPattern('dbus-signal', signal='CapabilitiesChanged',
                args=[[(bob, cs.CHANNEL_TYPE_STREAMED_MEDIA, 3, 0,
                    cs.MEDIA_CAP_AUDIO | cs.MEDIA_CAP_IMMUTABLE_STREAMS,
                    0)]],
                ),
            EventPattern('dbus-signal', signal='PresencesChanged',
                args=[{bob: (cs.PRESENCE_OFFLINE, 'offline', '')}]),
            EventPattern('dbus-signal', signal='ContactCapabilitiesChanged'),
            )

    # Contact went offline. Previously, this test asserted that the handle
    # became invalid, but that's not guaranteed to happen immediately; so we
    # now hold the handle (above), to guarantee that it does *not* become
    # invalid.
    rccs = conn.ContactCapabilities.GetContactCapabilities([bob])[bob]
    for rcc in rccs:
        assertEquals(cs.CHANNEL_TYPE_TEXT, rcc[0].get(cs.CHANNEL_TYPE))

    assertEquals(
            { bob: {
                cs.ATTR_CONTACT_CAPABILITIES: rccs,
                cs.CONN + '/contact-id': 'bob@foo.com',
                },
            },
            conn.Contacts.GetContactAttributes([bob],
                [cs.CONN_IFACE_CONTACT_CAPS], True))
    assert conn.Contacts.GetContactAttributes(
        [bob], [cs.CONN_IFACE_CAPS], False) == \
        { bob: { icaps_attr: basic_caps,
                cs.CONN + '/contact-id': 'bob@foo.com'}}

    # What about a handle that's not valid?
    assertEquals({}, conn.Contacts.GetContactAttributes(
        [31337], [cs.CONN_IFACE_CAPS], False))

    # regression test for fd.o #15198: getting caps of invalid handle crashed
    try:
        conn.Capabilities.GetCapabilities([31337])
    except dbus.DBusException, e:
        pass
    else:
        assert False, "Should have had an error!"

if __name__ == '__main__':
    exec_test(test)

