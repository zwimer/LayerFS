#!/usr/bin/env python3.8

import argparse
import platform
import dbm
import shutil
import errno
import sys
import os

from pathlib import Path
from collections import namedtuple
from fuse import FUSE, FuseOSError, Operations


# TODO: Long term things:
#       1. thread safe
#       2. optimize by only storing top level in shadow
#       3. Allow links


# A decorator used for debugging
def debug_member(f):
    def real(*args, **kwargs):
        global ll; ll += 1
        print('  '*ll + 'Invoked ' + f.__name__ + ':', args[1:], kwargs)
        try: ret = f(*args,  **kwargs)
        except Exception as e: pnt('Exception: ' + str(e)); raise
        finally: ll -= 1
        print('  '*ll+'Returned: ' + ('\n' if ll==0 else ''), ret)
        return ret
    return real
ll = 0


# The class that handles all FS / File operations
class LayerFS(Operations):
    def __init__(self, root, layer_storage):
        # Cleanup
        layer_storage = os.path.normpath(layer_storage)
        root = os.path.normpath(root)
        # Make directories
        Path(layer_storage).mkdir(parents=False, exist_ok=True)
        self.fake_root = self.join(layer_storage, 'fake_root')
        Path(self.fake_root).mkdir(parents=True, exist_ok=True)
        # Setup LayerFS
        self.fd_map_t = namedtuple('fd_map_t', ['fd', 'path', 'open_args'])
        self.shadow_file = self.join(layer_storage, 'shadow')
        self.load_shadow()
        self.fd_map = {}
        self.root = root

    ######################################################################
    #                                                                    #
    #                          Helper Functions                          #
    #                                                                    #
    ######################################################################

    ########################################
    #      Path Construction Functions     #
    ########################################

    # Load shadow from a file
    def load_shadow(self):
        if not os.path.exists(self.shadow_file):
            self.shadow = set()
        else:
            with open(self.shadow_file) as f:
                data = f.read()
            self.shadow = set([ i for i in data.split('\n') if len(i) > 0 ])

    # Never end in slash
    @staticmethod
    def join(a_root, tail):
        while tail.startswith('/'):
            tail = tail[1:]
        ret = os.path.join(a_root, tail)
        while ret.endswith('/'):
            ret = ret[:-1]
        return ret

    # Never end in slash
    def real_path(self, partial):
        return self.join(self.root, partial)

    # Never end in slash
    def fake_path(self, partial):
        return self.join(self.fake_root, partial)

    ########################################
    #           Shadow Functions           #
    ########################################

    # Add something to shadow (the fake paths to be used)
    def add_to_shadow(self, partial):
        self.shadow.add(partial)
        with open(self.shadow_file, 'a') as f:
            f.write(partial + '\n')

    # Determine if the real or fake paths should be used
    def test_use_fake(self, partial):
        if partial in self.shadow:
            return True
        elif partial == '/':
            return False
        else:
            return self.test_use_fake(os.path.dirname(partial))

    ########################################
    #       Path Selection Functions       #
    ########################################

    # Used for copytree to ignore already fake sub-items
    def ignore_fake(self, d, children):
        assert d.startswith(self.root), 'sanity check'
        prepend = d[len(self.root):]
        return [ i for i in children if self.test_use_fake(self.join(prepend, i)) ]

    # Returns path to use following these rules
    # force_fake will copy over real files if needed
    # Note: ancestors are not promised to have the proper permissions
    def path(self, partial, *, force_fake):
        use_fake = self.test_use_fake(partial)
        if use_fake is False and force_fake is True:
            path = self.fake_path(partial)
            Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
            real_path = self.real_path(partial)
            if os.path.exists(real_path):
                if os.path.isdir(real_path):
                    shutil.copytree(real_path, path, ignore=self.ignore_fake, dirs_exist_ok=True)
                else:
                    shutil.copy2(real_path, path)
            self.add_to_shadow(partial)
            return path
        return self.fake_path(partial) if use_fake else self.real_path(partial)

    ########################################
    #             fd Functions             #
    ########################################

    # Add an OS fd to the fdmap, return the LayerFS fd
    def add_to_fd_map(self, path, fd, *open_args):
        fake_fd = 0
        while fake_fd in self.fd_map:
            fake_fd += 1
        self.fd_map[fake_fd] = self.fd_map_t(fd, path, open_args)
        return fake_fd

    # Translate a LayerFS fs to an OS fd
    # Will update the OS fd if needed
    def real_fd(self, fh, path):
        entry = self.fd_map[fh]
        if entry.path == path:
            return entry.fd
        os.close(entry.fd)
        fd = os.open(entry.path, *entry.open_args)
        self.fd_map[fh].fd = fd
        return fd

    ########################################
    #            Misc Functions            #
    ########################################

    @staticmethod
    def fassert(b, ec):
        if not b:
            raise FuseOSError(ec)

    # Return the directory entries of partial
    # Does not include '.' or '..'
    def ls_dir(self, partial):
        fake_path = self.fake_path(partial)
        path = self.path(partial, force_fake=False)
        if fake_path == path:
            return os.listdir(path)
        else:
            # Check for path validity
            self.fassert(os.path.exists(path), errno.ENOENT)
            self.fassert(os.path.isdir(path), errno.ENOTDIR)
            # Get both real and fake files
            real_partials = [ self.join(partial, i) for i in os.listdir(path) ]
            real_files = [ self.path(i, force_fake=False) for i in real_partials ]
            fake_files = [ self.fake_path(i) for i in self.shadow if os.path.dirname(i) == partial ]
            # Merge and return the ones that should exist
            ret = [ os.path.basename(i) for i in (real_files + fake_files) if os.path.exists(i) ]
            return list(set(ret))

    ######################################################################
    #                                                                    #
    #                         Filesystem Methods                         #
    #                                                                    #
    ######################################################################

    def access(self, partial, mode):
        path = self.path(partial, force_fake=False)
        self.fassert(os.access(path, mode), errno.EACCES)

    def chmod(self, partial, mode):
        path = self.path(partial, force_fake=True)
        os.chmod(path, mode)

    def chown(self, partial, uid, gid):
        partial = self.path(partial, force_fake=True)
        os.chown(path, uid, gid)

    def getattr(self, partial, fh=None):
        path = self.path(partial, force_fake=False)
        st = os.lstat(path)
        # TODO: adjust these
        return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                'st_mtime', 'st_uid', 'st_gid', 'st_mode', 'st_size', 'st_nlink'))

    def readdir(self, partial, fh):
        dirents = self.ls_dir(partial)
        for i in ([ '.', '..' ] + dirents):
            yield i

    def readlink(self, path):
        raise FuseOSError(errno.EMLINK)

    # TODO: parent permissions
    def mknod(self, partial, mode, dev):
        path = self.path(partial, force_fake=True)
        os.mknod(path, mode, dev)

    # TODO: parent permissions
    def rmdir(self, partial):
        path = self.path(partial, force_fake=True)
        os.rmdir(path)

    # TODO: parent permissions
    def mkdir(self, partial, mode):
        path = self.path(partial, force_fake=True)
        os.mkdir(path, mode)

    def statfs(self, partial):
        path = self.path(partial, force_fake=False)
        stv = os.statvfs(path)
        return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
            'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
            'f_frsize', 'f_namemax'))

    # TODO: parent permissions
    def unlink(self, partial):
        path = self.path(partial, force_fake=True)
        os.unlink(path)

    def symlink(self, name, target):
        raise FuseOSError(errno.EMLINK)

    # TODO: parent permissions x2
    def rename(self, partial_old, partial_new):
        old = self.path(partial_old, force_fake=True)
        new = self.path(partial_new, force_fake=True)
        os.rename(old, new)

    def link(self, target, name):
        raise FuseOSError(errno.EMLINK)

    # TODO: parent permissions
    def utimens(self, partial, times=None):
        path = self.path(partial, force_fake=True)
        os.utime(path, times)

    ######################################################################
    #                                                                    #
    #                            File Methods                            #
    #                                                                    #
    ######################################################################

    def open(self, partial, flags):
        req_write = [ os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_APPEND, os.O_TRUNC, os.O_EXCL ]
        write_access = any([ flags == (flags | i) for i in req_write ])
        path = self.path(partial, force_fake=write_access)
        fd = os.open(path, flags)
        return self.add_to_fd_map(path, fd)

    def create(self, partial, mode, fi=None):
        path = self.path(partial, force_fake=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, mode)
        return self.add_to_fd_map(path, fd)

    def read(self, partial, length, offset, fh):
        path = self.path(partial, force_fake=False)
        fd = self.real_fd(fh, path)
        return os.read(fd, length)

    def write(self, partial, buf, offset, fh):
        path = self.path(partial, force_fake=True)
        fd = self.real_fd(fh, path)
        os.lseek(fd, offset, os.SEEK_SET)
        return os.write(fd, buf)

    def truncate(self, partial, length, fh=None):
        path = self.path(partial, force_fake=True)
        with open(path, 'r+') as f:
            f.truncate(length)

    def flush(self, partial, fh):
        pass

    def release(self, partial, fh):
        fd = self.fd_map.pop(fh)
        os.close(fd.fd)

    def fsync(self, partial, fdatasync, fh):
        path = self.path(partial, force_fake=True)
        fd = self.real_fd(fh, path)
        os.fsync(fd)


def layerFS(src, layer_storage, dst, **kwargs):
    # Argument verification
    src = os.path.realpath(src)
    assert os.path.exists(src), src + ' does not exist'
    assert os.path.isdir(src), src + ' is not a directory'
    layer_storage = os.path.realpath(layer_storage)
    if os.path.exists(layer_storage):
        assert os.path.isdir(layer_storage), layer_storage + ' exists and is not a directory'
    # Install the FUSE
    FUSE(LayerFS(src, layer_storage), dst, foreground=True, **kwargs)

def parse_args(prog, *args):
    parser = argparse.ArgumentParser(prog=os.path.basename(prog))
    parser.add_argument('src')
    parser.add_argument('layer_storage')
    parser.add_argument('dst')
    parser.add_argument('--debug', action='store_true', default=False)
    return parser.parse_args(args)

def main(argv):
    ns = parse_args(*argv)
    return layerFS(**vars(ns))


# Don't run on import
if __name__ == '__main__':
    rv = main(sys.argv)
    if type(rv) is int:
        sys.exit(rv)
