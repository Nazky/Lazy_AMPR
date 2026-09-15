#!/usr/bin/env python3

#############################################################################################
# PS5 SDK Version Patcher modified by @NazkyYT                                              #
# Original script by idlesauce                                                              #
# Link to the original: https://gist.github.com/idlesauce/2ded24b7b5ff296f21792a8202542aaa  #
#############################################################################################

import os
import struct
import shutil
import argparse
import sys
from typing import Dict, List, Optional, Tuple, Union
from pathlib import Path

# ANSI color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'

# Constants
PT_SCE_PROCPARAM = 0x61000001
PT_SCE_MODULE_PARAM = 0x61000002

SCE_PROCESS_PARAM_MAGIC = 0x4942524F
SCE_MODULE_PARAM_MAGIC = 0x3C13F4BF
SCE_PARAM_MAGIC_OFFSET = 0x8
SCE_PARAM_MAGIC_SIZE = 0x4
SCE_PARAM_PS4_SDK_OFFSET = 0x10
SCE_PARAM_PS5_SDK_OFFSET = 0x14
SCE_PARAM_PS_VERSION_SIZE = 0x4

PHT_OFFSET_OFFSET = 0x20
PHT_OFFSET_SIZE = 0x8
PHT_COUNT_OFFSET = 0x38
PHT_COUNT_SIZE = 0x2

PHDR_ENTRY_SIZE = 0x38
PHDR_TYPE_OFFSET = 0x0
PHDR_TYPE_SIZE = 0x4
PHDR_OFFSET_OFFSET = 0x8
PHDR_OFFSET_SIZE = 0x8
PHDR_FILESIZE_OFFSET = 0x20
PHDR_FILESIZE_SIZE = 0x8

ELF_MAGIC = b'\x7FELF'
PS4_FSELF_MAGIC = b'\x4F\x15\x3D\x1D'
PS5_FSELF_MAGIC = b'\x54\x14\xF5\xEE'

EXECUTABLE_EXTENSIONS = [".bin", ".elf", ".self", ".prx", ".sprx"]

# Known SDK version pairs (PS5 SDK version, PS4 version)
SDK_VERSION_PAIRS = {
    1:  (0x01000050, 0x07590001),
    2:  (0x02000009, 0x08050001),
    3:  (0x03000027, 0x08540001),
    4:  (0x04000031, 0x09040001),
    5:  (0x05000033, 0x09590001),
    6:  (0x06000038, 0x10090001),
    7:  (0x07000038, 0x10590001),
    8:  (0x08000041, 0x11090001),
    9:  (0x09000040, 0x11590001),
    10: (0x10000040, 0x12090001),
}
SDK_VERSION_PAIRS_MIN = 1
SDK_VERSION_PAIRS_MAX = 10

# Format map for reading/writing integers of different sizes
FORMAT_MAP = {1: '<B', 2: '<H', 4: '<I', 8: '<Q'}


class SDKVersionError(Exception):
    """Custom exception for SDK version patching errors."""
    pass


