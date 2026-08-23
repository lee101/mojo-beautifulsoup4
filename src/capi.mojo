from std.runtime.asyncrt import TaskGroup
from std.sys.info import simd_width_of as simdwidthof


comptime BPtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime IPtr = UnsafePointer[Int64, AnyOrigin[mut=True]]
comptime PREFILTER_PARALLEL_THRESHOLD = 131_072
comptime PREFILTER_CHUNK_SIZE = 16_384


def is_space(c: UInt8) -> Bool:
    return c == 32 or c == 9 or c == 10 or c == 12 or c == 13


def is_name(c: UInt8) -> Bool:
    return (
        (c >= 65 and c <= 90)
        or (c >= 97 and c <= 122)
        or (c >= 48 and c <= 57)
        or c == 45
        or c == 58
        or c == 95
    )


def lower(c: UInt8) -> UInt8:
    if c >= 65 and c <= 90:
        return c + 32
    return c


def starts4(src: BPtr, i: Int, n: Int, a: UInt8, b: UInt8, c: UInt8, d: UInt8) -> Bool:
    return i + 4 <= n and src[i] == a and src[i + 1] == b and src[i + 2] == c and src[i + 3] == d


def raw_kind(src: BPtr, start: Int, end: Int) -> Int:
    var length = end - start
    if length == 6:
        if (
            lower(src[start]) == 115
            and lower(src[start + 1]) == 99
            and lower(src[start + 2]) == 114
            and lower(src[start + 3]) == 105
            and lower(src[start + 4]) == 112
            and lower(src[start + 5]) == 116
        ):
            return 1
    elif length == 5:
        if (
            lower(src[start]) == 115
            and lower(src[start + 1]) == 116
            and lower(src[start + 2]) == 121
            and lower(src[start + 3]) == 108
            and lower(src[start + 4]) == 101
        ):
            return 2
        if (
            lower(src[start]) == 116
            and lower(src[start + 1]) == 105
            and lower(src[start + 2]) == 116
            and lower(src[start + 3]) == 108
            and lower(src[start + 4]) == 101
        ):
            return 3
    elif length == 8:
        if (
            lower(src[start]) == 116
            and lower(src[start + 1]) == 101
            and lower(src[start + 2]) == 120
            and lower(src[start + 3]) == 116
            and lower(src[start + 4]) == 97
            and lower(src[start + 5]) == 114
            and lower(src[start + 6]) == 101
            and lower(src[start + 7]) == 97
        ):
            return 4
    return 0


def raw_matches(src: BPtr, i: Int, n: Int, kind: Int) -> Bool:
    if i + 3 >= n or src[i] != 60 or src[i + 1] != 47:
        return False
    var p = i + 2
    while p < n and is_space(src[p]):
        p += 1
    if kind == 1:
        return p + 6 <= n and lower(src[p]) == 115 and lower(src[p + 1]) == 99 and lower(src[p + 2]) == 114 and lower(src[p + 3]) == 105 and lower(src[p + 4]) == 112 and lower(src[p + 5]) == 116 and (p + 6 == n or is_space(src[p + 6]) or src[p + 6] == 62)
    if kind == 2:
        return p + 5 <= n and lower(src[p]) == 115 and lower(src[p + 1]) == 116 and lower(src[p + 2]) == 121 and lower(src[p + 3]) == 108 and lower(src[p + 4]) == 101 and (p + 5 == n or is_space(src[p + 5]) or src[p + 5] == 62)
    if kind == 3:
        return p + 5 <= n and lower(src[p]) == 116 and lower(src[p + 1]) == 105 and lower(src[p + 2]) == 116 and lower(src[p + 3]) == 108 and lower(src[p + 4]) == 101 and (p + 5 == n or is_space(src[p + 5]) or src[p + 5] == 62)
    return p + 8 <= n and lower(src[p]) == 116 and lower(src[p + 1]) == 101 and lower(src[p + 2]) == 120 and lower(src[p + 3]) == 116 and lower(src[p + 4]) == 97 and lower(src[p + 5]) == 114 and lower(src[p + 6]) == 101 and lower(src[p + 7]) == 97 and (p + 8 == n or is_space(src[p + 8]) or src[p + 8] == 62)


