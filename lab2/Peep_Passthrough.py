import asyncio
import random
import playground
from .Peep_Packets import PEEPPacket
from playground.network.common import StackingProtocol, StackingTransport, StackingProtocolFactory
from playground.network.packet import PacketType

class PEEP_1a(StackingProtocol):

    """
    State Definitions:
        0 - INIT:  we haven't done anything.
        1 - HANDSHAKE: we sent an syn and waiting for server to respond
        2 - TRANS: data transmission. we can also send a rip from this state
        3 - TEARDOWN: we received a RIP from the server. send rip ack and close.
    """

    INIT, HANDSHAKE, TRANS, TEARDOWN = [0,1,2,3]

    def __init__(self):
        super().__init__()
        self.transport = None
        self.state = PEEP_1a.INIT
        self.deserializer = None

    def data_received(self, data):
        print("peep1a: data received")
        self.deserializer.update(data)
        for packet in self.deserializer.nextPackets():
            if isinstance(packet, PEEPPacket):
                if self.state == PEEP_1a.HANDSHAKE:
                    # expecting a synack
                    if (packet.Type == PEEPPacket.SYNACK):
                        # received a synack
                        if packet.verifyChecksum() and packet.Acknowledgement == self.sequence_number + 1:
                            print("peep1a: Received synack")
                            packet_to_send = PEEPPacket()
                            packet_to_send.Type = PEEPPacket.ACK
                            packet_to_send.SequenceNumber = packet.Acknowledgement
                            packet_to_send.Acknowledgement= packet.SequenceNumber+1
                            packet_to_send.updateChecksum()
                            print("peep1a: Sending Back Ack")
                            self.transport.write(packet_to_send.__serialize__())
                            self.state = PEEP_1a.TRANS # transmission state
                            # Open upper layer transport
                            print("peep1a: connection_made to higher protocol")
                            self.higherProtocol().connection_made(PEEP_transport(self.transport, self))
                        else:
                            self.transport.close()
                elif self.state == PEEP_1a.TRANS:
                    # expecting a message packet
                    # TODO: if checksum bad, then don't respond
                    if packet.Type == PEEPPacket.DATA:
                        print("peep1a: Message data received")
                        self.higherProtocol().data_received(packet.Data)

    def connection_made(self, transport):
        self.transport = transport
        self.deserializer = PacketType.Deserializer()
        self.start_handshake()

    def connection_lost(self, exc):
        self.transport.close()
        self.transport = None

    def start_handshake(self):
        self.sequence_number = random.randint(0,2**16)
        print("peep1a: start handshake")
        packet = PEEPPacket()
        packet.Type = self.state
        packet.SequenceNumber = self.sequence_number
        packet.updateChecksum()
        self.transport.write(packet.__serialize__())
        self.state = PEEP_1a.HANDSHAKE

class PEEP_1b(StackingProtocol):

    """
    State Definitions:
        0 - INIT: we have not received any connections
        1 - HANDSHAKE: we received a syn and sent a synack. waiting for ack
        2 - TRANS: getting data
        3 - TEARDOWN: received a rip, sent rip ack; sent a rip, waiting for ripack
    """

    INIT, HANDSHAKE, TRANS, TEARDOWN = [0,1,2,3]

    def __init__(self):
        super().__init__()
        self.transport = None
        self.deserializer = None
        self.state = PEEP_1b.INIT

    def connection_made(self,transport):
        print("peep1b: connection made")
        self.transport = transport
        self.higherProtocol().transport = PEEP_transport(transport, self)
        self.deserializer = PacketType.Deserializer()
        peername = transport.get_extra_info('peername')
        print('server(prepare)-->client(prepare):Connection from {}'.format(peername))

    def data_received(self,data):
        print("peep1b: data received")
        self.deserializer.update(data)
        for pkt in self.deserializer.nextPackets():
            self.handle_packets(pkt)

    def handle_packets(self,pkt):
        if isinstance(pkt, PEEPPacket):
            typenum = pkt.Type
            if typenum == PEEPPacket.SYN and self.state == PEEP_1b.INIT:
                print('peep1b: received SYN')
                self.handle_syn(pkt)
            elif typenum == PEEPPacket.ACK and self.state == PEEP_1b.HANDSHAKE:
                print('peep1b: received ACK')
                self.handle_ack(pkt)
            elif typenum == PEEPPacket.RIP and self.state == PEEP_1b.TRANS:
                print('peep1b: received RIP')
                self.handle_rip(pkt)
            elif typenum == PEEPPacket.RIPACK and self.state == PEEP_1b.TEARDOWN:
                print('peep1b: received RIPACK')
                self.handle_ripack(pkt)
            elif typenum == PEEPPacket.DATA and self.state == PEEP_1b.TRANS:
                print('peep1b: received Data')
                self.handle_data(pkt)
            else:
                print('peep1b: received UNKNOWN TYPE')
        else:
            print('peep1b:This packet is not a PEEPPacket')

    def handle_syn(self,pkt):
        if pkt.verifyChecksum():
            print('peep1b: checksum of SYN is correct')
            pktback = PEEPPacket()
            pktback.Acknowledgement = pkt.SequenceNumber + 1
            pktback.SequenceNumber = random.randint(0,2**16)
            pktback.Type = PEEPPacket.SYNACK
            pktback.updateChecksum()
            self.transport.write(pktback.__serialize__())
            self.state = PEEP_1b.HANDSHAKE
            print('peep1b: sent SYNACK')
        else:
            print('peep1b: checksum of SYN is incorrect')
            self.transport.close()

    def handle_ack(self,pkt):
        if pkt.verifyChecksum():
            print('peep1b: checksum of ACK is correct')
            # send data
            self.state = PEEP_1b.TRANS
            # open upper layer transport
            self.higherProtocol().connection_made(PEEP_transport(self.transport, self))
        else:
            print('peep1b: checksum of ACK is incorrect')
            self.transport.close()

    def handle_data(self, pkt):
        if pkt.verifyChecksum():
            print('peep1b: checksum of data is correct')
            self.higherProtocol().data_received(pkt.Data)
        else:
            print("pee1b: checksum of data is incorrect")

    def handle_rip(self,pkt):
        if pkt.verifyChecksum():
            print('peep1b: checksum of RIP is correct')
            # Sending remaining packets back
            pktback = PEEPPacket()
            pktback.Acknowledgement = pkt.SequenceNumber + 1
            pktback.Type = PEEPPacket.RIPACK
            pktback.updateChecksum()
            self.transport.write(pktback.__serialize__())
            print('peep1b: sent RIPACK')
            self.transport.close()

    def handle_ripack(self,pkt):
        if pkt.verifyChecksum():
            print('peep1b: checksum of RIPACK is correct')
        else:
            print('peep1b: checksum of RIPACK is incorrect')
        self.transport.close()

class PEEP_transport(StackingTransport):

    def __init__(self, transport, protocol):
        self._lowerTransport = transport
        self.protocol = protocol
        self.transport = self._lowerTransport

    def write(self, data):
        print("peep transport write")
        # TODO: need a proper sequence number
        data_packet = PEEPPacket(Type=PEEPPacket.DATA, SequenceNumber=1,\
                                Data=data)
        data_packet.updateChecksum()
        self.transport.write(data_packet.__serialize__())

#    def close(self):
#        self._lowerTransport.close()
#        self.transport = None


clientFactory = StackingProtocolFactory(PEEP_1a)
serverFactory = StackingProtocolFactory(PEEP_1b)