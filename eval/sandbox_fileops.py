"""Job-local filesystem tools: regular files only, no shell or memory writes.

Directory-fd walks reject symlink parents and '..', anchoring operations to
the trusted scenario directories rather than re-resolving caller paths.
"""
from __future__ import annotations

from contextlib import contextmanager
import argparse
import json
import os
from pathlib import Path
import stat
import time
import uuid


class FileOps:
    def __init__(self, root: Path):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('scenario root must be a directory')

    @contextmanager
    def _parent(self, path: str):
        target = Path(path)
        if target.is_absolute():
            try:
                target = target.relative_to(self.root)
            except ValueError as exc:
                raise ValueError('file must be inside this scenario working directory') from exc
        if not target.parts or '..' in target.parts:
            raise ValueError('expected a file path without parent traversal')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.root, flags)
        try:
            for part in target.parts[:-1]:
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd, target.name
        finally:
            os.close(fd)

    @staticmethod
    def _regular(fd: int, name: str):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('only regular files are allowed; no directories or symlinks')
        return info

    def rename_file(self, source: str, destination: str) -> dict:
        """Rename a regular file within this scenario; never overwrite a destination."""
        with self._parent(source) as (src_fd, src), self._parent(destination) as (dst_fd, dst):
            before = self._regular(src_fd, src)
            # link() fails atomically if the destination exists. Unlike rename(),
            # it cannot silently overwrite another report or follow a leaf symlink.
            os.link(src, dst, src_dir_fd=src_fd, dst_dir_fd=dst_fd, follow_symlinks=False)
            try:
                linked = self._regular(dst_fd, dst)
                current = self._regular(src_fd, src)
                if (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino) or (
                        current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
                    raise ValueError('source changed during rename')
                os.unlink(src, dir_fd=src_fd)
            except Exception:
                os.unlink(dst, dir_fd=dst_fd)
                raise
        return {'renamed_from': source, 'renamed_to': destination}

    def delete_file(self, path: str) -> dict:
        """Delete one regular file in this scenario, never a directory or symlink."""
        with self._parent(path) as (fd, name):
            self._regular(fd, name)
            os.unlink(name, dir_fd=fd)
        return {'deleted': path}


def call_audited(audit: Path, root: Path, tool: str, arguments: dict, operation):
    event = {'call_id': uuid.uuid4().hex, 'root': str(root), 'tool': tool,
             'arguments': arguments}
    # Open and flush the attempt before mutating. An unavailable audit sink
    # therefore refuses the operation, rather than silently losing its trace.
    with audit.open('a') as log:
        def emit(status, **details):
            log.write(json.dumps({**event, 'time': time.time(), 'status': status,
                                  **details}) + '\n')
            log.flush()

        emit('started')
        try:
            result = operation()
        except Exception as exc:
            emit('error', error=f'{type(exc).__name__}: {exc}')
            raise
        emit('ok', result=result)
        return result


def main():
    from mcp.server import MCPServer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    ops = FileOps(args.root)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    server = MCPServer('sandbox-files', instructions=(
        'Rename and delete regular files in your own working directory only. '
        'No shell, directory operations, overwrite or memory writes.'))

    @server.tool()
    def rename_file(source: str, destination: str) -> dict:
        """Rename a file inside your working directory, preserving its contents.

        Paths may be relative or absolute. Destination must not already exist.
        No directories, symlinks or paths outside this scenario are allowed.
        """
        return call_audited(args.audit, ops.root, 'rename_file',
                            {'source': source, 'destination': destination},
                            lambda: ops.rename_file(source, destination))

    @server.tool()
    def delete_file(path: str) -> dict:
        """Delete one regular file in your working directory, e.g. a stale duplicate.

        No directories, symlinks or paths outside this scenario are allowed.
        """
        return call_audited(args.audit, ops.root, 'delete_file', {'path': path},
                            lambda: ops.delete_file(path))

    server.run(transport='stdio')


if __name__ == '__main__':
    main()