def emit(kind: IPtr, starts: IPtr, ends: IPtr, aux: IPtr, count: Int, k: Int, s: Int, e: Int, a: Int):
    kind[count] = Int64(k)
    starts[count] = Int64(s)
    ends[count] = Int64(e)
    aux[count] = Int64(a)


def tokenize(src: BPtr, n: Int, kind: IPtr, starts: IPtr, ends: IPtr, aux: IPtr) -> Int:
    var i = 0
    var count = 0
    var data_start = 0
    var raw = 0
    while i < n:
        if raw != 0:
            var close = i
            while close < n and not raw_matches(src, close, n, raw):
                close += 1
            if close > i:
                emit(kind, starts, ends, aux, count, 0, i, close, 0)
                count += 1
            i = close
            raw = 0
            if i >= n:
                break
        if src[i] != 60:
            data_start = i
            i += 1
            while i < n and src[i] != 60:
                i += 1
            emit(kind, starts, ends, aux, count, 0, data_start, i, 0)
            count += 1
            continue
        if starts4(src, i, n, 60, 33, 45, 45):
            var p = i + 4
            while p + 2 < n and not (src[p] == 45 and src[p + 1] == 45 and src[p + 2] == 62):
                p += 1
            var close_end = p + 3 if p + 2 < n else n
            emit(kind, starts, ends, aux, count, 3, i + 4, p if p + 2 < n else n, 0)
            count += 1
            i = close_end
            continue
        if i + 1 < n and src[i + 1] == 33:
            var p = i + 2
            while p < n and src[p] != 62:
                p += 1
            emit(kind, starts, ends, aux, count, 4, i + 2, p, 0)
            count += 1
            i = p + 1 if p < n else n
            continue
        if i + 1 < n and src[i + 1] == 63:
            var p = i + 2
            while p < n and src[p] != 62:
                p += 1
            emit(kind, starts, ends, aux, count, 5, i + 2, p, 0)
            count += 1
            i = p + 1 if p < n else n
            continue
        var p = i + 1
        var closing = False
        if p < n and src[p] == 47:
            closing = True
            p += 1
        while p < n and is_space(src[p]):
            p += 1
        var name_start = p
        while p < n and is_name(src[p]):
            p += 1
        var name_end = p
        if name_end == name_start:
            emit(kind, starts, ends, aux, count, 0, i, i + 1, 0)
            count += 1
            i += 1
            continue
        var quote = UInt8(0)
        while p < n:
            var c = src[p]
            if quote != 0:
                if c == quote:
                    quote = 0
            elif c == 34 or c == 39:
                quote = c
            elif c == 62:
                break
            p += 1
        emit(kind, starts, ends, aux, count, 2 if closing else 1, name_start, p, name_end)
        count += 1
        i = p + 1 if p < n else n
        if not closing:
            var tail = p - 1
            while tail > name_end and is_space(src[tail]):
                tail -= 1
            if src[tail] != 47:
                raw = raw_kind(src, name_start, name_end)
    return count


def equal_slice(blob: BPtr, s: Int, e: Int, query: BPtr, qs: Int, qe: Int) -> Bool:
    var length = e - s
    if length != qe - qs:
        return False
    comptime W = simdwidthof[DType.float64]()
    var j = 0
    while j + W <= length:
        if not blob.load[width=W, alignment=1](s + j).eq(
            query.load[width=W, alignment=1](qs + j)
        ).reduce_and():
            return False
        j += W
    while j < length:
        if blob[s + j] != query[qs + j]:
            return False
        j += 1
    return True


def has_class(blob: BPtr, s: Int, e: Int, query: BPtr, qs: Int, qe: Int) -> Bool:
    var length = qe - qs
    if length == 0:
        return True
    var p = s
    while p < e:
        while p < e and blob[p] == 32:
            p += 1
        var token_start = p
        while p < e and blob[p] != 32:
            p += 1
        if equal_slice(blob, token_start, p, query, qs, qe):
            return True
    return False


@export("mbs_tokenize")
def mbs_tokenize(
    src_addr: Int,
    n: Int,
    kind_addr: Int,
    starts_addr: Int,
    ends_addr: Int,
    aux_addr: Int,
) abi("C") -> Int:
    return tokenize(
        BPtr(unsafe_from_address=src_addr),
        n,
        IPtr(unsafe_from_address=kind_addr),
        IPtr(unsafe_from_address=starts_addr),
        IPtr(unsafe_from_address=ends_addr),
        IPtr(unsafe_from_address=aux_addr),
    )


