"""Platform-independent seeded randomness (Python's salted hash() is never used)."""
import hashlib
import random


def stable_seed(*parts):
    text = '|'.join(map(str, parts)).encode()
    return int.from_bytes(hashlib.sha256(text).digest()[:8], 'big')


def stable_rng(*parts):
    return random.Random(stable_seed(*parts))
