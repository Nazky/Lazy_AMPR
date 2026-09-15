#!/usr/bin/env python3

##############################################################################################################
# Convert Fake Signed ELF to Unsigned ELF                                                                   #
# Based on the original make_fself.py by john-tornblom / @NazkyYT                                           #
# Added support for PS4 (0x1D3D154F) and PS5 (0xEEF51454) SELF magic                                       #
##############################################################################################################

import sys, os, struct, traceback
import hashlib
import argparse
from typing import Dict, Optional, List, BinaryIO

def align_up(x, alignment):
    return (x + (alignment - 1)) & ~(alignment - 1)

def align_down(x, alignment):
    return x & ~(alignment - 1)

class SelfError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return repr(self.msg)

# ELF Header structure
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
        old_pos = f.tell()
        self.magic, self.machine_class, self.data_encoding, self.version, self.os_abi, self.abi_version, self.nident_size = struct.unpack(ElfEHdr.FMT, f.read(struct.calcsize(ElfEHdr.FMT)))
        f.seek(old_pos + struct.calcsize(ElfEHdr.FMT))
        self.type, self.machine, self.version, self.entry, self.phoff, self.shoff, self.flags, self.ehsize, self.phentsize, self.phnum, self.shentsize, self.shnum, self.shstridx = struct.unpack(ElfEHdr.EX_FMT, f.read(struct.calcsize(ElfEHdr.EX_FMT)))

    def save(self, f):
        f.write(struct.pack(ElfEHdr.FMT, self.magic, self.machine_class, self.data_encoding, self.version, self.os_abi, self.abi_version, self.nident_size))
        f.write(struct.pack(ElfEHdr.EX_FMT, self.type, self.machine, self.version, self.entry, self.phoff, self.shoff, self.flags, self.ehsize, self.phentsize, self.phnum, self.shentsize, self.shnum, self.shstridx))

# ELF Program Header structure
class ElfPHdr(object):
    FMT = '<2I6Q'

    PT_LOAD = 0x1
    PT_DYNAMIC = 0x2
    PT_INTERP = 0x3
    PT_TLS = 0x7
    PT_GNU_EH_FRAME = 0x6474E550
    PT_GNU_STACK = 0x6474E551
    PT_SCE_RELA = 0x60000000
    PT_SCE_DYNLIBDATA = 0x61000000
    PT_SCE_PROCPARAM = 0x61000001
    PT_SCE_MODULE_PARAM = 0x61000002
    PT_SCE_RELRO = 0x61000010
    PT_SCE_COMMENT = 0x6FFFFF00
    PT_SCE_VERSION = 0x6FFFFF01

    def __init__(self):
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

# SELF Entry structure with bitfield support
class SelfEntry(object):
    FMT = '<Q3Q'  # props (64-bit) + offset + enc_size + dec_size
    
    def __init__(self):
        self.props = None
        self.offset = None
        self.enc_size = None  # filesz in SELF
        self.dec_size = None  # memsz in SELF
        
    def load(self, f):
        self.props, self.offset, self.enc_size, self.dec_size = struct.unpack(self.FMT, f.read(struct.calcsize(self.FMT)))
    
    @property
    def segment_index(self):
        """Extract segment_index from props (bits 20-35)"""
        return (self.props >> 20) & 0xFFFF
    
    @property
    def has_meta_segment(self):
        """Check if this is a meta/digest segment (bit 20)"""
        return ((self.props >> 20) & 0x1) != 0
    
    @property
    def has_blocks(self):
        """Check if this entry has blocks (bit 11)"""
        return ((self.props >> 11) & 0x1) != 0
    
    @property
    def has_digest(self):
        """Check if this entry has digest (bit 16)"""
        return ((self.props >> 16) & 0x1) != 0
    
    @property
    def is_signed(self):
        """Check if this entry is signed (bit 2)"""
        return ((self.props >> 2) & 0x1) != 0
    
    @property
    def filesz(self):
        """Alias for enc_size"""
        return self.enc_size
    
    @property
    def memsz(self):
        """Alias for dec_size"""
        return self.dec_size

# SELF Extended Info structure
class SelfExInfo(object):
    FMT = '<4Q32s'

    def __init__(self):
        self.authid = None
        self.ptype = None
        self.app_version = None
        self.fw_version = None
        self.digest = None

    def load(self, f):
        self.authid, self.ptype, self.app_version, self.fw_version, self.digest = struct.unpack(self.FMT, f.read(struct.calcsize(self.FMT)))

