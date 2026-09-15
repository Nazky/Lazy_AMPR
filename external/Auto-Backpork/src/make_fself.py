#!/usr/bin/env python3

##############################################################################################################
# Make Fake Signed ELF modified by @NazkyYT                                                   			     #
# Original script by john-tornblom                                                              			 #
# Link to the original: https://github.com/ps5-payload-dev/sdk/blob/master/samples/install_app/make_fself.py #
##############################################################################################################

import sys, os, struct, traceback
import hashlib, hmac
import argparse, re, string
from typing import Dict, Optional, Tuple, List, Any

def int_with_base_type(val):
    return int(val, 0)

def try_parse_int(x, base=0):
    try:
        return int(x, base) if isinstance(x, str) else int(x)
    except:
        return None

def align_up(x, alignment):
    return (x + (alignment - 1)) & ~(alignment - 1)

def align_down(x, alignment):
    return x & ~(alignment - 1)

def ilog2(x):
    if x <= 0:
        raise ValueError('math domain error')
    return len(bin(x)) - 3

def is_intervals_overlap(p1, p2):
    return p1[0] <= p2[1] and p1[1] <= p2[0]

def check_file_magic(f, expected_magic):
    old_offset = f.tell()
    try:
        magic = f.read(len(expected_magic))
    except:
        return False
    finally:
        f.seek(old_offset)
    return magic == expected_magic

def parse_version(version):
    major, minor, patch = (version >> 8) & 0xFF, version & 0xFF, 0  # FIXME
    major = 10 * (major >> 4) + (major & 0xF)
    minor = 10 * (minor >> 4) + (minor & 0xF)
    return '{0:d}.{1:02d}.{2:03d}'.format(major, minor, patch)

def sha256(data):
    return hashlib.sha256(data).digest()

def hmac_sha256(key, data):
    return hmac.new(key=key, msg=data, digestmod=hashlib.sha256).digest()

class ElfError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return repr(self.msg)

class ElfEHdr(object):
    FMT = '<4s5B6xB'
    EX_FMT = '<2HI3QI6H'

    MAGIC = b'\x7FELF'
    CLASS64 = 0x2
    DATA2LSB = 0x1
    EM_X86_64 = 0x3E
    EV_CURRENT = 0x1

    ET_EXEC = 0x2
    ET_SCE_EXEC = 0xFE00
    ET_SCE_EXEC_ASLR = 0xFE10
    ET_SCE_DYNAMIC = 0xFE18

    def __init__(self):
        self.magic = None
        self.machine_class = None
        self.data_encoding = None
        self.version = None
        self.os_abi = None
        self.abi_version = None
        self.nident_size = None
        self.type = None
        self.machine = None
        self.version = None
        self.entry = None
        self.phoff = None
        self.shoff = None
        self.flags = None
        self.ehsize = None
        self.phentsize = None
        self.phnum = None
        self.shentsize = None
        self.shnum = None
        self.shstridx = None

    def load(self, f):
        if not check_file_magic(f, ElfEHdr.MAGIC):
            raise ElfError('Invalid magic.')

        self.magic, self.machine_class, self.data_encoding, self.version, self.os_abi, self.abi_version, self.nident_size = struct.unpack(ElfEHdr.FMT, f.read(struct.calcsize(ElfEHdr.FMT)))
        if self.machine_class != ElfEHdr.CLASS64 or self.data_encoding != ElfEHdr.DATA2LSB:
            raise ElfError('Unsupported class or data encoding.')
        self.type, self.machine, self.version, self.entry, self.phoff, self.shoff, self.flags, self.ehsize, self.phentsize, self.phnum, self.shentsize, self.shnum, self.shstridx = struct.unpack(ElfEHdr.EX_FMT, f.read(struct.calcsize(ElfEHdr.EX_FMT)))
        if self.machine != ElfEHdr.EM_X86_64 or self.version != ElfEHdr.EV_CURRENT:
            raise ElfError('Unsupported machine type or version.')
        if self.phentsize != struct.calcsize(ElfPHdr.FMT) or (self.shentsize > 0 and self.shentsize != struct.calcsize(ElfSHdr.FMT)):
            raise ElfError('Unsupported header entry size.')
        if self.type not in [ElfEHdr.ET_EXEC, ElfEHdr.ET_SCE_EXEC, ElfEHdr.ET_SCE_EXEC_ASLR, ElfEHdr.ET_SCE_DYNAMIC]:
            raise ElfError('Unsupported type.')

    def save(self, f):
        f.write(struct.pack(ElfEHdr.FMT, self.magic, self.machine_class, self.data_encoding, self.version, self.os_abi, self.abi_version, self.nident_size))
        f.write(struct.pack(ElfEHdr.EX_FMT, self.type, self.machine, self.version, self.entry, self.phoff, self.shoff, self.flags, self.ehsize, self.phentsize, self.phnum, self.shentsize, self.shnum, self.shstridx))

    def has_segments(self):
        return self.phentsize > 0 and self.phnum > 0

    def has_sections(self):
        return self.shentsize > 0 and self.shnum > 0

