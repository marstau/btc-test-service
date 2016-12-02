from ethereum import utils
from secp256k1 import PrivateKey, PublicKey, ALL_FLAGS
from . import flatten_payload

def data_decoder(data):
    """Decode `data` representing unformatted data."""
    if not data.startswith('0x'):
        data = '0x' + data

    if len(data) % 2 != 0:
        # workaround for missing leading zeros from netstats
        assert len(data) < 64 + 2
        data = '0x' + '0' * (64 - (len(data) - 2)) + data[2:]

    try:
        return utils.decode_hex(data[2:])
    except TypeError:
        raise Exception('Invalid data hex encoding', data[2:])

def data_encoder(data, length=None):
    """Encode unformatted binary `data`.

    If `length` is given, the result will be padded like this: ``data_encoder('\xff', 3) ==
    '0x0000ff'``.
    """
    s = utils.encode_hex(data).decode('ascii')
    if length is None:
        return '0x' + s
    else:
        return '0x' + s.rjust(length * 2, '0')

def ecrecover(msg, signature, address=None):
    rawhash = utils.sha3(msg)

    v = utils.safe_ord(signature[64]) + 27
    r = utils.big_endian_to_int(signature[0:32])
    s = utils.big_endian_to_int(signature[32:64])

    pk = PublicKey(flags=ALL_FLAGS)
    pk.public_key = pk.ecdsa_recover(
        rawhash,
        pk.ecdsa_recoverable_deserialize(
            utils.zpad(utils.bytearray_to_bytestr(utils.int_to_32bytearray(r)), 32) +
            utils.zpad(utils.bytearray_to_bytestr(utils.int_to_32bytearray(s)), 32),
            v - 27
        ),
        raw=True
    )
    pub = pk.serialize(compressed=False)

    recaddr = data_encoder(utils.sha3(pub[1:])[-20:])
    if address:
        if not address.startswith("0x"):
            recaddr = recaddr[2:]

        return recaddr == address

    return recaddr

def sign_payload(private_key, payload):

    if isinstance(payload, dict):
        payload = flatten_payload(payload)

    rawhash = utils.sha3(payload)

    pk = PrivateKey(private_key, raw=True)
    signature = pk.ecdsa_recoverable_serialize(
        pk.ecdsa_sign_recoverable(rawhash, raw=True)
    )
    signature = signature[0] + utils.bytearray_to_bytestr([signature[1]])

    return data_encoder(signature)
