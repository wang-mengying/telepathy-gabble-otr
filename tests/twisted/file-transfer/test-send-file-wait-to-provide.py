from file_transfer_helper import SendFileTest, CHANNEL_TYPE_FILE_TRANSFER, \
    FT_STATE_PENDING, FT_STATE_ACCEPTED, FT_STATE_OPEN, FT_STATE_CHANGE_REASON_REQUESTED, \
    FT_STATE_CHANGE_REASON_NONE, exec_file_transfer_test

class SendFileTransferWaitToProvideTest(SendFileTest):
    def __init__(self, bytestream_cls):
        SendFileTest.__init__(self, bytestream_cls)

        self._actions =  [self.connect, self.check_ft_available, self.announce_contact,
            self.check_ft_available, self.request_ft_channel, self.create_ft_channel, self.got_send_iq,
            self.client_accept_file, self.provide_file, self.send_file, self.close_channel]

    def client_accept_file(self):
        # state is still Pending as remote didn't accept the transfer yet
        state = self.ft_props.Get(CHANNEL_TYPE_FILE_TRANSFER, 'State')
        assert state == FT_STATE_PENDING

        SendFileTest.client_accept_file(self)

        # Remote accepted the transfer
        e = self.q.expect('dbus-signal', signal='FileTransferStateChanged')
        state, reason = e.args
        assert state == FT_STATE_ACCEPTED, state
        assert reason == FT_STATE_CHANGE_REASON_NONE

    def provide_file(self):
        SendFileTest.provide_file(self)

        e = self.q.expect('dbus-signal', signal='InitialOffsetDefined')
        offset = e.args[0]
        # We don't support resume
        assert offset == 0

        # Channel is open. We can start to send the file
        e = self.q.expect('dbus-signal', signal='FileTransferStateChanged')
        state, reason = e.args
        assert state == FT_STATE_OPEN
        assert reason == FT_STATE_CHANGE_REASON_REQUESTED

if __name__ == '__main__':
    exec_file_transfer_test(SendFileTransferWaitToProvideTest)