class ElfPHdr(object):
    FMT = '<2I6Q'

    PT_LOAD = 0x1
    PT_DYNAMIC = 0x2
    PT_INTERP = 0x3
    PT_TLS = 0x7
    PT_GNU_EH_FRAME = 0x6474E550
    PT_GNU_STACK = 0x6474E551
    PT_SCE_RELA = 0x60000000,
    PT_SCE_DYNLIBDATA = 0x61000000
    PT_SCE_PROCPARAM = 0x61000001
    PT_SCE_MODULE_PARAM = 0x61000002
    PT_SCE_RELRO = 0x61000010
    PT_SCE_COMMENT = 0x6FFFFF00
    PT_SCE_VERSION = 0x6FFFFF01

    PF_EXEC = 0x1
    PF_WRITE = 0x2
    PF_READ = 0x4
    PF_READ_EXEC = PF_READ | PF_EXEC
    PF_READ_WRITE = PF_READ | PF_WRITE

    def __init__(self, idx):
        self.idx = idx
        self.type = None
        self.flags = None
        self.offset = None
        self.vaddr = None
        self.paddr = None
        self.filesz = None
        self.memsz = None
        self.align = None

    def load(self, f):
        self.type, self.flags, self.offset, self.vaddr, self.paddr, self.filesz, self.memsz, self.align = struct.unpack(ElfPHdr.FMT, f.read(struct.calcsize(ElfPHdr.FMT)))

    def save(self, f):
        f.write(struct.pack(ElfPHdr.FMT, self.type, self.flags, self.offset, self.vaddr, self.paddr, self.filesz, self.memsz, self.align))

class ElfSHdr(object):
    FMT = '<2I4Q2I2Q'

    def __init__(self, idx):
        self.idx = idx
        self.name = None
        self.type = None
        self.flags = None
        self.addr = None
        self.offset = None
        self.size = None
        self.link = None
        self.info = None
        self.align = None
        self.entsize = None

    def load(self, f):
        self.name, self.type, self.flags, self.addr, self.offset, self.size, self.link, self.info, self.align, self.entsize = struct.unpack(ElfSHdr.FMT, f.read(struct.calcsize(ElfSHdr.FMT)))

    def save(self, f):
        f.write(struct.pack(ElfSHdr.FMT, self.name, self.type, self.flags, self.addr, self.offset, self.size, self.link, self.info, self.align, self.entsize))

class ElfFile(object):
    def __init__(self, **kwargs):
        self.ehdr = None
        self.phdrs = None
        self.shdrs = None
        self.file_size = None
        self.digest = None
        self.segments = None
        self.sections = None
        self.ignore_shdrs = 'ignore_shdrs' in kwargs and kwargs['ignore_shdrs']

    def load(self, f):
        start_offset = f.tell()
        data = f.read()
        self.file_size = len(data)
        self.digest = sha256(data)
        f.seek(start_offset)

        self.ehdr = ElfEHdr()
        self.ehdr.load(f)

        if self.ignore_shdrs:
            self.ehdr.shnum = 0

        self.phdrs = []
        self.segments = []
        if self.ehdr.has_segments():
            for i in range(self.ehdr.phnum):
                f.seek(start_offset + self.ehdr.phoff + i * self.ehdr.phentsize)
                phdr = ElfPHdr(i)
                phdr.load(f)
                self.phdrs.append(phdr)
                if phdr.filesz > 0:
                    f.seek(start_offset + phdr.offset)
                    data = f.read(phdr.filesz)
                else:
                    data = b''
                self.segments.append(data)

        self.shdrs = []
        self.sections = []
        if self.ehdr.has_sections():
            for i in range(self.ehdr.shnum):
                f.seek(start_offset + self.ehdr.shoff + i * self.ehdr.shentsize)
                shdr = ElfSHdr(i)
                shdr.load(f)
                self.shdrs.append(shdr)
                if shdr.size > 0 and shdr.type != 8:  # SHT_NOBITS
                    f.seek(start_offset + shdr.offset)
                    data = f.read(shdr.size)
                else:
                    data = b''
                self.sections.append(data)

    def save(self, f, no_sections=False):
        start_offset = f.tell()

        self.ehdr.save(f)

        if not no_sections:
            if self.ehdr.has_sections():
                for i in range(self.ehdr.shnum):
                    f.seek(start_offset + self.ehdr.shoff + i * self.ehdr.shentsize)
                    shdr = self.shdrs[i]
                    shdr.save(f)

        if self.ehdr.has_segments():
            for i in range(self.ehdr.phnum):
                f.seek(start_offset + self.ehdr.phoff + i * self.ehdr.phentsize)
                phdr = self.phdrs[i]
                phdr.save(f)

