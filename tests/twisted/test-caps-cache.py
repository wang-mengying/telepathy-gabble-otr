
"""
Test that requesting a caps set 1 time is enough with hash and that we need 5
confirmation without hash.
"""

import dbus
import sys

from twisted.words.xish import domish, xpath

from gabbletest import exec_test, make_result_iq

text = 'org.freedesktop.Telepathy.Channel.Type.Text'
sm = 'org.freedesktop.Telepathy.Channel.Type.StreamedMedia'
caps_iface = 'org.freedesktop.Telepathy.Connection.Interface.Capabilities'

caps_changed_flag = 0

def caps_changed_cb(dummy):
    # Workaround to bug 9980: do not raise an error but use a flag
    # https://bugs.freedesktop.org/show_bug.cgi?id=9980
    global caps_changed_flag
    caps_changed_flag = 1

def make_presence(from_jid, type, status):
    presence = domish.Element((None, 'presence'))

    if from_jid is not None:
        presence['from'] = from_jid

    if type is not None:
        presence['type'] = type

    if status is not None:
        presence.addElement('status', content=status)

    return presence

def presence_add_caps(presence, ver, client, hash=None):
    c = presence.addElement(('http://jabber.org/protocol/caps', 'c'))
    c['node'] = client
    c['ver'] = ver
    if hash is not None:
        c['hash'] = hash
    return presence

def _test_without_hash(q, bus, conn, stream, contact, contact_handle, client, disco):
    global caps_changed_flag

    presence = make_presence(contact, None, 'hello')
    stream.send(presence)

    event = q.expect('dbus-signal', signal='PresenceUpdate',
        args=[{contact_handle: (0L, {u'available': {'message': 'hello'}})}])

    # no special capabilities
    basic_caps = [(contact_handle, text, 3, 0)]
    assert conn.Capabilities.GetCapabilities([contact_handle]) == basic_caps

    # send updated presence with Jingle caps info
    presence = make_presence(contact, None, 'hello')
    presence = presence_add_caps(presence, '0.1', client)
    print str(presence)
    stream.send(presence)

    if disco:
        # Gabble looks up our capabilities
        event = q.expect('stream-iq', to=contact,
            query_ns='http://jabber.org/protocol/disco#info')
        query_node = xpath.queryForNodes('/iq/query', event.stanza)[0]
        assert query_node.attributes['node'] == \
            client + '#' + '0.1'

        # send good reply
        result = make_result_iq(stream, event.stanza)
        query = result.firstChildElement()
        feature = query.addElement('feature')
        feature['var'] = 'http://jabber.org/protocol/jingle'
        feature = query.addElement('feature')
        feature['var'] = 'http://jabber.org/protocol/jingle/description/audio'
        feature = query.addElement('feature')
        feature['var'] = 'http://www.google.com/transport/p2p'
        stream.send(result)

    # we can now do audio calls
    event = q.expect('dbus-signal', signal='CapabilitiesChanged')
    caps_changed_flag = 0

    # don't receive any D-Bus signal
    assert caps_changed_flag == 0

def _test_with_hash(q, bus, conn, stream, contact, contact_handle, client, disco):
    global caps_changed_flag

    presence = make_presence(contact, None, 'hello')
    stream.send(presence)

    event = q.expect('dbus-signal', signal='PresenceUpdate',
        args=[{contact_handle: (0L, {u'available': {'message': 'hello'}})}])

    # no special capabilities
    basic_caps = [(contact_handle, text, 3, 0)]
    assert conn.Capabilities.GetCapabilities([contact_handle]) == basic_caps

    # send updated presence with Jingle caps info
    presence = make_presence(contact, None, 'hello')
    c = presence.addElement(('http://jabber.org/protocol/caps', 'c'))
    c['node'] = client
    c['ver'] = 'CzO+nkbflbxu1pgzOQSIi8gOyDc=' # good hash
    c['hash'] = 'sha-1'
    stream.send(presence)

    if disco:
        # Gabble looks up our capabilities
        event = q.expect('stream-iq', to=contact,
            query_ns='http://jabber.org/protocol/disco#info')
        query_node = xpath.queryForNodes('/iq/query', event.stanza)[0]
        assert query_node.attributes['node'] == \
            client + '#' + c['ver']

        # send good reply
        result = make_result_iq(stream, event.stanza)
        query = result.firstChildElement()
        query['node'] = client + '#' + c['ver']
        feature = query.addElement('feature')
        feature['var'] = 'http://jabber.org/protocol/jingle'
        feature = query.addElement('feature')
        feature['var'] = 'http://jabber.org/protocol/jingle/description/audio'
        feature = query.addElement('feature')
        feature['var'] = 'http://www.google.com/transport/p2p'
        query.addRawXml("""
<x type='result' xmlns='jabber:x:data'>
<field var='FORM_TYPE' type='hidden'>
<value>urn:xmpp:dataforms:softwareinfo</value>
</field>
<field var='software'>
<value>A Fake Client with Twisted</value>
</field>
<field var='software_version'>
<value>5.11.2-svn-20080512</value>
</field>
<field var='os'>
<value>Debian GNU/Linux unstable (sid) unstable sid</value>
</field>
<field var='os_version'>
<value>2.6.24-1-amd64</value>
</field>
</x>
        """)
        stream.send(result)

    # we can now do audio calls
    event = q.expect('dbus-signal', signal='CapabilitiesChanged')
    caps_changed_flag = 0

    # don't receive any D-Bus signal
    assert caps_changed_flag == 0

def test(q, bus, conn, stream):
    conn.Connect()
    q.expect('dbus-signal', signal='StatusChanged', args=[0, 1])

    # be notified when the signal CapabilitiesChanged is fired
    conn_caps_iface = dbus.Interface(conn, caps_iface)
    conn_caps_iface.connect_to_signal('CapabilitiesChanged', caps_changed_cb)

    client = 'http://telepathy.freedesktop.org/fake-client'

    _test_without_hash(q, bus, conn, stream, 'bob1@foo.com/Foo', 2L, client, 1)
    _test_without_hash(q, bus, conn, stream, 'bob2@foo.com/Foo', 3L, client, 1)
    _test_without_hash(q, bus, conn, stream, 'bob3@foo.com/Foo', 4L, client, 1)
    _test_without_hash(q, bus, conn, stream, 'bob4@foo.com/Foo', 5L, client, 1)
    _test_without_hash(q, bus, conn, stream, 'bob5@foo.com/Foo', 6L, client, 1)
    # we have 5 different contacts that confirm
    _test_without_hash(q, bus, conn, stream, 'bob6@foo.com/Foo', 7L, client, 0)

    _test_with_hash(q, bus, conn, stream, 'bilbo1@foo.com/Foo', 8L, client, 1)
    # 1 contact is enough with hash
    _test_with_hash(q, bus, conn, stream, 'bilbo2@foo.com/Foo', 9L, client, 0)

    conn.Disconnect()
    q.expect('dbus-signal', signal='StatusChanged', args=[2, 1])


if __name__ == '__main__':
    exec_test(test)
