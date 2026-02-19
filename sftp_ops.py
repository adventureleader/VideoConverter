"""
SFTP Operations Module for Video Converter Daemon

Provides SFTPConnection class and helper functions for remote file operations
via SSH/SFTP using paramiko. Used when remote mode is enabled in config.

Security notes:
- SSH key auth only (no passwords)
- All remote paths validated against allowed directories
- No ssh.exec_command() — pure SFTP operations only
- Uploads use atomic temp-then-rename pattern
- Thread-safe via threading.Lock
"""

import logging
import posixpath
import threading
import time
from typing import List, Optional, Tuple

import paramiko

logger = logging.getLogger('VideoConverter.sftp')


class SFTPConnectionError(Exception):
    """Raised when SFTP connection fails."""
    pass


class SFTPOperationError(Exception):
    """Raised when an SFTP operation fails."""
    pass


def validate_remote_path(path: str, allowed_dirs: List[str]) -> bool:
    """Validate that a remote path is within allowed directories.

    Prevents directory traversal attacks via '..' components.

    Args:
        path: Remote POSIX path to validate.
        allowed_dirs: List of allowed remote directory prefixes.

    Returns:
        True if the path is within an allowed directory, False otherwise.
    """
    normalized = posixpath.normpath(path)

    # Reject paths with '..' after normalization
    if '..' in normalized.split('/'):
        return False

    # Must be absolute
    if not posixpath.isabs(normalized):
        return False

    for allowed_dir in allowed_dirs:
        allowed_normalized = posixpath.normpath(allowed_dir)
        # Check that normalized path starts with the allowed directory
        if normalized == allowed_normalized or normalized.startswith(allowed_normalized + '/'):
            return True

    return False


class SFTPConnection:
    """Thread-safe SSH/SFTP connection manager.

    Supports context manager protocol and automatic reconnection.

    Args:
        host: Remote hostname or IP.
        user: SSH username.
        port: SSH port (default 22).
        key_file: Path to SSH private key file (optional, uses agent if not set).
        connect_timeout: SSH connection timeout in seconds.
        logger: Logger instance.
    """

    def __init__(
        self,
        host: str,
        user: str,
        port: int = 22,
        key_file: Optional[str] = None,
        connect_timeout: int = 30,
        custom_logger: Optional[logging.Logger] = None,
    ):
        self.host = host
        self.user = user
        self.port = port
        self.key_file = key_file
        self.connect_timeout = connect_timeout
        self.logger = custom_logger or logger

        self._ssh: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._lock = threading.Lock()

    def connect(self):
        """Establish SSH and SFTP connections.

        Raises:
            SFTPConnectionError: If connection fails.
        """
        with self._lock:
            self._connect_locked()

    def _connect_locked(self):
        """Internal connect (must be called with _lock held)."""
        self.logger.info("Connecting to %s@%s:%d", self.user, self.host, self.port)
        try:
            self._ssh = paramiko.SSHClient()
            self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                'hostname': self.host,
                'port': self.port,
                'username': self.user,
                'timeout': self.connect_timeout,
                'allow_agent': True,
                'look_for_keys': True,
            }

            if self.key_file:
                connect_kwargs['key_filename'] = self.key_file

            self._ssh.connect(**connect_kwargs)
            self._sftp = self._ssh.open_sftp()
            self.logger.info("Connected to %s@%s:%d", self.user, self.host, self.port)
        except Exception as e:
            self._cleanup_locked()
            raise SFTPConnectionError(
                f"Failed to connect to {self.user}@{self.host}:{self.port}: {e}"
            ) from e

    def disconnect(self):
        """Close SSH and SFTP connections."""
        with self._lock:
            self._cleanup_locked()

    def _cleanup_locked(self):
        """Internal cleanup (must be called with _lock held)."""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
            self._ssh = None

    def ensure_connected(self):
        """Ensure the SFTP connection is active, reconnecting once if needed.

        Raises:
            SFTPConnectionError: If reconnection fails.
        """
        with self._lock:
            if self._sftp is not None:
                try:
                    # Test connection with a lightweight operation
                    self._sftp.normalize('.')
                    return
                except Exception:
                    self.logger.warning("SFTP connection lost, reconnecting...")
                    self._cleanup_locked()

            # Attempt to reconnect
            self._connect_locked()

    @property
    def sftp(self) -> paramiko.SFTPClient:
        """Get the active SFTP client.

        Raises:
            SFTPConnectionError: If not connected.
        """
        if self._sftp is None:
            raise SFTPConnectionError("Not connected. Call connect() first.")
        return self._sftp

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


def sftp_list_videos(
    conn: SFTPConnection,
    remote_dirs: List[str],
    extensions: List[str],
    exclude_patterns: Optional[List[str]] = None,
) -> List[str]:
    """Recursively list video files on the remote host.

    Args:
        conn: Active SFTPConnection.
        remote_dirs: List of remote directories to scan.
        extensions: List of video file extensions to match (without dot).
        exclude_patterns: List of filename patterns to exclude.

    Returns:
        List of remote file paths.
    """
    import fnmatch

    conn.ensure_connected()
    exclude_patterns = exclude_patterns or []
    ext_set = {ext.lower() for ext in extensions}
    results = []

    def _walk_remote(sftp: paramiko.SFTPClient, directory: str):
        try:
            entries = sftp.listdir_attr(directory)
        except IOError as e:
            conn.logger.warning("Cannot list remote directory %s: %s", directory, e)
            return

        for entry in entries:
            remote_path = posixpath.join(directory, entry.filename)

            # Skip hidden files/dirs
            if entry.filename.startswith('.'):
                continue

            if _is_dir(entry):
                _walk_remote(sftp, remote_path)
            elif _is_regular(entry):
                # Check extension
                _, ext = posixpath.splitext(entry.filename)
                if ext and ext[1:].lower() in ext_set:
                    # Check exclude patterns
                    should_exclude = False
                    for pattern in exclude_patterns:
                        if fnmatch.fnmatch(entry.filename, pattern):
                            should_exclude = True
                            break
                        if fnmatch.fnmatch(remote_path, pattern):
                            should_exclude = True
                            break
                    if not should_exclude:
                        results.append(remote_path)

    for remote_dir in remote_dirs:
        conn.logger.debug("Scanning remote directory: %s", remote_dir)
        _walk_remote(conn.sftp, remote_dir)

    return results