DIGEST_SIZE = 0x20
SIGNATURE_SIZE = 0x100
BLOCK_SIZE = 0x4000
DEFAULT_BLOCK_SIZE = 0x1000

SELF_CONTROL_BLOCK_TYPE_NPDRM = 0x3
SELF_NPDRM_CONTROL_BLOCK_CONTENT_ID_SIZE = 0x13
SELF_NPDRM_CONTROL_BLOCK_RANDOM_PAD_SIZE = 0xD

EMPTY_DIGEST = b'\0' * DIGEST_SIZE
EMPTY_SIGNATURE = b'\0' * SIGNATURE_SIZE

class SignedElfEntry(object):
    FMT = '<4Q'

    PROPS_ORDER_SHIFT = 0
    PROPS_ORDER_MASK = 0x1
    PROPS_ENCRYPTED_SHIFT = 1
    PROPS_ENCRYPTED_MASK = 0x1
    PROPS_SIGNED_SHIFT = 2
    PROPS_SIGNED_MASK = 0x1
    PROPS_COMPRESSED_SHIFT = 3
    PROPS_COMPRESSED_MASK = 0x1
    PROPS_WINDOW_BITS_SHIFT = 8
    PROPS_WINDOW_BITS_MASK = 0x7
    PROPS_HAS_BLOCKS_SHIFT = 11
    PROPS_HAS_BLOCKS_MASK = 0x1
    PROPS_BLOCK_SIZE_SHIFT = 12
    PROPS_BLOCK_SIZE_MASK = 0xF
    PROPS_HAS_DIGESTS_SHIFT = 16
    PROPS_HAS_DIGESTS_MASK = 0x1
    PROPS_HAS_EXTENTS_SHIFT = 17
    PROPS_HAS_EXTENTS_MASK = 0x1
    PROPS_HAS_META_SEGMENT_SHIFT = 20
    PROPS_HAS_META_SEGMENT_MASK = 0x1
    PROPS_SEGMENT_INDEX_SHIFT = 20
    PROPS_SEGMENT_INDEX_MASK = 0xFFFF
    PROPS_DEFAULT_BLOCK_SIZE = 0x1000
    PROPS_META_SEGMENT_MASK = 0xF0000

    def __init__(self, index):
        self.index = index
        self.props = None
        self.offset = None
        self.filesz = None
        self.memsz = None
        self.data = None

    def save(self, f):
        f.write(struct.pack(self.FMT, self.props, self.offset, self.filesz, self.memsz))

    @property
    def order(self):
        return (self.props >> self.PROPS_ORDER_SHIFT) & self.PROPS_ORDER_MASK

    @order.setter
    def order(self, value):
        self.props &= ~(self.PROPS_ORDER_MASK << self.PROPS_ORDER_SHIFT)
        self.props |= (value & self.PROPS_ORDER_MASK) << self.PROPS_ORDER_SHIFT

    @property
    def encrypted(self):
        return ((self.props >> self.PROPS_ENCRYPTED_SHIFT) & self.PROPS_ENCRYPTED_MASK) != 0

    @encrypted.setter
    def encrypted(self, value):
        self.props &= ~(self.PROPS_ENCRYPTED_MASK << self.PROPS_ENCRYPTED_SHIFT)
        if value:
            self.props |= self.PROPS_ENCRYPTED_MASK << self.PROPS_ENCRYPTED_SHIFT

    @property
    def signed(self):
        return ((self.props >> self.PROPS_SIGNED_SHIFT) & self.PROPS_SIGNED_MASK) != 0

    @signed.setter
    def signed(self, value):
        self.props &= ~(self.PROPS_SIGNED_MASK << self.PROPS_SIGNED_SHIFT)
        if value:
            self.props |= self.PROPS_SIGNED_MASK << self.PROPS_SIGNED_SHIFT

    @property
    def compressed(self):
        return ((self.props >> self.PROPS_COMPRESSED_SHIFT) & self.PROPS_COMPRESSED_MASK) != 0

    @compressed.setter
    def compressed(self, value):
        self.props &= ~(self.PROPS_COMPRESSED_MASK << self.PROPS_COMPRESSED_SHIFT)
        if value:
            self.props |= self.PROPS_COMPRESSED_MASK << self.PROPS_COMPRESSED_SHIFT

    @property
    def has_blocks(self):
        return ((self.props >> self.PROPS_HAS_BLOCKS_SHIFT) & self.PROPS_HAS_BLOCKS_MASK) != 0

    @has_blocks.setter
    def has_blocks(self, value):
        self.props &= ~(self.PROPS_HAS_BLOCKS_MASK << self.PROPS_HAS_BLOCKS_SHIFT)
        if value:
            self.props |= self.PROPS_HAS_BLOCKS_MASK << self.PROPS_HAS_BLOCKS_SHIFT

    @property
    def has_digests(self):
        return ((self.props >> self.PROPS_HAS_DIGESTS_SHIFT) & self.PROPS_HAS_DIGESTS_MASK) != 0

    @has_digests.setter
    def has_digests(self, value):
        self.props &= ~(self.PROPS_HAS_DIGESTS_MASK << self.PROPS_HAS_DIGESTS_SHIFT)
        if value:
            self.props |= self.PROPS_HAS_DIGESTS_MASK << self.PROPS_HAS_DIGESTS_SHIFT

    @property
    def has_extents(self):
        return ((self.props >> self.PROPS_HAS_EXTENTS_SHIFT) & self.PROPS_HAS_EXTENTS_MASK) != 0

    @has_extents.setter
    def has_extents(self, value):
        self.props &= ~(self.PROPS_HAS_EXTENTS_MASK << self.PROPS_HAS_EXTENTS_SHIFT)
        if value:
            self.props |= self.PROPS_HAS_EXTENTS_MASK << self.PROPS_HAS_EXTENTS_SHIFT

    @property
    def has_meta_segment(self):
        return ((self.props >> self.PROPS_HAS_META_SEGMENT_SHIFT) & self.PROPS_HAS_META_SEGMENT_MASK) != 0

    @has_meta_segment.setter
    def has_meta_segment(self, value):
        self.props &= ~(self.PROPS_HAS_META_SEGMENT_MASK << self.PROPS_HAS_META_SEGMENT_SHIFT)
        if value:
            self.props |= self.PROPS_HAS_META_SEGMENT_MASK << self.PROPS_HAS_META_SEGMENT_SHIFT

    @property
    def wbits(self):
        return (self.props >> self.PROPS_WINDOW_BITS_SHIFT) & self.PROPS_WINDOW_BITS_MASK

    @wbits.setter
    def wbits(self, value):
        self.props &= ~(self.PROPS_WINDOW_BITS_MASK << self.PROPS_WINDOW_BITS_SHIFT)
        self.props |= (value & self.PROPS_WINDOW_BITS_MASK) << self.PROPS_WINDOW_BITS_SHIFT

    @property
    def block_size(self):
        if self.has_blocks:
            return 1 << (12 + (self.props >> self.PROPS_BLOCK_SIZE_SHIFT) & self.PROPS_BLOCK_SIZE_MASK)
        else:
            return DEFAULT_BLOCK_SIZE

    @block_size.setter
    def block_size(self, value):
        self.props &= ~(self.PROPS_BLOCK_SIZE_MASK << self.PROPS_BLOCK_SIZE_SHIFT)
        if self.has_blocks:
            value = ilog2(value) - 12
        else:
            value = 0  # TODO: check
        self.props |= (value & self.PROPS_BLOCK_SIZE_MASK) << self.PROPS_BLOCK_SIZE_SHIFT

    @property
    def segment_index(self):
        return (self.props >> self.PROPS_SEGMENT_INDEX_SHIFT) & self.PROPS_SEGMENT_INDEX_MASK

    @segment_index.setter
    def segment_index(self, value):
        self.props &= ~(self.PROPS_SEGMENT_INDEX_MASK << self.PROPS_SEGMENT_INDEX_SHIFT)
        self.props |= (value & self.PROPS_SEGMENT_INDEX_MASK) << self.PROPS_SEGMENT_INDEX_SHIFT

    def is_meta_segment(self):
        return (self.props & self.PROPS_META_SEGMENT_MASK) != 0

    def __repr__(self):
        return f'prs:0x{self.props:X} ofs:0x{self.offset:X} fsz:0x{self.filesz:X} msz:0x{self.memsz:X}'

