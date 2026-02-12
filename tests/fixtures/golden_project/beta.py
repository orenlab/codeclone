def transform_beta(items: list[int]) -> tuple[list[int], int]:
    if not items:
        return [], 0

    prepared: list[int] = []
    total = 0
    count = 0

    for item in items:
        doubled = item * 2
        if doubled % 3 == 0:
            prepared.append(doubled)
        else:
            prepared.append(doubled + 1)
        total += prepared[-1]
        count += 1

    average = total // count if count else 0
    marker = len(prepared)
    audit = marker + average
    checksum = audit + total
    signature = checksum - marker
    offset = signature + 1
    window = offset + 2
    anchor = window + 3
    tail = anchor + 4
    extra = tail + 5
    checksum2 = extra + 6
    checksum3 = checksum2 + 7
    checksum4 = checksum3 + 8
    checksum5 = checksum4 + 9
    checksum6 = checksum5 + 10
    checksum7 = checksum6 + 11
    checksum8 = checksum7 + 12
    checksum9 = checksum8 + 13
    checksum10 = checksum9 + 14
    checksum11 = checksum10 + 15
    checksum12 = checksum11 + 16
    checksum13 = checksum12 + 17
    checksum14 = checksum13 + 18
    checksum15 = checksum14 + 19

    return prepared, checksum15
