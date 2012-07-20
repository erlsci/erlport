# Copyright (c) 2009-2012, Dmitry Vasiliev <dima@hlabs.org>
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 
#  * Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#  * Neither the name of the copyright holders nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission. 
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""Erlang external term format.

See Erlang External Term Format for details:
    http://www.erlang.org/doc/apps/erts/erl_ext_dist.html
"""

__author__ = "Dmitry Vasiliev <dima@hlabs.org>"

from struct import pack, unpack
from array import array
from zlib import decompressobj, compress
from cPickle import loads, dumps


class IncompleteData(ValueError):
    """Need more data."""


class Atom(str):
    """Erlang atom."""

    def __new__(cls, s):
        if len(s) > 255:
            raise ValueError("invalid atom length")
        return super(Atom, cls).__new__(cls, s)

    def __repr__(self):
        return "atom(%s)" % super(Atom, self).__repr__()


class String(unicode):
    """Erlang list/string wrapper."""

    def __new__(cls, s):
        if isinstance(s, list):
            # Raise TypeError
            s = u"".join(unichr(i) for i in s)
        elif not isinstance(s, unicode):
            raise TypeError("list or unicode object expected")
        return super(String, cls).__new__(cls, s)

    def __repr__(self):
        return "string(%s)" % super(String, self).__repr__()


class BitBinary(str):
    """Erlang bitstring whose length in bits is not a multiple of 8."""

    def __new__(cls, s, bits):
        obj = super(BitBinary, cls).__new__(cls, s)
        obj.bits = bits
        return obj

    def __repr__(self):
        return "bits(%s, %s)" % (self.bits, super(BitBinary, self).__repr__())


class Pid(object):
    """Erlang process identifier."""

    __slots__ = "node", "id", "serial", "creation"

    def __init__(self, node, id, serial, creation):
        self.node = node
        self.id = id
        self.serial = serial
        self.creation = creation

    def __eq__(self, other):
        return (type(self) == type(other)
            and (self.node, self.id, self.serial, self.creation)
                == (other.node, other.id, other.serial, other.creation))

    def __hash__(self):
        hash((self.__module__, self.__name__,
            self.node, self.id, self.serial, self.creation))

    def __repr__(self):
        return "pid(%r, %r, %r, %r)" % (self.node, self.id, self.serial,
            self.creation)


class Reference(object):
    """Erlang reference."""

    __slots__ = "node", "id", "creation"

    def __init__(self, node, id, creation):
        self.node = node
        self.id = id
        self.creation = creation

    def __eq__(self, other):
        return (type(self) == type(other)
            and (self.node, self.id, self.creation)
                == (other.node, other.id, other.creation))

    def __hash__(self):
        hash((self.__module__, self.__name__,
            self.node, self.id, self.creation))

    def __repr__(self):
        return "ref(%r, %r, %r)" % (self.node, self.id, self.creation)


class Port(object):
    """Erlang port."""

    __slots__ = "node", "id", "creation"

    def __init__(self, node, id, creation):
        self.node = node
        self.id = id
        self.creation = creation

    def __eq__(self, other):
        return (type(self) == type(other)
            and (self.node, self.id, self.creation)
                == (other.node, other.id, other.creation))

    def __hash__(self):
        hash((self.__module__, self.__name__,
            self.node, self.id, self.creation))

    def __repr__(self):
        return "port(%r, %r, %r)" % (self.node, self.id, self.creation)


class Export(object):
    """Erlang function export fun M:F/A."""

    __slots__ = "module", "function", "arity"

    def __init__(self, module, function, arity):
        self.module = module
        self.function = function
        self.arity = arity

    def __eq__(self, other):
        return (type(self) == type(other)
            and (self.module, self.function, self.arity)
                == (other.module, other.function, other.arity))

    def __hash__(self):
        hash((self.__module__, self.__name__,
            self.module, self.function, self.arity))

    def __repr__(self):
        return "export(%r, %r, %r)" % (self.module, self.function, self.arity)


def decode(string):
    """Decode Erlang external term."""
    if not string:
        raise IncompleteData("incomplete data: %r" % string)
    version = ord(string[0])
    if version != 131:
        raise ValueError("unknown protocol version: %i" % version)
    if string[1:2] == '\x50':
        # compressed term
        if len(string) < 6:
            raise IncompleteData("incomplete data: %r" % string)
        d = decompressobj()
        zlib_data = string[6:]
        term_string = d.decompress(zlib_data) + d.flush()
        uncompressed_size = unpack('>I', string[2:6])[0]
        if len(term_string) != uncompressed_size:
            raise ValueError(
                "invalid compressed tag, "
                "%d bytes but got %d" % (uncompressed_size, len(term_string)))
        # tail data returned by decode_term() can be simple ignored
        return decode_term(term_string)[0], d.unused_data
    return decode_term(string[1:])


def decode_term(string,
                # Hack to turn globals into locals
                len=len, ord=ord, unpack=unpack, tuple=tuple, float=float,
                BitBinary=BitBinary, Atom=Atom):
    if not string:
        raise IncompleteData("incomplete data: %r" % string)
    tag = ord(string[0])
    tail = string[1:]
    if tag == 97:
        # SMALL_INTEGER_EXT
        if not tail:
            raise IncompleteData("incomplete data: %r" % string)
        return ord(tail[:1]), tail[1:]
    elif tag == 98:
        # INTEGER_EXT
        if len(tail) < 4:
            raise IncompleteData("incomplete data: %r" % string)
        i, = unpack(">i", tail[:4])
        return i, tail[4:]
    elif tag == 106:
        # NIL_EXT
        return [], tail
    elif tag == 107:
        # STRING_EXT
        if len(tail) < 2:
            raise IncompleteData("incomplete data: %r" % string)
        length, = unpack(">H", tail[:2])
        tail = tail[2:]
        if len(tail) < length:
            raise IncompleteData("incomplete data: %r" % string)
        return [ord(i) for i in tail[:length]], tail[length:]
    elif tag == 108:
        # LIST_EXT
        if len(tail) < 4:
            raise IncompleteData("incomplete data: %r" % string)
        length, = unpack(">I", tail[:4])
        tail = tail[4:]
        lst = []
        while length > 0:
            term, tail = decode_term(tail)
            lst.append(term)
            length -= 1
        ignored, tail = decode_term(tail)
        return lst, tail
    elif tag == 109:
        # BINARY_EXT
        if len(tail) < 4:
            raise IncompleteData("incomplete data: %r" % string)
        length, = unpack(">I", tail[:4])
        tail = tail[4:]
        if len(tail) < length:
            raise IncompleteData("incomplete data: %r" % string)
        return tail[:length], tail[length:]
    elif tag == 100:
        # ATOM_EXT
        if len(tail) < 2:
            raise IncompleteData("incomplete data: %r" % string)
        length, = unpack(">H", tail[:2])
        tail = tail[2:]
        if len(tail) < length:
            raise IncompleteData("incomplete data: %r" % string)
        name = tail[:length]
        tail = tail[length:]
        if name == "true":
            return True, tail
        elif name == "false":
            return False, tail
        elif name == "none":
            return None, tail
        return Atom(name), tail
    elif tag == 104 or tag == 105:
        # SMALL_TUPLE_EXT, LARGE_TUPLE_EXT
        if tag == 104:
            if not tail:
                raise IncompleteData("incomplete data: %r" % string)
            arity = ord(tail[0])
            tail = tail[1:]
        else:
            if len(tail) < 4:
                raise IncompleteData("incomplete data: %r" % string)
            arity, = unpack(">I", tail[:4])
            tail = tail[4:]
        lst = []
        while arity > 0:
            term, tail = decode_term(tail)
            lst.append(term)
            arity -= 1
        if len(lst) == 2 and lst[0] == Atom("python_pickle"):
            return loads(lst[1]), tail
        return tuple(lst), tail
    elif tag == 70:
        # NEW_FLOAT_EXT
        term, = unpack(">d", tail[:8])
        return term, tail[8:]
    elif tag == 99:
        # FLOAT_EXT
        return float(tail[:31].split("\x00", 1)[0]), tail[31:]
    elif tag == 110 or tag == 111:
        # SMALL_BIG_EXT, LARGE_BIG_EXT
        if tag == 110:
            if len(tail) < 2:
                raise IncompleteData("incomplete data: %r" % string)
            length, sign = unpack(">BB", tail[:2])
            tail = tail[2:]
        else:
            if len(tail) < 5:
                raise IncompleteData("incomplete data: %r" % string)
            length, sign = unpack(">IB", tail[:5])
            tail = tail[5:]
        if len(tail) < length:
            raise IncompleteData("incomplete data: %r" % string)
        n = 0
        for i in array('B', tail[length-1::-1]):
            n = (n << 8) | i
        if sign:
            n = -n
        return n, tail[length:]
    elif tag == 77:
        # BIT_BINARY_EXT
        if len(tail) < 5:
            raise IncompleteData("incomplete data: %r" % string)
        length, bits = unpack(">IB", tail[:5])
        tail = tail[5:]
        if len(tail) < length:
            raise IncompleteData("incomplete daata: %r" % string)
        return BitBinary(tail[:length], bits), tail[length:]
    elif tag == 103:
        # PID_EXT
        node, tail = decode_term(tail)
        if len(tail) < 9:
            raise IncompleteData("incomplete data: %r" % string)
        id = tail[:4]
        serial = tail[4:8]
        creation = ord(tail[8])
        return Pid(node, id, serial, creation), tail[9:]
    elif tag == 101:
        # REFERENCE_EXT
        node, tail = decode_term(tail)
        if len(tail) < 5:
            raise IncompleteData("incomplete data: %r" % string)
        id = tail[:4]
        creation = ord(tail[4])
        return Reference(node, id, creation), tail[5:]
    elif tag == 102:
        # PORT_EXT
        node, tail = decode_term(tail)
        if len(tail) < 5:
            raise IncompleteData("incomplete data: %r" % string)
        id = tail[:4]
        creation = ord(tail[4])
        return Port(node, id, creation), tail[5:]
    elif tag == 114:
        # NEW_REFERENCE_EXT
        if len(tail) < 2:
            raise IncompleteData("incomplete data: %r" % string)
        num, = unpack(">H", tail[:2])
        length = num * 4
        node, tail = decode_term(tail[2:])
        if len(tail) < 1 + length:
            raise IncompleteData("incomplete data: %r" % string)
        creation = ord(tail[0])
        id = tail[1:length + 1]
        return Reference(node, id, creation), tail[length + 1:]
    elif tag == 113:
        # EXPORT_EXT
        module, tail = decode_term(tail)
        function, tail = decode_term(tail)
        arity, tail = decode_term(tail)
        return Export(module, function, arity), tail

    raise ValueError("unsupported data tag: %i" % tag)


def encode(term, compressed=False):
    """Encode Erlang external term."""
    encoded_term = encode_term(term)
    # False and 0 do not attempt compression.
    if compressed:
        if compressed is True:
            # default compression level of 6
            compressed = 6
        zlib_term = compress(encoded_term, compressed)
        if len(zlib_term) + 5 <= len(encoded_term):
            # compressed term is smaller
            return '\x83\x50' + pack('>I', len(encoded_term)) + zlib_term
    return "\x83" + encoded_term


def encode_term(term,
                # Hack to turn globals into locals
                pack=pack, tuple=tuple, len=len, isinstance=isinstance,
                list=list, int=int, long=long, array=array, unicode=unicode,
                Atom=Atom, BitBinary=BitBinary, str=str, float=float, ord=ord,
                dict=dict, True=True, False=False,
                ValueError=ValueError, OverflowError=OverflowError):
    if isinstance(term, tuple):
        arity = len(term)
        if arity <= 255:
            header = 'h%c' % arity
        elif arity <= 4294967295:
            header = pack(">BI", 105, arity)
        else:
            raise ValueError("invalid tuple arity")
        _encode_term = encode_term
        return header + "".join(_encode_term(t) for t in term)
    if isinstance(term, list):
        if not term:
            return "j"
        length = len(term)
        if length <= 65535:
            try:
                # array coersion will allow floats as a deprecated feature
                for t in term:
                    if not isinstance(t, (int, long)):
                        raise TypeError
                bytes = array('B', term).tostring()
            except (TypeError, OverflowError):
                pass
            else:
                if len(bytes) == length:
                    return pack(">BH", 107, length) + bytes
        elif length > 4294967295:
            raise ValueError("invalid list length")
        header = pack(">BI", 108, length)
        _encode_term = encode_term
        return header + "".join(_encode_term(t) for t in term) + "j"
    elif isinstance(term, unicode):
        if not term:
            return "j"
        length = len(term)
        if length <= 65535:
            try:
                bytes = term.encode("latin1")
            except UnicodeEncodeError:
                pass
            else:
                return pack(">BH", 107, length) + bytes
        return encode_term([ord(i) for i in term])
    elif isinstance(term, Atom):
        return pack(">BH", 100, len(term)) + term
    # Must be before str type
    elif isinstance(term, BitBinary):
        return pack(">BIB", 77, len(term), term.bits) + term
    elif isinstance(term, str):
        length = len(term)
        if length > 4294967295:
            raise ValueError("invalid binary length")
        return pack(">BI", 109, length) + term
    # Must be before int type
    elif term is True or term is False:
        term = term and 'true' or 'false'
        return pack(">BH", 100, len(term)) + term
    elif isinstance(term, (int, long)):
        if 0 <= term <= 255:
            return 'a%c' % term
        elif -2147483648 <= term <= 2147483647:
            return pack(">Bi", 98, term)

        if term >= 0:
            sign = 0
        else:
            sign = 1
            term = -term

        bytes = array('B')
        while term > 0:
            bytes.append(term & 0xff)
            term >>= 8

        length = len(bytes)
        if length <= 255:
            return pack(">BBB", 110, length, sign) + bytes.tostring()
        elif length <= 4294967295:
            return pack(">BIB", 111, length, sign) + bytes.tostring()
        raise ValueError("invalid integer value")
    elif isinstance(term, float):
        return pack(">Bd", 70, term)
    elif isinstance(term, dict):
        # encode dict as proplist, but will be orddict compatible if keys
        # are all of the same type.
        items = term.items()
        # Faster than sorted(term.iteritems())
        items.sort()
        return encode_term(items)
    elif term is None:
        return pack(">BH", 100, 4) + "none"
    elif isinstance(term, Pid):
        node = encode_term(term.node)
        if len(term.serial) != 4:
            raise ValueError("invalid pid serial field")
        return "g" + node + term.id + term.serial + "%c" % term.creation
    elif isinstance(term, Reference):
        node = encode_term(term.node)
        num = len(term.id) // 4
        return "r" + pack(">H", num) + node + "%c" % term.creation + term.id
    elif isinstance(term, Port):
        node = encode_term(term.node)
        if len(term.id) != 4:
            raise ValueError("invalid port id field")
        return "f" + node + term.id + "%c" % term.creation
    elif isinstance(term, Export):
        module = encode_term(term.module)
        function = encode_term(term.function)
        arity = encode_term(term.arity)
        return "q" + module + function + arity

    try:
        data = dumps(term, -1)
    except:
        raise ValueError("unsupported data type: %s" % type(term))
    return encode_term((Atom("python_pickle"), data))