class SignedElfExInfo(object):
    FMT = '<4Q32s'

    PTYPE_FAKE = 0x1
    PTYPE_NPDRM_EXEC = 0x4
    PTYPE_NPDRM_DYNLIB = 0x5
    PTYPE_SYSTEM_EXEC = 0x8
    PTYPE_SYSTEM_DYNLIB = 0x9
    PTYPE_HOST_KERNEL = 0xC
    PTYPE_SECURE_MODULE = 0xE
    PTYPE_SECURE_KERNEL = 0xF

    def __init__(self):
        self.paid = None
        self.ptype = None
        self.app_version = None
        self.fw_version = None
        self.digest = None

    def save(self, f):
        f.write(struct.pack(self.FMT, self.paid, self.ptype, self.app_version, self.fw_version, self.digest))

class SignedElfNpdrmControlBlock(object):
    FMT = '<H14x19s13s'

    def __init__(self):
        self.type = SELF_CONTROL_BLOCK_TYPE_NPDRM
        self.content_id = None
        self.random_pad = None

    def save(self, f):
        f.write(struct.pack(self.FMT, self.type, self.content_id, self.random_pad))

class SignedElfMetaBlock(object):
    FMT = '<80x'

    def __init__(self):
        pass

    def save(self, f):
        f.write(struct.pack(self.FMT))