# SELF NpDrm Control Block
class SelfNpDrmBlock(object):
    FMT = '<H14s19s13s'
    
    def __init__(self):
        self.type = None
        self.unknown = None
        self.content_id = None
        self.random_pad = None
    
    def load(self, f):
        self.type, self.unknown, self.content_id, self.random_pad = struct.unpack(self.FMT, f.read(struct.calcsize(self.FMT)))

# SELF Meta Block
class SelfMetaBlock(object):
    FMT = '<80s'
    
    def __init__(self):
        self.unknown = None
    
    def load(self, f):
        self.unknown = struct.unpack(self.FMT, f.read(struct.calcsize(self.FMT)))[0]

# SELF Meta Footer
class SelfMetaFooter(object):
    FMT = '<48sI28s100x'
    
    def __init__(self):
        self.unknown0 = None
        self.unknown1 = None
        self.unknown2 = None
    
    def load(self, f):
        self.unknown0, self.unknown1, self.unknown2 = struct.unpack(self.FMT, f.read(struct.calcsize(self.FMT)))

class SelfFile(object):
    """Class to parse and extract unsigned ELF from SELF file."""
    
    COMMON_HEADER_FMT = '<IBBBB'
    EXT_HEADER_FMT = '<IHHQHH4x'
    
    # Magic values from C code
    SELF_PS4_MAGIC = 0x1D3D154F  # b'\x4F\x15\x3D\x1D' (little-endian)
    SELF_PS5_MAGIC = 0xEEF51454  # b'\x54\x14\xF5\xEE' (little-endian)
    
    # Byte representations for magic checking
    SELF_PS4_MAGIC_BYTES = b'\x4F\x15\x3D\x1D'
    SELF_PS5_MAGIC_BYTES = b'\x54\x14\xF5\xEE'
    
    def __init__(self):
        self.magic = None
        self.version = None
        self.mode = None
        self.endian = None
        self.attrs = None
        self.key_type = None
        self.header_size = None
        self.meta_size = None
        self.file_size = None
        self.num_entries = None
        self.flags = None
        
        self.entries = []
        self.ex_info = None
        self.npdrm_block = None
        self.elf_header = None
        self.program_headers = []
        
        # Store which magic we detected
        self.is_ps4_format = False
        self.is_ps5_format = False
        
    def load(self, f: BinaryIO) -> bool:
        """Load and parse SELF file."""
        start_pos = f.tell()
        
        # Check magic
        magic_bytes = f.read(4)
        f.seek(start_pos)
        
        if magic_bytes == self.SELF_PS4_MAGIC_BYTES:
            self.is_ps4_format = True
            self.is_ps5_format = False
        elif magic_bytes == self.SELF_PS5_MAGIC_BYTES:
            self.is_ps4_format = False
            self.is_ps5_format = True
        else:
            raise SelfError(f"Not a valid SELF file (invalid magic: 0x{magic_bytes.hex()})")
        
        # Read common header
        self.magic, self.version, self.mode, self.endian, self.attrs = struct.unpack(
            self.COMMON_HEADER_FMT, f.read(struct.calcsize(self.COMMON_HEADER_FMT))
        )
        
        # Read extended header
        self.key_type, self.header_size, self.meta_size, self.file_size, self.num_entries, self.flags = struct.unpack(
            self.EXT_HEADER_FMT, f.read(struct.calcsize(self.EXT_HEADER_FMT))
        )
        
        if self.verbose:
            print(f"  Detected: {'PS4' if self.is_ps4_format else 'PS5'} SELF format")
            print(f"  Header size: 0x{self.header_size:X}")
            print(f"  Meta size: 0x{self.meta_size:X}")
            print(f"  File size: 0x{self.file_size:X}")
            print(f"  Number of entries: {self.num_entries}")
        
        # Read entries
        self.entries = []
        for i in range(self.num_entries):
            entry = SelfEntry()
            entry.load(f)
            self.entries.append(entry)
            
            if self.verbose:
                print(f"  Entry {i}: seg_idx={entry.segment_index}, "
                      f"has_blocks={entry.has_blocks}, has_digest={entry.has_digest}, "
                      f"offset=0x{entry.offset:X}, size=0x{entry.filesz:X}")
        
        # Current position after reading entries
        current_pos = f.tell()
        
        # The ELF header should start here (aligned to 16 bytes)
        elf_header_offset = current_pos
        elf_header_offset = align_up(elf_header_offset, 16)
        f.seek(start_pos + elf_header_offset)
        
        # Read ELF header
        self.elf_header = ElfEHdr()
        self.elf_header.load(f)
        
        # Read program headers
        f.seek(start_pos + elf_header_offset + self.elf_header.phoff)
        self.program_headers = []
        for i in range(self.elf_header.phnum):
            phdr = ElfPHdr()
            phdr.load(f)
            self.program_headers.append(phdr)
        
        # Calculate position of extended info
        # It's located after the ELF headers, aligned to 16 bytes
        elf_headers_end = elf_header_offset + self.elf_header.ehsize + (self.elf_header.phnum * self.elf_header.phentsize)
        elf_headers_end = align_up(elf_headers_end, 16)
        
        f.seek(start_pos + elf_headers_end)
        self.ex_info = SelfExInfo()
        self.ex_info.load(f)
        
        # Read NpDrm block if present
        f.seek(start_pos + elf_headers_end + struct.calcsize(SelfExInfo.FMT))
        self.npdrm_block = SelfNpDrmBlock()
        self.npdrm_block.load(f)
        
        if self.verbose:
            print(f"  Auth ID: 0x{self.ex_info.authid:016X}")
            print(f"  Type: 0x{self.ex_info.ptype:X}")
            print(f"  ELF segments: {self.elf_header.phnum}")
        
        return True
    
    def extract_elf(self, f: BinaryIO, output_f: BinaryIO) -> bool:
        """Extract unsigned ELF from SELF file."""
        start_pos = f.tell()
        
        # First, write ELF header
        f.seek(start_pos)
        self.load(f)  # Ensure we've parsed the file
        
        # Go to ELF header position
        current_pos = struct.calcsize(self.COMMON_HEADER_FMT) + struct.calcsize(self.EXT_HEADER_FMT)
        current_pos += self.num_entries * struct.calcsize(SelfEntry.FMT)
        current_pos = align_up(current_pos, 16)
        
        f.seek(start_pos + current_pos)
        elf_header_data = f.read(self.elf_header.ehsize)
        output_f.write(elf_header_data)
        
        # Write program headers
        if self.elf_header.phnum > 0:
            f.seek(start_pos + current_pos + self.elf_header.phoff)
            for i in range(self.elf_header.phnum):
                phdr_data = f.read(self.elf_header.phentsize)
                output_f.write(phdr_data)
        
        # Now write segment data
        # We need to map SELF entries to ELF segments
        # In PS4/PS5 SELF format, each segment has two entries:
        # 1. A digest/metadata entry (has_digest=True, has_blocks=False)
        # 2. A data entry (has_blocks=True, has_digest=False)
        
        data_entries = []
        
        # Find data entries (those with has_blocks=True)
        for entry in self.entries:
            if entry.has_blocks:
                data_entries.append(entry)
        
        # Sort by segment index to maintain order
        data_entries.sort(key=lambda x: x.segment_index)
        
        if self.verbose:
            print(f"  Found {len(data_entries)} data entries")
        
        # Write segment data
        for data_entry in data_entries:
            segment_idx = data_entry.segment_index
            
            if segment_idx >= len(self.program_headers):
                if self.verbose:
                    print(f"  Warning: Segment index {segment_idx} out of range (max {len(self.program_headers)-1})")
                continue
                
            phdr = self.program_headers[segment_idx]
            
            if self.verbose:
                print(f"  Extracting segment {segment_idx}: "
                      f"type=0x{phdr.type:X}, offset=0x{phdr.offset:X}, "
                      f"filesz=0x{phdr.filesz:X}")
            
            # Seek to the segment data in SELF file
            f.seek(start_pos + data_entry.offset)
            
            # Read and write the segment data
            segment_data = f.read(data_entry.filesz)
            
            # Ensure we're at the correct position in output file
            current_output_pos = output_f.tell()
            if current_output_pos < phdr.offset:
                # Pad with zeros if needed
                padding_size = phdr.offset - current_output_pos
                if self.verbose and padding_size > 0:
                    print(f"    Padding with {padding_size} bytes")
                output_f.write(b'\x00' * padding_size)
            elif current_output_pos > phdr.offset:
                # This shouldn't happen, but just in case
                print(f"Warning: Overlap detected at segment {segment_idx}")
                output_f.seek(phdr.offset)
            
            output_f.write(segment_data)
            
            # Pad to filesz if necessary
            current_output_pos = output_f.tell()
            if current_output_pos < phdr.offset + phdr.filesz:
                padding_size = phdr.offset + phdr.filesz - current_output_pos
                if self.verbose and padding_size > 0:
                    print(f"    Padding end with {padding_size} bytes")
                output_f.write(b'\x00' * padding_size)
        
        # Check for PT_SCE_VERSION segment (special handling)
        version_segment_found = False
        for i, phdr in enumerate(self.program_headers):
            if phdr.type == ElfPHdr.PT_SCE_VERSION and phdr.filesz > 0:
                if self.verbose:
                    print(f"  Found PT_SCE_VERSION segment at index {i}")
                
                # Find corresponding data entry
                for entry in data_entries:
                    if entry.segment_index == i:
                        # Already extracted above
                        version_segment_found = True
                        break
                
                if not version_segment_found:
                    # Try to find it in the file
                    # In the C code, PT_SCE_VERSION is appended at the end
                    f.seek(0, 2)  # Seek to end
                    file_end = f.tell()
                    f.seek(file_end - phdr.filesz)
                    version_data = f.read(phdr.filesz)
                    
                    current_output_pos = output_f.tell()
                    if current_output_pos < phdr.offset:
                        output_f.write(b'\x00' * (phdr.offset - current_output_pos))
                    output_f.write(version_data)
                    
                    if self.verbose:
                        print(f"    Appended PT_SCE_VERSION from end of file")
        
        return True