def _is_dir(attr: paramiko.SFTPAttributes) -> bool:
    """Check if an SFTP entry is a directory."""
    import stat
    return stat.S_ISDIR(attr.st_mode) if attr.st_mode is not None else False


def _is_regular(attr: paramiko.SFTPAttributes) -> bool:
    """Check if an SFTP entry is a regular file."""
    import stat
    return stat.S_ISREG(attr.st_mode) if attr.st_mode is not None else False


def sftp_stat(conn: SFTPConnection, path: str) -> Tuple[int, float]:
    """Get remote file size and modification time.

    Args:
        conn: Active SFTPConnection.
        path: Remote file path.

    Returns:
        Tuple of (size_bytes, mtime_epoch).

    Raises:
        SFTPOperationError: If stat fails.
    """
    conn.ensure_connected()
    try:
        attr = conn.sftp.stat(path)
        size = attr.st_size if attr.st_size is not None else 0
        mtime = attr.st_mtime if attr.st_mtime is not None else 0.0
        return (size, mtime)
    except IOError as e:
        raise SFTPOperationError(f"Failed to stat {path}: {e}") from e


def sftp_download(
    conn: SFTPConnection,
    remote_path: str,
    local_path: str,
    timeout: Optional[int] = None,
) -> None:
    """Download a file from the remote host.

    Args:
        conn: Active SFTPConnection.
        remote_path: Remote file path.
        local_path: Local destination path.
        timeout: Transfer timeout in seconds (applied via channel timeout).

    Raises:
        SFTPOperationError: If download fails.
    """
    conn.ensure_connected()
    try:
        if timeout:
            conn.sftp.get_channel().settimeout(float(timeout))
        conn.sftp.get(remote_path, local_path)
    except IOError as e:
        raise SFTPOperationError(f"Failed to download {remote_path}: {e}") from e
    except OSError as e:
        raise SFTPOperationError(f"Local write error downloading {remote_path}: {e}") from e
    finally:
        if timeout:
            try:
                conn.sftp.get_channel().settimeout(None)
            except Exception:
                pass


def sftp_upload(
    conn: SFTPConnection,
    local_path: str,
    remote_path: str,
    timeout: Optional[int] = None,
) -> None:
    """Upload a file to the remote host using atomic temp-then-rename.

    Uploads to <remote_path>.tmp first, then renames to prevent partial files.

    Args:
        conn: Active SFTPConnection.
        local_path: Local source file path.
        remote_path: Remote destination path.
        timeout: Transfer timeout in seconds.

    Raises:
        SFTPOperationError: If upload fails.
    """
    conn.ensure_connected()
    tmp_remote = remote_path + '.tmp'
    try:
        if timeout:
            conn.sftp.get_channel().settimeout(float(timeout))
        conn.sftp.put(local_path, tmp_remote)
        conn.sftp.rename(tmp_remote, remote_path)
    except IOError as e:
        # Try to clean up the temp file
        try:
            conn.sftp.remove(tmp_remote)
        except Exception:
            pass
        raise SFTPOperationError(f"Failed to upload to {remote_path}: {e}") from e
    except OSError as e:
        try:
            conn.sftp.remove(tmp_remote)
        except Exception:
            pass
        raise SFTPOperationError(f"Local read error uploading to {remote_path}: {e}") from e
    finally:
        if timeout:
            try:
                conn.sftp.get_channel().settimeout(None)
            except Exception:
                pass


def sftp_delete(conn: SFTPConnection, path: str) -> None:
    """Delete a file on the remote host.

    Args:
        conn: Active SFTPConnection.
        path: Remote file path to delete.

    Raises:
        SFTPOperationError: If delete fails.
    """
    conn.ensure_connected()
    try:
        conn.sftp.remove(path)
    except IOError as e:
        raise SFTPOperationError(f"Failed to delete {path}: {e}") from e


def sftp_utime(conn: SFTPConnection, path: str, times: Tuple[float, float]) -> None:
    """Set access and modification times on a remote file.

    Args:
        conn: Active SFTPConnection.
        path: Remote file path.
        times: Tuple of (atime, mtime) as epoch floats.

    Raises:
        SFTPOperationError: If utime fails.
    """
    conn.ensure_connected()
    try:
        conn.sftp.utime(path, times)
    except IOError as e:
        raise SFTPOperationError(f"Failed to set times on {path}: {e}") from e


def sftp_exists(conn: SFTPConnection, path: str) -> bool:
    """Check if a remote path exists.

    Args:
        conn: Active SFTPConnection.
        path: Remote file path.

    Returns:
        True if the path exists, False otherwise.
    """
    conn.ensure_connected()
    try:
        conn.sftp.stat(path)
        return True
    except IOError:
        return False