class SDKVersionPatcher:
    """
    A class to patch PS5 SDK versions in ELF files.
    
    This class can be used to modify the PS5 SDK version and PS4 version
    in PS5 ELF files' process and module parameter segments.
    """
    
    def __init__(self, 
                 ps5_sdk_version: Optional[int] = None,
                 ps4_version: Optional[int] = None,
                 create_backup: bool = True,
                 use_colors: bool = True):
        """
        Initialize the SDK version patcher.
        
        Args:
            ps5_sdk_version: PS5 SDK version to set (e.g., 0x04000031)
            ps4_version: PS4 version to set (e.g., 0x09040001)
            create_backup: Whether to create backup files (.bak)
            use_colors: Whether to use ANSI colors in output messages
        """
        self.ps5_sdk_version = ps5_sdk_version
        self.ps4_version = ps4_version
        self.create_backup = create_backup
        self.use_colors = use_colors
        
    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if colors are enabled."""
        if self.use_colors:
            return f"{color}{text}{RESET}"
        return text
    
    def _read_le_int(self, file, offset: int, size: int) -> int:
        """
        Read a little-endian integer from a file at the given offset.
        
        Args:
            file: File object (opened in binary mode)
            offset: Offset in the file to read from
            size: Size of the integer (1, 2, 4, or 8 bytes)
            
        Returns:
            The integer value read from the file
        """
        if size not in FORMAT_MAP:
            raise ValueError(f"Unsupported size: {size}. Must be 1, 2, 4, or 8 bytes.")
        
        file.seek(offset)
        data = file.read(size)
        if len(data) < size:
            raise SDKVersionError(f"Could not read {size} bytes at offset 0x{offset:X}")
        
        return struct.unpack(FORMAT_MAP[size], data)[0]
    
    def _write_le_int(self, file, offset: int, size: int, value: int):
        """
        Write a little-endian integer to a file at the given offset.
        
        Args:
            file: File object (opened in binary mode)
            offset: Offset in the file to write to
            size: Size of the integer (1, 2, 4, or 8 bytes)
            value: Integer value to write
        """
        if size not in FORMAT_MAP:
            raise ValueError(f"Unsupported size: {size}. Must be 1, 2, 4, or 8 bytes.")
        
        data = struct.pack(FORMAT_MAP[size], value)
        file.seek(offset)
        file.write(data)
    
    def _check_file_magic(self, file_path: str) -> str:
        """
        Check the file magic to determine file type.
        
        Args:
            file_path: Path to the file
            
        Returns:
            String indicating file type: "elf", "ps4_self", "ps5_self", or "unknown"
        """
        with open(file_path, 'rb') as f:
            magic = f.read(4)
            
        if magic == ELF_MAGIC:
            return "elf"
        elif magic == PS4_FSELF_MAGIC:
            return "ps4_self"
        elif magic == PS5_FSELF_MAGIC:
            return "ps5_self"
        else:
            return "unknown"
    
    def _patch_file_internal(self, file_path: str) -> Tuple[bool, str]:
        """
        Internal method to patch a single file.
        
        Args:
            file_path: Path to the ELF file
            
        Returns:
            Tuple of (success, message)
        """
        try:
            with open(file_path, 'r+b') as file:
                # Check if it's an ELF file
                file.seek(0)
                magic = file.read(4)
                
                if magic != ELF_MAGIC:
                    if magic in (PS4_FSELF_MAGIC, PS5_FSELF_MAGIC):
                        msg = f"Skipping signed file '{file_path}' (expected unsigned ELF)"
                        return False, self._colorize(f"[!] {msg}", RED)
                    return False, f"Not an ELF file: '{file_path}'"
                
                # Create backup if requested
                backup_path = file_path + ".bak"
                if self.create_backup and not os.path.exists(backup_path):
                    shutil.copyfile(file_path, backup_path)
                
                # Read segment count and program header table offset
                segment_count = self._read_le_int(file, PHT_COUNT_OFFSET, PHT_COUNT_SIZE)
                pht_offset = self._read_le_int(file, PHT_OFFSET_OFFSET, PHT_OFFSET_SIZE)
                
                patched = False
                
                for i in range(segment_count):
                    segment_type = self._read_le_int(
                        file, 
                        pht_offset + i * PHDR_ENTRY_SIZE + PHDR_TYPE_OFFSET, 
                        PHDR_TYPE_SIZE
                    )
                    
                    if segment_type not in (PT_SCE_PROCPARAM, PT_SCE_MODULE_PARAM):
                        continue
                    
                    segment_offset = self._read_le_int(
                        file,
                        pht_offset + i * PHDR_ENTRY_SIZE + PHDR_OFFSET_OFFSET,
                        PHDR_OFFSET_SIZE
                    )
                    
                    param_struct_size = self._read_le_int(file, segment_offset, 4)
                    
                    # Check for empty module param
                    if param_struct_size == 0 and segment_type == PT_SCE_MODULE_PARAM:
                        msg = f"Module file has no param, skipping '{file_path}'"
                        return True, self._colorize(f"[?] {msg}", YELLOW)
                    
                    # Validate param struct size
                    if param_struct_size < SCE_PARAM_PS5_SDK_OFFSET + SCE_PARAM_PS_VERSION_SIZE:
                        msg = f"Unexpected param struct size 0x{param_struct_size:X} for file '{file_path}'"
                        return False, self._colorize(f"[!] {msg}", RED)
                    
                    # Check magic
                    magic = self._read_le_int(
                        file, 
                        segment_offset + SCE_PARAM_MAGIC_OFFSET, 
                        SCE_PARAM_MAGIC_SIZE
                    )
                    
                    expected_magic = (SCE_PROCESS_PARAM_MAGIC if segment_type == PT_SCE_PROCPARAM 
                                     else SCE_MODULE_PARAM_MAGIC)
                    
                    if magic != expected_magic:
                        msg = f"Invalid param magic 0x{magic:08X} for file '{file_path}'"
                        return False, self._colorize(f"[!] {msg}", RED)
                    
                    # Read original versions
                    og_ps5_sdk_version = self._read_le_int(
                        file, 
                        segment_offset + SCE_PARAM_PS5_SDK_OFFSET, 
                        4
                    )
                    og_ps4_sdk_version = self._read_le_int(
                        file, 
                        segment_offset + SCE_PARAM_PS4_SDK_OFFSET, 
                        4
                    )
                    
                    # Write new versions
                    self._write_le_int(
                        file, 
                        segment_offset + SCE_PARAM_PS5_SDK_OFFSET, 
                        SCE_PARAM_PS_VERSION_SIZE, 
                        self.ps5_sdk_version
                    )
                    self._write_le_int(
                        file, 
                        segment_offset + SCE_PARAM_PS4_SDK_OFFSET, 
                        SCE_PARAM_PS_VERSION_SIZE, 
                        self.ps4_version
                    )
                    
                    msg = (f"Patched file '{file_path}': "
                          f"PS5 SDK version 0x{og_ps5_sdk_version:08X} -> 0x{self.ps5_sdk_version:08X}, "
                          f"PS4 version 0x{og_ps4_sdk_version:08X} -> 0x{self.ps4_version:08X}")
                    patched = True
                    print(self._colorize(f"[+] {msg}", GREEN))
                
                if not patched:
                    msg = f"No process or module param segment found in '{file_path}'"
                    return False, self._colorize(f"[!] {msg}", YELLOW)
                
                return True, f"Successfully patched '{file_path}'"
                
        except Exception as e:
            return False, f"Error patching '{file_path}': {str(e)}"
    
    def patch_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Patch a single ELF file.
        
        Args:
            file_path: Path to the ELF file
            
        Returns:
            Tuple of (success, message)
            
        Raises:
            ValueError: If SDK versions are not set
        """
        if self.ps5_sdk_version is None or self.ps4_version is None:
            raise ValueError("PS5 SDK version and PS4 version must be set before patching")
        
        if not os.path.exists(file_path):
            return False, f"File not found: '{file_path}'"
        
        return self._patch_file_internal(file_path)
    
    def patch_directory(self, directory_path: str) -> Dict[str, Tuple[bool, str]]:
        """
        Recursively patch all ELF files in a directory.
        
        Args:
            directory_path: Path to the directory containing ELF files
            
        Returns:
            Dictionary mapping file paths to (success, message) tuples
            
        Raises:
            ValueError: If SDK versions are not set
        """
        if self.ps5_sdk_version is None or self.ps4_version is None:
            raise ValueError("PS5 SDK version and PS4 version must be set before patching")
        
        if not os.path.exists(directory_path):
            raise FileNotFoundError(f"Directory not found: '{directory_path}'")
        
        results = {}
        
        # Walk through directory recursively
        for root, dirs, files in os.walk(directory_path):
            for filename in files:
                if any(filename.endswith(ext) for ext in EXECUTABLE_EXTENSIONS):
                    file_path = os.path.join(root, filename)
                    success, message = self.patch_file(file_path)
                    results[file_path] = (success, message)
        
        return results
    
    def set_versions_by_pair(self, pair_number: int):
        """
        Set versions using a known SDK version pair.
        
        Args:
            pair_number: SDK version pair number (1-10)
            
        Raises:
            ValueError: If pair_number is not in range
        """
        if pair_number not in SDK_VERSION_PAIRS:
            raise ValueError(f"Pair number must be between {SDK_VERSION_PAIRS_MIN} and {SDK_VERSION_PAIRS_MAX}")
        
        self.ps5_sdk_version, self.ps4_version = SDK_VERSION_PAIRS[pair_number]
    
    def set_custom_versions(self, ps5_sdk_version: int, ps4_version: int):
        """
        Set custom SDK versions.
        
        Args:
            ps5_sdk_version: PS5 SDK version (32-bit)
            ps4_version: PS4 version (32-bit)
            
        Raises:
            ValueError: If versions are not 32-bit values
        """
        if ps5_sdk_version > 0xFFFFFFFF:
            raise ValueError("PS5 SDK version must be a 32-bit value")
        if ps4_version > 0xFFFFFFFF:
            raise ValueError("PS4 version must be a 32-bit value")
        
        self.ps5_sdk_version = ps5_sdk_version
        self.ps4_version = ps4_version
    
    def get_current_versions(self) -> Tuple[Optional[int], Optional[int]]:
        """Get the currently set SDK versions."""
        return self.ps5_sdk_version, self.ps4_version
    
    @staticmethod
    def get_supported_pairs() -> Dict[int, Tuple[int, int]]:
        """Get the dictionary of supported SDK version pairs."""
        return SDK_VERSION_PAIRS.copy()
    
    @staticmethod
    def get_sdk_version_range() -> Tuple[int, int]:
        """Get the range of supported SDK version pairs."""
        return SDK_VERSION_PAIRS_MIN, SDK_VERSION_PAIRS_MAX


