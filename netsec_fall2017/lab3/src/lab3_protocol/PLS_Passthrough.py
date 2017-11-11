import random
import os
import hashlib
from . import CertFactory
# import CertFactory
import cryptography
import OpenSSL
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization, hashes, hmac
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from playground.network.packet import PacketType
from playground.network.common import StackingProtocol, StackingTransport, StackingProtocolFactory
from playground.network.packet.fieldtypes import UINT8, UINT32, UINT64,\
    STRING, BUFFER, LIST, ComplexFieldType, PacketFields
from playground.network.packet.fieldtypes.attributes import Optional
from .PLS_Base import PLS_Base, PLS_Transport
from .PLS_Packets import PlsBasePacket, PlsHello, PlsKeyExchange,\
    PlsHandshakeDone, PlsData, PlsClose

key_dir = os.path.expanduser("~/netsec/keys/")
my_key_path = key_dir + "my.key"
cli_key_path = key_dir + "client.key"
server_key_path = key_dir + "server.key"
cert_dir = os.path.expanduser("~/netsec/certs/")
root_cert_path = cert_dir + "root.crt"
my_cert_path = cert_dir + "my.crt"
cli_cert_path = cert_dir + "client.crt"
server_cert_path = cert_dir + "server.crt"

sha256 = cryptography.hazmat.primitives.hashes.SHA256()
mgf1 = padding.MGF1(sha256)
oaep = padding.OAEP(mgf1, sha256, None)


class PLS_Client(PLS_Base):

    def __init__(self):
        super().__init__()
        with open(cli_key_path, "rb") as key_file:
            self.my_priv_key = serialization.load_pem_private_key(\
                key_file.read(),\
                password = None,\
                backend = default_backend()\
            )

    def connection_made(self, transport):
        super().connection_made(transport)
        self.start_handshake()

    def start_handshake(self):
        cli_hello = PlsHello()
        self.client_nonce = random.getrandbits(64)
        cli_hello.Nonce = self.client_nonce
        cli_cert = CertFactory.getCertsForAddr(cli_cert_path)
        my_cert = CertFactory.getCertsForAddr(my_cert_path)
        root_cert = CertFactory.getCertsForAddr(root_cert_path)
        cli_hello.Certs = [cli_cert.encode(), my_cert.encode(), root_cert.encode()]
        self.m1 = cli_hello.__serialize__()
        self.send_packet(cli_hello)
        self.state = PLS_Base.HELLO

    def handle_hello(self, packet):
        self.m2 = packet.__serialize__()
        if not self.verify_certificate_chain(packet.Certs):
            self.pls_close()
        self.received_pub_key = x509.load_pem_x509_certificate(packet.Certs[0], default_backend()).public_key()
        self.state == PLS_Base.KEYEXCH
        keyexch_packet = PlsKeyExchange()
        self.pkc = "client pre key".encode()
        keyexch_packet.PreKey = self.received_pub_key.encrypt(self.pkc, oaep)
        self.server_nonce = packet.Nonce
        keyexch_packet.NoncePlusOne = self.server_nonce + 1
        self.m3 = keyexch_packet.__serialize__()
        self.send_packet(keyexch_packet)

    def handle_keyexch(self, packet):
        self.m4 = packet.__serialize__()
        try:
            self.pks = self.my_priv_key.decrypt(packet.PreKey, oaep)
        except ValueError as e:
            print(e)
            self.pls_close()
        hsdone_packet = PlsHandshakeDone()
        messages_hash = hashlib.sha1()
        messages_hash.update(self.m1)
        messages_hash.update(self.m2)
        messages_hash.update(self.m3)
        messages_hash.update(self.m4)
        self.validation_hash = messages_hash.digest()
        hsdone_packet.ValidationHash = self.validation_hash
        self.send_packet(hsdone_packet)

    def handle_hsdone(self, packet):
        super().handle_hsdone(packet)
        cli_cipher = Cipher(algorithms.AES(self.ekc), modes.CTR(self.ivc), backend=default_backend())
        server_cipher = Cipher(algorithms.AES(self.eks), modes.CTR(self.ivs), backend=default_backend())
        self.data_encryptor = cli_cipher.encryptor()
        self.data_decryptor = server_cipher.decryptor()
        self.mac_creator = hmac.HMAC(self.mkc, hashes.SHA1(), backend=default_backend())
        self.mac_verifier = hmac.HMAC(self.mks, hashes.SHA1(), backend=default_backend())
        self.higherProtocol().connection_made(PLS_Transport(self.transport, self))


class PLS_Server(PLS_Base):

    def __init__(self):
        super().__init__()
        with open(server_key_path, "rb") as key_file:
            self.my_priv_key = serialization.load_pem_private_key(\
                key_file.read(),\
                password = None,\
                backend = default_backend()\
            )

    def connection_made(self, transport):
        super().connection_made(transport)

    def handle_hello(self, packet):
        self.m1 = packet.__serialize__()
        if not self.verify_certificate_chain(packet.Certs):
            self.pls_close()
        self.received_pub_key = x509.load_pem_x509_certificate(packet.Certs[0], default_backend()).public_key()
        self.state = PLS_Base.HELLO
        hello_packet = PlsHello()
        self.server_nonce = random.getrandbits(64)
        hello_packet.Nonce = self.server_nonce
        server_cert = CertFactory.getCertsForAddr(server_cert_path)
        my_cert = CertFactory.getCertsForAddr(my_cert_path)
        root_cert = CertFactory.getCertsForAddr(root_cert_path)
        hello_packet.Certs = [server_cert.encode(), my_cert.encode(), root_cert.encode()]
        self.m2 = hello_packet.__serialize__()
        self.send_packet(hello_packet)
        self.state == PLS_Base.KEYEXCH
        keyexch_packet = PlsKeyExchange()
        self.pks = "server pre key".encode()
        keyexch_packet.PreKey = self.received_pub_key.encrypt(self.pks, oaep)
        self.client_nonce = packet.Nonce
        keyexch_packet.NoncePlusOne = self.client_nonce + 1
        self.m4 = keyexch_packet.__serialize__()
        self.send_packet(keyexch_packet)

    def handle_keyexch(self, packet):
        self.m3 = packet.__serialize__()
        try:
            self.pkc = self.my_priv_key.decrypt(packet.PreKey, oaep)
        except ValueError as e:
            print(e)
            self.pls_close()
        hsdone_packet = PlsHandshakeDone()
        messages_hash = hashlib.sha1()
        messages_hash.update(self.m1)
        messages_hash.update(self.m2)
        messages_hash.update(self.m3)
        messages_hash.update(self.m4)
        self.validation_hash = messages_hash.digest()
        hsdone_packet.ValidationHash = self.validation_hash
        self.send_packet(hsdone_packet)

    def handle_hsdone(self, packet):
        super().handle_hsdone(packet)
        cli_cipher = Cipher(algorithms.AES(self.ekc), modes.CTR(self.ivc), backend=default_backend())
        server_cipher = Cipher(algorithms.AES(self.eks), modes.CTR(self.ivs), backend=default_backend())
        self.data_encryptor = server_cipher.encryptor()
        self.data_decryptor = cli_cipher.decryptor()
        self.mac_creator = hmac.HMAC(self.mks, hashes.SHA1(), backend=default_backend())
        self.mac_verifier = hmac.HMAC(self.mkc, hashes.SHA1(), backend=default_backend())
        self.higherProtocol().connection_made(PLS_Transport(self.transport, self))


clientFactory = StackingProtocolFactory(PLS_Client)
serverFactory = StackingProtocolFactory(PLS_Server)