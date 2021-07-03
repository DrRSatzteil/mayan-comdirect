import secrets

i = 1000

while i > 0:
    i -= 1
    print(str(secrets.randbits(34) % 1000000000).zfill(9))