def main():
    """Command-line interface for standalone use."""
    parser = argparse.ArgumentParser(description="Patches the SDK version PS5 ELF files")
    parser.add_argument("input", help="Path to an ELF file or a folder which will be processed recursively")
    parser.add_argument("--ps5_ver", help="(optional) Custom PS5 SDK version to set (e.g. 0x04000031)", 
                       type=lambda x: int(x, 0))
    parser.add_argument("--ps4_ver", help="(optional) Custom PS4 version to set (e.g. 0x09040001)", 
                       type=lambda x: int(x, 0))
    parser.add_argument("--no-backup", action="store_true", 
                       help="(optional) Do not create backup .bak files")
    parser.add_argument("--no-colors", action="store_true",
                       help="(optional) Disable colored output")
    
    args = parser.parse_args()
    
    # Create patcher instance
    patcher = SDKVersionPatcher(
        ps5_sdk_version=args.ps5_ver,
        ps4_version=args.ps4_ver,
        create_backup=not args.no_backup,
        use_colors=not args.no_colors
    )
    
    # If versions not provided, prompt for SDK version pair
    if patcher.ps5_sdk_version is None or patcher.ps4_version is None:
        print(f"Enter target PS5 SDK version ({SDK_VERSION_PAIRS_MIN}-{SDK_VERSION_PAIRS_MAX}):")
        try:
            ver_input = int(input().strip())
            if ver_input not in SDK_VERSION_PAIRS:
                print(f"{RED}[!] Invalid or unsupported version{RESET}")
                sys.exit(1)
            patcher.set_versions_by_pair(ver_input)
        except ValueError:
            print(f"{RED}[!] Invalid input{RESET}")
            sys.exit(1)
    
    print(f"Selected PS5 SDK version 0x{patcher.ps5_sdk_version:08X} "
          f"and PS4 version 0x{patcher.ps4_version:08X}")
    
    input_path = args.input
    
    if not os.path.exists(input_path):
        print(f"{RED}[!] Invalid input '{input_path}'{RESET}")
        sys.exit(1)
    
    if os.path.isfile(input_path):
        success, message = patcher.patch_file(input_path)
        if not success:
            print(message)
            sys.exit(1)
    elif os.path.isdir(input_path):
        results = patcher.patch_directory(input_path)
        
        # Print summary
        successful = sum(1 for success, _ in results.values() if success)
        total = len(results)
        
        print("\n" + "="*50)
        print(f"Summary: {successful}/{total} files patched successfully")
        
        if successful < total:
            print("\nFailed files:")
            for file_path, (success, message) in results.items():
                if not success:
                    print(f"  {file_path}: {message}")
            sys.exit(1)
    else:
        print(f"{RED}[!] Invalid input '{input_path}'{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()