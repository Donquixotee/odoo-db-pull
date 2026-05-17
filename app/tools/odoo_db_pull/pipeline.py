import asyncio
import os
import tempfile
from typing import Optional, AsyncGenerator
from .ssh_utils import SshClient
from .target_db import TargetDb, LocalDbTarget


class PullPipeline:
    """
    Orchestrates the full DB pull workflow.
    Yields SSE-formatted event strings for real-time UI updates.
    """

    def __init__(self, source_ssh: SshClient, db_target: TargetDb, target_ssh: Optional[SshClient] = None):
        self._source_ssh = source_ssh
        self._db_target = db_target
        self._target_ssh = target_ssh

    def _event(self, message: str, status: str = "info") -> str:
        return f"data: {status}|{message}\n\n"

    async def run(  # noqa: C901
        self,
        db_container: str,
        source_db: str,
        target_mode: str,
        target_db_name: str,
        rename_existing_to: Optional[str],
        db_user: str = "odoo",
    ) -> AsyncGenerator[str, None]:

        dump_remote = f"/tmp/{source_db}_pull.dump"
        dump_local = os.path.join(tempfile.gettempdir(), f"{source_db}_pull.dump")
        dump_target_remote = f"/tmp/{target_db_name}_pull_target.dump"

        # Step 1 — Connect
        yield self._event("Connecting to Source SSH server…")
        try:
            await asyncio.to_thread(self._source_ssh.connect)
        except Exception as e:
            yield self._event(f"Source SSH connection failed: {e}", "error")
            return

        if self._target_ssh and self._target_ssh is not self._source_ssh:
            yield self._event("Connecting to Target SSH server…")
            try:
                await asyncio.to_thread(self._target_ssh.connect)
            except Exception as e:
                yield self._event(f"Target SSH connection failed: {e}", "error")
                return

        try:
            # Step 2 — pg_dump inside container
            yield self._event(f"Running pg_dump for '{source_db}' on remote server…")
            try:
                await asyncio.to_thread(
                    self._source_ssh.exec,
                    f"docker exec {db_container} pg_dump -U {db_user} -Fc "
                    f"{source_db} -f {dump_remote}"
                )
            except Exception as e:
                yield self._event(f"pg_dump failed: {e}", "error")
                return

            # Step 3 — copy dump out of container
            yield self._event("Copying dump out of container…")
            try:
                await asyncio.to_thread(
                    self._source_ssh.exec,
                    f"docker cp {db_container}:{dump_remote} {dump_remote}"
                )
            except Exception as e:
                yield self._event(f"docker cp failed: {e}", "error")
                return

            # Step 4 — get dump size + download / transfer
            try:
                size_bytes = await asyncio.to_thread(self._source_ssh.file_size, dump_remote)
                size_mb = round(size_bytes / 1024 / 1024, 1)
            except Exception:
                size_mb = "?"

            if target_mode == "same_server":
                # Already on the server at dump_remote
                dump_final_path = dump_remote
            else:
                yield self._event(f"Downloading dump ({size_mb} MB)…")
                try:
                    await asyncio.to_thread(self._source_ssh.download, dump_remote, dump_local)
                except Exception as e:
                    yield self._event(f"Download failed: {e}", "error")
                    return

                if target_mode == "remote":
                    yield self._event(f"Uploading dump ({size_mb} MB) to Target Server…")
                    try:
                        await asyncio.to_thread(self._target_ssh.upload, dump_local, dump_target_remote)
                        dump_final_path = dump_target_remote
                    except Exception as e:
                        yield self._event(f"Upload to Target failed: {e}", "error")
                        return
                    finally:
                        if os.path.exists(dump_local):
                            os.remove(dump_local)
                else:
                    # target_mode == "local"
                    dump_final_path = dump_local

            # Step 5 — rename existing DB
            if rename_existing_to:
                exists = await asyncio.to_thread(self._db_target.exists, target_db_name)
                if exists:
                    yield self._event(f"Renaming '{target_db_name}' → '{rename_existing_to}'…")
                    try:
                        await asyncio.to_thread(
                            self._db_target.rename, target_db_name, rename_existing_to
                        )
                    except Exception as e:
                        yield self._event(f"Rename failed: {e}", "error")
                        return

            # Step 6 — create fresh target DB and restore
            yield self._event(f"Creating target database '{target_db_name}'…")
            try:
                await asyncio.to_thread(self._db_target.drop, target_db_name)
                await asyncio.to_thread(self._db_target.create, target_db_name)
            except Exception as e:
                yield self._event(f"Database creation failed: {e}", "error")
                return

            yield self._event("Restoring dump (pg_restore)…")
            try:
                await asyncio.to_thread(self._db_target.restore, target_db_name, dump_final_path)
            except Exception as e:
                yield self._event(f"Restore failed: {e}", "error")
                return

            # Cleanup dumps
            if target_mode == "remote":
                try:
                    await asyncio.to_thread(self._target_ssh.exec, f"rm -f {dump_target_remote}")
                except Exception:
                    pass
            elif target_mode == "local":
                try:
                    if os.path.exists(dump_local):
                        os.remove(dump_local)
                except Exception:
                    pass

            try:
                await asyncio.to_thread(self._source_ssh.exec, f"rm -f {dump_remote}")
            except Exception:
                pass

            yield self._event("✓ Done — database pulled successfully!", "success")

        finally:
            await asyncio.to_thread(self._source_ssh.disconnect)
            if self._target_ssh and self._target_ssh is not self._source_ssh:
                await asyncio.to_thread(self._target_ssh.disconnect)