def prefilter_range(
    blob: BPtr,
    ns: IPtr,
    ne: IPtr,
    ids: IPtr,
    ide: IPtr,
    cs: IPtr,
    ce: IPtr,
    query: BPtr,
    tag_start: Int,
    tag_end: Int,
    id_start: Int,
    id_end: Int,
    offsets: IPtr,
    class_count: Int,
    result: BPtr,
    first: Int,
    last: Int,
):
    for i in range(first, last):
        var ok = True
        if tag_end > tag_start and not equal_slice(blob, Int(ns[i]), Int(ne[i]), query, tag_start, tag_end):
            ok = False
        if ok and id_end > id_start and not equal_slice(blob, Int(ids[i]), Int(ide[i]), query, id_start, id_end):
            ok = False
        if ok:
            for c in range(class_count):
                if not has_class(blob, Int(cs[i]), Int(ce[i]), query, Int(offsets[c]), Int(offsets[c + 1])):
                    ok = False
                    break
        result[i] = 1 if ok else 0


async def prefilter_chunk(
    blob: BPtr,
    ns: IPtr,
    ne: IPtr,
    ids: IPtr,
    ide: IPtr,
    cs: IPtr,
    ce: IPtr,
    query: BPtr,
    tag_start: Int,
    tag_end: Int,
    id_start: Int,
    id_end: Int,
    offsets: IPtr,
    class_count: Int,
    result: BPtr,
    chunk: Int,
    node_count: Int,
):
    var first = chunk * PREFILTER_CHUNK_SIZE
    var last = min(first + PREFILTER_CHUNK_SIZE, node_count)
    prefilter_range(
        blob,
        ns,
        ne,
        ids,
        ide,
        cs,
        ce,
        query,
        tag_start,
        tag_end,
        id_start,
        id_end,
        offsets,
        class_count,
        result,
        first,
        last,
    )


@export("mbs_prefilter")
def mbs_prefilter(
    blob_addr: Int,
    name_starts_addr: Int,
    name_ends_addr: Int,
    id_starts_addr: Int,
    id_ends_addr: Int,
    class_starts_addr: Int,
    class_ends_addr: Int,
    node_count: Int,
    query_addr: Int,
    tag_start: Int,
    tag_end: Int,
    id_start: Int,
    id_end: Int,
    class_offsets_addr: Int,
    class_count: Int,
    result_addr: Int,
    parallel_ready: Int,
) abi("C") -> Int:
    var blob = BPtr(unsafe_from_address=blob_addr)
    var ns = IPtr(unsafe_from_address=name_starts_addr)
    var ne = IPtr(unsafe_from_address=name_ends_addr)
    var ids = IPtr(unsafe_from_address=id_starts_addr)
    var ide = IPtr(unsafe_from_address=id_ends_addr)
    var cs = IPtr(unsafe_from_address=class_starts_addr)
    var ce = IPtr(unsafe_from_address=class_ends_addr)
    var query = BPtr(unsafe_from_address=query_addr)
    var offsets = IPtr(unsafe_from_address=class_offsets_addr)
    var result = BPtr(unsafe_from_address=result_addr)

    if parallel_ready != 0 and node_count >= PREFILTER_PARALLEL_THRESHOLD:
        var tasks = TaskGroup()
        for chunk in range(
            (node_count + PREFILTER_CHUNK_SIZE - 1) // PREFILTER_CHUNK_SIZE
        ):
            tasks.create_task(
                prefilter_chunk(
                    blob,
                    ns,
                    ne,
                    ids,
                    ide,
                    cs,
                    ce,
                    query,
                    tag_start,
                    tag_end,
                    id_start,
                    id_end,
                    offsets,
                    class_count,
                    result,
                    chunk,
                    node_count,
                )
            )
        tasks.wait()
    else:
        prefilter_range(
            blob,
            ns,
            ne,
            ids,
            ide,
            cs,
            ce,
            query,
            tag_start,
            tag_end,
            id_start,
            id_end,
            offsets,
            class_count,
            result,
            0,
            node_count,
        )

    comptime W = simdwidthof[DType.float64]()
    var matched = 0
    var i = 0
    while i + W <= node_count:
        matched += Int(result.load[width=W, alignment=1](i).reduce_add())
        i += W
    while i < node_count:
        matched += Int(result[i])
        i += 1
    return matched