class SignedElfMetaFooter(object):
    FMT = '<48xI28x'

    def __init__(self):
        self.unk1 = None

    def save(self, f):
        f.write(struct.pack(self.FMT, self.unk1))

class SignedElfFile(object):
    COMMON_HEADER_FMT = '<4s4B'
    EXT_HEADER_FMT = '<I2HQ2H4x'

    MAGIC = b'\x4F\x15\x3D\x1D'
    VERSION = 0x00
    MODE = 0x01
    ENDIAN = 0x01
    ATTRIBS = 0x12

    KEY_TYPE = 0x101

    FLAGS_SEGMENT_SIGNED_SHIFT = 4
    FLAGS_SEGMENT_SIGNED_MASK = 0x7

    HAS_NPDRM = 1

    def __init__(self, elf, **kwargs):
        self.elf = elf

        self.magic = None
        self.version = None
        self.mode = None
        self.endian = None
        self.attribs = None
        self.key_type = None
        self.header_size = None
        self.meta_size = None
        self.file_size = None
        self.num_entries = None
        self.flags = None

        self.entries = None
        self.ex_info = None
        self.npdrm_control_block = None
        self.meta_blocks = None
        self.meta_footer = None
        self.signature = None
        self.version_data = None

        self.paid = kwargs.get('paid', 0x3100000000000002)
        self.ptype = kwargs.get('ptype', SignedElfExInfo.PTYPE_FAKE)
        self.app_version = kwargs.get('app_version', 0)
        self.fw_version = kwargs.get('fw_version', 0)
        self.auth_info = kwargs.get('auth_info', None)

    def _prepare(self):
        if self.elf is None:
            raise ValueError("No ELF file provided for signing")

        self.magic = self.MAGIC
        self.version = self.VERSION
        self.mode = self.MODE
        self.endian = self.ENDIAN
        self.attribs = self.ATTRIBS
        self.key_type = self.KEY_TYPE
        self.flags = 0x2

        signed_block_count = 2
        self.flags |= (signed_block_count & self.FLAGS_SEGMENT_SIGNED_MASK) << self.FLAGS_SEGMENT_SIGNED_SHIFT

        self.entries = []
        entry_idx = 0
        for i in range(self.elf.ehdr.phnum):
            phdr = self.elf.phdrs[i]
            if phdr.type == ElfPHdr.PT_SCE_VERSION:
                self.version_data = self.elf.segments[i]
            if not phdr.type in [ElfPHdr.PT_LOAD, ElfPHdr.PT_SCE_RELRO, ElfPHdr.PT_SCE_DYNLIBDATA, ElfPHdr.PT_SCE_COMMENT]:
                continue
            meta_entry = SignedElfEntry(entry_idx)
            meta_entry.props = 0
            meta_entry.encrypted = False
            meta_entry.signed = True
            meta_entry.has_digests = True
            meta_entry.segment_index = entry_idx + 1
            self.entries.append(meta_entry)
            data_entry = SignedElfEntry(entry_idx + 1)
            data_entry.props = 0
            data_entry.encrypted = False
            data_entry.signed = True
            data_entry.has_blocks = True
            data_entry.block_size = BLOCK_SIZE
            data_entry.segment_index = i
            self.entries.append(data_entry)
            entry_idx += 2
        self.num_entries = len(self.entries)

        self.ex_info = SignedElfExInfo()
        self.ex_info.paid = self.paid
        self.ex_info.ptype = self.ptype
        self.ex_info.app_version = self.app_version
        self.ex_info.fw_version = self.fw_version
        self.ex_info.digest = self.elf.digest

        if self.HAS_NPDRM:
            self.npdrm_control_block = SignedElfNpdrmControlBlock()
            self.npdrm_control_block.content_id = b'\0' * SELF_NPDRM_CONTROL_BLOCK_CONTENT_ID_SIZE
            self.npdrm_control_block.random_pad = b'\0' * SELF_NPDRM_CONTROL_BLOCK_RANDOM_PAD_SIZE

        self.header_size = struct.calcsize(self.COMMON_HEADER_FMT) + struct.calcsize(self.EXT_HEADER_FMT)
        self.header_size += self.num_entries * struct.calcsize(SignedElfEntry.FMT)
        self.header_size += max(self.elf.ehdr.ehsize, self.elf.ehdr.phoff + self.elf.ehdr.phentsize * self.elf.ehdr.phnum)
        self.header_size = align_up(self.header_size, 16)
        self.header_size += struct.calcsize(SignedElfExInfo.FMT)
        if self.HAS_NPDRM:
            self.header_size += struct.calcsize(SignedElfNpdrmControlBlock.FMT)
        self.meta_size = self.num_entries * struct.calcsize(SignedElfMetaBlock.FMT) + struct.calcsize(SignedElfMetaFooter.FMT) + SIGNATURE_SIZE

        self.meta_blocks = []
        for i in range(self.num_entries):
            meta_block = SignedElfMetaBlock()
            self.meta_blocks.append(meta_block)

        self.meta_footer = SignedElfMetaFooter()
        self.meta_footer.unk1 = 0x10000

        if self.auth_info is not None:
            self.signature = (struct.pack('<QQ', len(self.auth_info), self.ex_info.paid) + self.auth_info[8:]).ljust(SIGNATURE_SIZE, b'\0')
        else:
            self.signature = EMPTY_SIGNATURE

        entry_idx = 0
        offset = self.header_size + self.meta_size
        for i in range(self.elf.ehdr.phnum):
            phdr = self.elf.phdrs[i]
            if not phdr.type in [ElfPHdr.PT_LOAD, ElfPHdr.PT_SCE_RELRO, ElfPHdr.PT_SCE_DYNLIBDATA, ElfPHdr.PT_SCE_COMMENT]:
                continue

            meta_entry, data_entry = self.entries[entry_idx], self.entries[entry_idx + 1]

            num_blocks = align_up(phdr.filesz, BLOCK_SIZE) // BLOCK_SIZE
            meta_entry.data = EMPTY_DIGEST * num_blocks
            meta_entry.offset = offset
            meta_entry.memsz = meta_entry.filesz = len(meta_entry.data)
            offset += meta_entry.filesz
            offset = align_up(offset, 16)

            data_entry.data = self.elf.segments[i]
            data_entry.offset = offset
            data_entry.memsz = data_entry.filesz = phdr.filesz
            offset += data_entry.filesz
            offset = align_up(offset, 16)

            entry_idx += 2

        self.file_size = offset

    def save(self, f):
        """Save as SELF file (for signing)."""
        if self.elf is None:
            raise ValueError("No ELF file to sign")
            
        start_offset = f.tell()

        # Calculate necessary fields
        self._prepare()

        # Write common header
        f.write(struct.pack(self.COMMON_HEADER_FMT, self.magic, self.version, self.mode, self.endian, self.attribs))

        # Write extended header
        f.write(struct.pack(self.EXT_HEADER_FMT, self.key_type, self.header_size, self.meta_size, self.file_size, self.num_entries, self.flags))

        # Write entries
        for entry in self.entries:
            entry.save(f)

        # Write elf headers
        elf_offset = f.tell()
        elf_header_size = max(self.elf.ehdr.ehsize, self.elf.ehdr.phoff + self.elf.ehdr.phentsize * self.elf.ehdr.phnum)
        elf_header_size = align_up(elf_header_size, 16)
        self.elf.save(f, True)
        f.seek(elf_offset + elf_header_size)

        # Write extended info
        self.ex_info.save(f)

        # Write npdrm control block
        if self.HAS_NPDRM:
            self.npdrm_control_block.save(f)

        # Write meta blocks
        for meta_block in self.meta_blocks:
            meta_block.save(f)

        # Write meta footer
        self.meta_footer.save(f)

        # Write signature
        f.write(self.signature)

        # Write segments
        for entry in self.entries:
            f.seek(start_offset + entry.offset)
            f.write(entry.data)

        if f.tell() < self.file_size:
            f.seek(self.file_size - 1)
            f.write(b"\x00")

        # Write version
        if self.version_data is not None:
            f.write(self.version_data)


