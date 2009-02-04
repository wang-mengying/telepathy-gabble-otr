"""Test IBB tube support in the context of a MUC."""

import base64

import dbus
from dbus.connection import Connection
from dbus.lowlevel import SignalMessage

from servicetest import call_async, EventPattern, tp_name_prefix
from gabbletest import exec_test, make_result_iq, acknowledge_iq, make_muc_presence, elem
from constants import *
import ns
import tubetestutil as t

from twisted.words.xish import domish, xpath

from muctubeutil import get_muc_tubes_channel

sample_parameters = dbus.Dictionary({
    's': 'hello',
    'ay': dbus.ByteArray('hello'),
    'u': dbus.UInt32(123),
    'i': dbus.Int32(-123),
    }, signature='sv')

def test(q, bus, conn, stream):
    conn.Connect()

    _, iq_event = q.expect_many(
        EventPattern('dbus-signal', signal='StatusChanged', args=[0, 1]),
        EventPattern('stream-iq', to=None, query_ns='vcard-temp',
            query_name='vCard'))

    acknowledge_iq(stream, iq_event.stanza)

    self_handle = conn.GetSelfHandle()
    self_name = conn.InspectHandles(1, [self_handle])[0]

    handles, tubes_chan, tubes_iface = get_muc_tubes_channel(q, bus, conn,
        stream, 'chat@conf.localhost')

    # Exercise basic Channel Properties from spec 0.17.7
    channel_props = tubes_chan.GetAll(CHANNEL,
            dbus_interface=dbus.PROPERTIES_IFACE)
    assert channel_props.get('TargetHandle') == handles[0],\
            (channel_props.get('TargetHandle'), handles[0])
    assert channel_props.get('TargetHandleType') == 2,\
            channel_props.get('TargetHandleType')
    assert channel_props.get('ChannelType') == CHANNEL_TYPE_TUBES,\
            channel_props.get('ChannelType')
    assert 'Interfaces' in channel_props, channel_props
    assert CHANNEL_IFACE_GROUP in channel_props['Interfaces'], \
            channel_props['Interfaces']
    assert channel_props['TargetID'] == 'chat@conf.localhost', channel_props
    assert channel_props['Requested'] == True
    assert channel_props['InitiatorID'] == 'test@localhost'
    assert channel_props['InitiatorHandle'] == conn.GetSelfHandle()

    # Exercise Group Properties from spec 0.17.6 (in a basic way)
    group_props = tubes_chan.GetAll(CHANNEL_IFACE_GROUP,
            dbus_interface=dbus.PROPERTIES_IFACE)
    assert 'SelfHandle' in group_props, group_props
    assert 'HandleOwners' in group_props, group_props
    assert 'Members' in group_props, group_props
    assert 'LocalPendingMembers' in group_props, group_props
    assert 'RemotePendingMembers' in group_props, group_props
    assert 'GroupFlags' in group_props, group_props

    tubes_self_handle = tubes_chan.GetSelfHandle(
        dbus_interface=CHANNEL_IFACE_GROUP)
    assert group_props['SelfHandle'] == tubes_self_handle

    # Offer a D-Bus tube (old API)
    call_async(q, tubes_iface, 'OfferDBusTube',
            'com.example.TestCase', sample_parameters)

    new_tube_event, presence_event, offer_return_event, dbus_changed_event = \
        q.expect_many(
        EventPattern('dbus-signal', signal='NewTube'),
        EventPattern('stream-presence', to='chat@conf.localhost/test'),
        EventPattern('dbus-return', method='OfferDBusTube'),
        EventPattern('dbus-signal', signal='DBusNamesChanged', interface=CHANNEL_TYPE_TUBES))

    # handle new_tube_event
    dbus_tube_id = new_tube_event.args[0]
    assert new_tube_event.args[1] == tubes_self_handle
    assert new_tube_event.args[2] == TUBE_TYPE_DBUS
    assert new_tube_event.args[3] == 'com.example.TestCase'
    assert new_tube_event.args[4] == sample_parameters
    assert new_tube_event.args[5] == TUBE_STATE_OPEN

    # handle offer_return_event
    assert offer_return_event.value[0] == dbus_tube_id

    # handle presence_event
    # We announce our newly created tube in our muc presence
    presence = presence_event.stanza
    x_nodes = xpath.queryForNodes('/presence/x[@xmlns="http://jabber.org/'
            'protocol/muc"]', presence)
    assert x_nodes is not None
    assert len(x_nodes) == 1

    tubes_nodes = xpath.queryForNodes('/presence/tubes[@xmlns="%s"]'
        % ns.TUBES, presence)
    assert tubes_nodes is not None
    assert len(tubes_nodes) == 1

    tube_nodes = xpath.queryForNodes('/tubes/tube', tubes_nodes[0])
    assert tube_nodes is not None
    assert len(tube_nodes) == 1
    for tube in tube_nodes:
        tube['type'] = 'dbus'
        assert tube['initiator'] == 'chat@conf.localhost/test'
        assert tube['service'] == 'com.example.TestCase'
        dbus_stream_id = tube['stream-id']
        my_bus_name = tube['dbus-name']
        assert tube['id'] == str(dbus_tube_id)

    params = {}
    parameter_nodes = xpath.queryForNodes('/tube/parameters/parameter', tube)
    for node in parameter_nodes:
        assert node['name'] not in params
        params[node['name']] = (node['type'], str(node))
    assert params == {'ay': ('bytes', 'aGVsbG8='),
                      's': ('str', 'hello'),
                      'i': ('int', '-123'),
                      'u': ('uint', '123'),
                     }

    # handle dbus_changed_event
    assert dbus_changed_event.args[0] == dbus_tube_id
    assert dbus_changed_event.args[1][0][0] == tubes_self_handle
    assert dbus_changed_event.args[1][0][1] == my_bus_name

    # handle offer_return_event
    assert dbus_tube_id == offer_return_event.value[0]

    tubes = tubes_iface.ListTubes(byte_arrays=True)
    assert len(tubes) == 1
    expected_tube = (dbus_tube_id, tubes_self_handle, TUBE_TYPE_DBUS,
        'com.example.TestCase', sample_parameters, TUBE_STATE_OPEN)
    t.check_tube_in_tubes(expected_tube, tubes)

    dbus_tube_adr = tubes_iface.GetDBusTubeAddress(dbus_tube_id)
    tube = Connection(dbus_tube_adr)
    signal = SignalMessage('/', 'foo.bar', 'baz')
    signal.append(42, signature='u')
    tube.send_message(signal)

    event = q.expect('stream-message', to='chat@conf.localhost',
        message_type='groupchat')
    message = event.stanza

    data_nodes = xpath.queryForNodes('/message/data[@xmlns="%s"]' % ns.MUC_BYTESTREAM,
        message)
    assert data_nodes is not None
    assert len(data_nodes) == 1
    ibb_data = data_nodes[0]
    assert ibb_data['sid'] == dbus_stream_id
    binary = base64.b64decode(str(ibb_data))
    # little and big endian versions of: SIGNAL, NO_REPLY, protocol v1,
    # 4-byte payload
    assert binary.startswith('l\x04\x01\x01' '\x04\x00\x00\x00') or \
           binary.startswith('B\x04\x01\x01' '\x00\x00\x00\x04')
    # little and big endian versions of the 4-byte payload, UInt32(42)
    assert (binary[0] == 'l' and binary.endswith('\x2a\x00\x00\x00')) or \
           (binary[0] == 'B' and binary.endswith('\x00\x00\x00\x2a'))
    # XXX: verify that it's actually in the "sender" slot, rather than just
    # being in the message somewhere
    assert my_bus_name in binary


    # offer a D-Bus tube to another room using new API
    requestotron = dbus.Interface(conn, CONN_IFACE_REQUESTS)

    # check if we can request muc D-Bus tube
    properties = conn.GetAll(CONN_IFACE_REQUESTS, dbus_interface=PROPERTIES_IFACE)

    assert ({CHANNEL_TYPE: CHANNEL_TYPE_DBUS_TUBE,
        TARGET_HANDLE_TYPE: HT_ROOM},
         [TARGET_HANDLE, TARGET_ID, TUBE_PARAMETERS, DBUS_TUBE_SERVICE_NAME]
        ) in properties.get('RequestableChannelClasses'),\
                 properties['RequestableChannelClasses']

    call_async(q, requestotron, 'CreateChannel',
            {CHANNEL_TYPE: CHANNEL_TYPE_DBUS_TUBE,
         TARGET_HANDLE_TYPE: HT_ROOM,
         TARGET_ID: 'chat2@conf.localhost',
         DBUS_TUBE_SERVICE_NAME: 'com.example.TestCase',
         TUBE_PARAMETERS: sample_parameters,
        })

    # Send presence for other member of room.
    stream.send(make_muc_presence('owner', 'moderator', 'chat2@conf.localhost', 'bob'))

    # Send presence for own membership of room.
    stream.send(make_muc_presence('none', 'participant', 'chat2@conf.localhost', 'test'))

    event = q.expect('dbus-return', method='CreateChannel')
    new_tube_path, new_tube_props = event.value

    # first text and tubes channels are announced
    event = q.expect('dbus-signal', signal='NewChannels')
    channels = event.args[0]
    assert len(channels) == 2
    path1, prop1 = channels[0]
    path2, prop2 = channels[1]
    assert sorted([prop1[CHANNEL_TYPE], prop2[CHANNEL_TYPE]]) == \
        [CHANNEL_TYPE_TEXT, CHANNEL_TYPE_TUBES]

    got_text, got_tubes = False, False
    for path, props in channels:
        if props[CHANNEL_TYPE] == CHANNEL_TYPE_TEXT:
            got_text = True
        elif props[CHANNEL_TYPE] == CHANNEL_TYPE_TUBES:
            got_tubes = True
        else:
            assert False

        assert props[INITIATOR_HANDLE] == self_handle
        assert props[INITIATOR_ID] == self_name
        assert CHANNEL_IFACE_GROUP in props[INTERFACES]
        assert props[TARGET_ID] == 'chat2@conf.localhost'
        assert props[REQUESTED] == False

    assert (got_text, got_tubes) == (True, True)

    # now the tube channel is announced
    # FIXME: in this case, all channels should probably be announced together
    event = q.expect('dbus-signal', signal='NewChannels')
    channels = event.args[0]
    assert len(channels) == 1
    path, prop = channels[0]
    assert prop[CHANNEL_TYPE] == CHANNEL_TYPE_DBUS_TUBE
    assert prop[INITIATOR_ID] == 'chat2@conf.localhost/test'
    assert prop[REQUESTED] == True
    assert prop[TARGET_HANDLE_TYPE] == HT_ROOM
    assert prop[TARGET_ID] == 'chat2@conf.localhost'
    assert prop[DBUS_TUBE_SERVICE_NAME] == 'com.example.TestCase'

    tube_chan = bus.get_object(conn.bus_name, path)
    dbus_tube_iface = dbus.Interface(tube_chan, CHANNEL_TYPE_DBUS_TUBE)
    chan_iface = dbus.Interface(tube_chan, CHANNEL)
    tube_props = tube_chan.GetAll(CHANNEL_IFACE_TUBE, dbus_interface=PROPERTIES_IFACE,
        byte_arrays=True)

    tube_self_handle = tube_chan.GetSelfHandle(dbus_interface=CHANNEL_IFACE_GROUP)

    assert tube_props['Parameters'] == sample_parameters
    assert tube_props['State'] == TUBE_CHANNEL_STATE_NOT_OFFERED

    # offer the tube
    call_async(q, dbus_tube_iface, 'OfferDBusTube')

    new_tube_event, presence_event, _, status_event, dbus_changed_event = q.expect_many(
        EventPattern('dbus-signal', signal='NewTube'),
        EventPattern('stream-presence', to='chat2@conf.localhost/test'),
        EventPattern('dbus-return', method='OfferDBusTube'),
        EventPattern('dbus-signal', signal='TubeChannelStateChanged', args=[TUBE_CHANNEL_STATE_OPEN]),
        EventPattern('dbus-signal', signal='DBusNamesChanged', interface=CHANNEL_TYPE_DBUS_TUBE))

    # handle new_tube_event
    dbus_tube_id = new_tube_event.args[0]
    assert new_tube_event.args[2] == TUBE_TYPE_DBUS
    assert new_tube_event.args[3] == 'com.example.TestCase'
    assert new_tube_event.args[4] == sample_parameters
    assert new_tube_event.args[5] == TUBE_STATE_OPEN

    # handle presence_event
    # We announce our newly created tube in our muc presence
    presence = presence_event.stanza
    x_nodes = xpath.queryForNodes('/presence/x[@xmlns="http://jabber.org/'
            'protocol/muc"]', presence)
    assert x_nodes is not None
    assert len(x_nodes) == 1

    tubes_nodes = xpath.queryForNodes('/presence/tubes[@xmlns="%s"]'
        % ns.TUBES, presence)
    assert tubes_nodes is not None
    assert len(tubes_nodes) == 1

    tube_nodes = xpath.queryForNodes('/tubes/tube', tubes_nodes[0])
    assert tube_nodes is not None
    assert len(tube_nodes) == 1
    for tube in tube_nodes:
        tube['type'] = 'dbus'
        assert tube['initiator'] == 'chat2@conf.localhost/test'
        assert tube['service'] == 'com.example.TestCase'
        dbus_stream_id = tube['stream-id']
        my_bus_name = tube['dbus-name']
        assert tube['id'] == str(dbus_tube_id)

    params = {}
    parameter_nodes = xpath.queryForNodes('/tube/parameters/parameter', tube)
    for node in parameter_nodes:
        assert node['name'] not in params
        params[node['name']] = (node['type'], str(node))
    assert params == {'ay': ('bytes', 'aGVsbG8='),
                      's': ('str', 'hello'),
                      'i': ('int', '-123'),
                      'u': ('uint', '123'),
                     }

    # handle dbus_changed_event
    added, removed = dbus_changed_event.args
    assert {tube_self_handle: my_bus_name}
    assert removed == []

    bob_bus_name = ':2.Ym9i'
    bob_handle = conn.RequestHandles(HT_CONTACT, ['chat2@conf.localhost/bob'])[0]

    # Bob joins the tube
    # stream-id=dbus_stream_id dbus-name=
    presence = elem('presence', from_='chat2@conf.localhost/bob', to='chat2@conf.localhost')(
        elem('x', xmlns=ns.MUC),
        elem('tubes', xmlns=ns.TUBES)(
            elem('tube', type='dbus', initiator='chat2@conf.localhost/test',
                service='com.example.TestCase', id=str(dbus_tube_id))(
                    elem('parameters')(
                        elem('parameter', name='ay', type='bytes')(u'aGVsbG8='),
                        elem('parameter', name='s', type='str')(u'hello'),
                        elem('parameter', name='i', type='int')(u'-123'),
                        elem('parameter', name='u', type='uint')(u'123')
                        ))))

    # have to add stream-id and dbus-name attributes manuallya as we can't use
    # keyword with '-'...
    tube_node = xpath.queryForNodes('/presence/tubes/tube', presence)[0]
    tube_node['stream-id'] = dbus_stream_id
    tube_node['dbus-name'] = bob_bus_name
    stream.send(presence)

    dbus_changed_event = q.expect('dbus-signal', signal='DBusNamesChanged',
        interface=CHANNEL_TYPE_DBUS_TUBE)

    added, removed = dbus_changed_event.args
    assert added == {bob_handle: bob_bus_name}
    assert removed == []

    # TODO: use tube
    # TODO: remove bob

    chan_iface.Close()
    q.expect_many(
        EventPattern('dbus-signal', signal='Closed'),
        EventPattern('dbus-signal', signal='ChannelClosed'))

    # OK, we're done
    conn.Disconnect()

    q.expect('dbus-signal', signal='StatusChanged', args=[2, 1])

if __name__ == '__main__':
    exec_test(test)