class UnsignedELFConverter:
    """
    A class to convert fake signed SELF files back to unsigned ELF files.
    Files keep their original extensions and .bak files are skipped.
    """
    
    def __init__(self, verbose: bool = False):
        """
        Initialize the converter.
        
        Args:
            verbose: Enable verbose output
        """
        self.verbose = verbose
    
    def convert_file(self, input_path: str, output_path: str) -> bool:
        """
        Convert a single SELF file to unsigned ELF file.
        
        Args:
            input_path: Path to input SELF file
            output_path: Path to output ELF file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.verbose:
                print(f"Processing: {input_path}")
            
            with open(input_path, 'rb') as f:
                # Check if it's a SELF file
                magic = f.read(4)
                f.seek(0)
                
                is_self_file = (magic == SelfFile.SELF_PS4_MAGIC_BYTES or 
                               magic == SelfFile.SELF_PS5_MAGIC_BYTES)
                
                if not is_self_file:
                    print(f"Warning: {input_path} is not a SELF file (wrong magic: 0x{magic.hex()}), skipping")
                    return False
                
                self_file = SelfFile()
                self_file.verbose = self.verbose
                self_file.load(f)
                
                # Extract ELF
                with open(output_path, 'wb') as out_f:
                    f.seek(0)  # Reset to beginning
                    success = self_file.extract_elf(f, out_f)
                    
                    if success and self.verbose:
                        print(f"  Successfully extracted to: {output_path}")
                        print(f"  Format: {'PS4' if self_file.is_ps4_format else 'PS5'}")
                        print(f"  PAID/Auth ID: 0x{self_file.ex_info.authid:016X}")
                        print(f"  Type: 0x{self_file.ex_info.ptype:X}")
                    
                    return success
                    
        except Exception as err:
            print(f'Error converting {input_path}: {err}')
            if self.verbose:
                traceback.print_exc()
            return False
    
    def convert_directory(self, input_dir: str, output_dir: str) -> Dict[str, bool]:
        """
        Recursively convert all SELF files in a directory.
        
        Args:
            input_dir: Input directory containing SELF files
            output_dir: Output directory for ELF files
            
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
                
                # Check if it's a SELF file by magic
                try:
                    with open(src_file, 'rb') as f:
                        magic = f.read(4)
                        is_self_file = (magic == SelfFile.SELF_PS4_MAGIC_BYTES or 
                                       magic == SelfFile.SELF_PS5_MAGIC_BYTES)
                        if not is_self_file:
                            continue  # Skip non-SELF files
                except:
                    continue  # Skip files we can't read
                
                # Keep same filename and extension
                dst_file = os.path.join(dest_dir, filename)
                
                if self.verbose:
                    print(f'Converting: {src_file} -> {dst_file}')
                results[src_file] = self.convert_file(src_file, dst_file)
                
        return results