class FakeSignedELFConverter:
    """
    A class to convert ELF files to fake signed SELF files.
    Files keep their original extensions and .bak files are skipped.
    """
    
    def __init__(self, 
                 paid: int = 0x3100000000000002,
                 ptype: int = SignedElfExInfo.PTYPE_FAKE,
                 app_version: int = 0,
                 fw_version: int = 0,
                 auth_info: Optional[bytes] = None):
        """
        Initialize the converter with parameters.
        
        Args:
            paid: Program authentication ID (default: 0x3100000000000002)
            ptype: Program type (default: PTYPE_FAKE)
            app_version: Application version (default: 0)
            fw_version: Firmware version (default: 0)
            auth_info: Authentication info bytes (default: None)
        """
        self.paid = paid
        self.ptype = ptype
        self.app_version = app_version
        self.fw_version = fw_version
        self.auth_info = auth_info
        
    @staticmethod
    def parse_ptype(ptype_str: str) -> int:
        """Parse program type string to integer."""
        ptype_map = {
            'fake': SignedElfExInfo.PTYPE_FAKE,
            'npdrm_exec': SignedElfExInfo.PTYPE_NPDRM_EXEC,
            'npdrm_dynlib': SignedElfExInfo.PTYPE_NPDRM_DYNLIB,
            'system_exec': SignedElfExInfo.PTYPE_SYSTEM_EXEC,
            'system_dynlib': SignedElfExInfo.PTYPE_SYSTEM_DYNLIB,
            'host_kernel': SignedElfExInfo.PTYPE_HOST_KERNEL,
            'secure_module': SignedElfExInfo.PTYPE_SECURE_MODULE,
            'secure_kernel': SignedElfExInfo.PTYPE_SECURE_KERNEL,
        }
        
        if ptype_str.lower() in ptype_map:
            return ptype_map[ptype_str.lower()]
        
        ptype_int = try_parse_int(ptype_str)
        if ptype_int is not None:
            return ptype_int
            
        raise ValueError(f"Invalid program type: {ptype_str}")
    
    def sign_file(self, input_path: str, output_path: str) -> bool:
        """
        Convert a single ELF file to fake signed SELF file.
        
        Args:
            input_path: Path to input ELF file
            output_path: Path to output SELF file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(input_path, 'rb') as f:
                elf_file = ElfFile(ignore_shdrs=True)
                elf_file.load(f)
                
            with open(output_path, 'wb') as f:
                self_file = SignedElfFile(
                    elf_file,
                    paid=self.paid,
                    ptype=self.ptype,
                    app_version=self.app_version,
                    fw_version=self.fw_version,
                    auth_info=self.auth_info,
                )
                self_file.save(f)
                
            return True
            
        except Exception as err:
            print(f'Error signing {input_path}: {err}')
            traceback.print_exc()
            return False
    
    def sign_directory(self, input_dir: str, output_dir: str) -> Dict[str, bool]:
        """
        Recursively sign all files in a directory.
        
        Args:
            input_dir: Input directory containing files
            output_dir: Output directory for SELF files
            
        Returns:
            Dict[str, bool]: Dictionary mapping input files to success status
        """
        results = {}
        
        for dirpath, dirnames, filenames in os.walk(input_dir):
            rel_dir = os.path.relpath(dirpath, input_dir)
            dest_dir = os.path.join(output_dir, rel_dir) if rel_dir != '.' else output_dir
            os.makedirs(dest_dir, exist_ok=True)
            
            for filename in filenames:
                if filename.endswith('.bak'):
                    continue
                    
                src_file = os.path.join(dirpath, filename)
                
                # Check if it's an ELF file by magic
                try:
                    with open(src_file, 'rb') as f:
                        magic = f.read(4)
                        if magic != ElfEHdr.MAGIC:
                            continue  # Skip non-ELF files
                except:
                    continue  # Skip files we can't read
                
                # Keep same filename and extension
                dst_file = os.path.join(dest_dir, filename)
                
                print(f'Signing: {src_file} -> {dst_file}')
                results[src_file] = self.sign_file(src_file, dst_file)
                
        return results


# Utility functions for standalone use (kept for backward compatibility)
def ensure_hex_string(val, **kwargs):
    exact_size = int(kwargs['exact_size']) if 'exact_size' in kwargs else None
    min_size = int(kwargs['min_size']) if 'min_size' in kwargs else None
    max_size = int(kwargs['max_size']) if 'max_size' in kwargs else None

    val = re.sub(r'\s+', '', val)
    val_size = len(val)
    if val_size > 0:
        if val.startswith('0x') or val.startswith('0X'):
            val = val[2:]
        if len(val) % 2 != 0 or not all(x in string.hexdigits for x in val):
            return None
        val = bytes.fromhex(val)
        val_size = len(val)

    if not exact_size is None and val_size != exact_size:
        return None
    else:
        if not min_size is None and val_size < min_size:
            return None
        if not max_size is None and val_size > max_size:
            return None

    return val


def auth_info_type(val):
    new_val = ensure_hex_string(val, exact_size=0x88)
    if new_val is None:
        raise argparse.ArgumentTypeError('invalid auth info: {0}'.format(val))
    return new_val


class MyParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_help()
        sys.stderr.write('\nerror: {0}\n'.format(message))
        sys.exit(2)


def main():
    """Command-line interface for standalone use."""
    parser = MyParser(description='Fake signed ELF maker')

    parser.add_argument('input',
                        type=str,
                        help='ELF file **or** a directory containing ELF files')
    parser.add_argument('output',
                        type=str,
                        help='output file **or** a directory. Files keep their original extensions.')
    parser.add_argument('--paid', type=int_with_base_type, default=0x3100000000000002,
                        help='program authentication id')
    parser.add_argument('--ptype', default=None,
                        help='program type {fake, npdrm_exec, npdrm_dynlib, system_exec, '
                             'system_dynlib, host_kernel, secure_module, secure_kernel}')
    parser.add_argument('--app-version', type=int_with_base_type, default=0,
                        help='application version')
    parser.add_argument('--fw-version', type=int_with_base_type, default=0,
                        help='firmware version')
    parser.add_argument('--auth-info', type=auth_info_type, default=None,
                        help='authentication info')

    if len(sys.argv) == 1:
        parser.print_usage()
        sys.exit(1)

    args = parser.parse_args()

    # Validate PAID
    paid = args.paid
    if not (0 <= paid <= 0xFFFFFFFFFFFFFFFF):
        parser.error(f'invalid program authentication id: 0x{paid:016X}')

    # Parse program type
    ptype = SignedElfExInfo.PTYPE_FAKE
    if args.ptype is not None:
        try:
            ptype = FakeSignedELFConverter.parse_ptype(args.ptype)
        except ValueError as e:
            parser.error(str(e))
    
    if not (0 <= ptype <= 0xFFFFFFFF):
        parser.error(f'invalid program type: 0x{ptype:016X}')

    # Validate versions
    if not (0 <= args.app_version <= 0xFFFFFFFFFFFFFFFF):
        parser.error(f'invalid application version: 0x{args.app_version:016X}')
    if not (0 <= args.fw_version <= 0xFFFFFFFFFFFFFFFF):
        parser.error(f'invalid firmware version: 0x{args.fw_version:016X}')

    # Create converter instance
    converter = FakeSignedELFConverter(
        paid=paid,
        ptype=ptype,
        app_version=args.app_version,
        fw_version=args.fw_version,
        auth_info=args.auth_info
    )

    # Process input
    in_path = args.input
    out_path = args.output

    if os.path.isdir(in_path):
        if not os.path.isdir(out_path):
            parser.error('When the input is a directory the output must also be a directory.')
        
        results = converter.sign_directory(in_path, out_path)
        successful = sum(1 for result in results.values() if result)
        total = len(results)
        print(f'\nSigning complete: {successful}/{total} files processed successfully')
        
    else:  # Single file
        # Skip .bak files even for single file mode
        if in_path.endswith('.bak'):
            print(f'Skipping backup file: {in_path}')
            sys.exit(0)
            
        if os.path.isdir(out_path):
            # Keep same filename
            dst_name = os.path.basename(in_path)
            out_file = os.path.join(out_path, dst_name)
        else:
            out_file = out_path

        os.makedirs(os.path.dirname(out_file) or '.', exist_ok=True)
        
        if converter.sign_file(in_path, out_file):
            print('Signing successful')
        else:
            print('Signing failed')
            sys.exit(1)


if __name__ == '__main__':
    main()