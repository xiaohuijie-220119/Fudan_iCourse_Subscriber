"""Authenticated encryption; filenames are opaque on the public data branch."""
import base64
import hashlib
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def key_bytes(value):
    key = base64.urlsafe_b64decode(value.encode())
    if len(key) != 32:
        raise ValueError('加密密钥格式无效')
    return key

def encrypt(raw, key, identity):
    nonce = os.urandom(12)
    return b'ICN1' + nonce + AESGCM(key_bytes(key)).encrypt(nonce, raw, identity.encode())

def decrypt(raw, key, identity):
    if raw[:4] != b'ICN1':
        raise ValueError('云端文件格式无效')
    return AESGCM(key_bytes(key)).decrypt(raw[4:16], raw[16:], identity.encode())

def blob_name(identity):
    return hashlib.sha256(identity.encode()).hexdigest() + '.enc'