def detect_self_magic(file_path: str) -> Optional[str]:
    """Detect the SELF magic in a file."""
    try:
        with open(file_path, 'rb') as f:
            magic = f.read(4)
            
            if magic == SelfFile.SELF_PS4_MAGIC_BYTES:
                return "PS4 (0x1D3D154F)"
            elif magic == SelfFile.SELF_PS5_MAGIC_BYTES:
                return "PS5 (0xEEF51454)"
            else:
                return None
    except:
        return None

def main():
    """Command-line interface for standalone use."""
    parser = argparse.ArgumentParser(
        description='Convert fake signed SELF files back to unsigned ELF files\n'
                   'Supports both PS4 (0x1D3D154F) and PS5 (0xEEF51454) SELF formats',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.self output.elf
  %(prog)s input_dir output_dir
  %(prog)s signed.self unsigned.elf --verbose
  %(prog)s --detect file.self
  
Supported SELF magics:
  PS4: 0x1D3D154F (\\x4F\\x15\\x3D\\x1D)
  PS5: 0xEEF51454 (\\x54\\x14\\xF5\\xEE)
        """
    )
    
    parser.add_argument('input',
                       nargs='?',
                       type=str,
                       help='SELF file **or** a directory containing SELF files')
    parser.add_argument('output',
                       nargs='?',
                       type=str,
                       help='output ELF file **or** a directory. Files keep their original extensions.')
    parser.add_argument('--verbose', '-v',
                       action='store_true',
                       help='enable verbose output')
    parser.add_argument('--detect',
                       action='store_true',
                       help='detect SELF magic in file(s) without converting')
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
    
    args = parser.parse_args()
    
    # Detection mode
    if args.detect:
        if not args.input:
            print("Error: --detect requires an input file or directory")
            sys.exit(1)
        
        if os.path.isdir(args.input):
            print(f"Detecting SELF magic in directory: {args.input}")
            for dirpath, dirnames, filenames in os.walk(args.input):
                for filename in filenames:
                    if filename.endswith('.bak'):
                        continue
                    
                    file_path = os.path.join(dirpath, filename)
                    magic_type = detect_self_magic(file_path)
                    if magic_type:
                        rel_path = os.path.relpath(file_path, args.input)
                        print(f"  {rel_path}: {magic_type}")
        else:
            magic_type = detect_self_magic(args.input)
            if magic_type:
                print(f"{args.input}: {magic_type}")
            else:
                print(f"{args.input}: Not a SELF file")
        sys.exit(0)
    
    # Normal conversion mode
    if not args.input or not args.output:
        print("Error: Both input and output arguments are required for conversion")
        parser.print_help()
        sys.exit(1)
    
    # Create converter instance
    converter = UnsignedELFConverter(verbose=args.verbose)
    
    # Process input
    in_path = args.input
    out_path = args.output
    
    if not os.path.exists(in_path):
        print(f"Error: Input path '{in_path}' does not exist")
        sys.exit(1)
    
    if os.path.isdir(in_path):
        if not os.path.exists(out_path):
            os.makedirs(out_path, exist_ok=True)
        elif not os.path.isdir(out_path):
            print("Error: When the input is a directory, the output must also be a directory.")
            sys.exit(1)
        
        results = converter.convert_directory(in_path, out_path)
        successful = sum(1 for result in results.values() if result)
        total = len(results)
        
        if args.verbose or total > 0:
            print(f'\nConversion complete: {successful}/{total} files processed successfully')
        
    else:  # Single file
        if os.path.isdir(out_path):
            # Keep same filename
            dst_name = os.path.basename(in_path)
            out_file = os.path.join(out_path, dst_name)
        else:
            out_file = out_path
        
        os.makedirs(os.path.dirname(out_file) or '.', exist_ok=True)
        
        if converter.convert_file(in_path, out_file):
            if not args.verbose:
                print('Conversion successful')
        else:
            print('Conversion failed')
            sys.exit(1)

if __name__ == '__main__':
    main()