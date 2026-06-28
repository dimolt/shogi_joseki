import os
import json
import argparse
import subprocess
from pathlib import Path

import dropbox
from dropbox.files import WriteMode

CHUNK_SIZE = 4 * 1024 * 1024

def load_token():
    token = os.environ.get("DROPBOX_ACCESS_TOKEN")
    if not token:
        raise SystemExit("DROPBOX_ACCESS_TOKEN is not set")
    return token

def dbx_client():
    return dropbox.Dropbox(load_token())

def git_root():
    p = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise SystemExit(p.stderr.strip() or "Not inside a git repository")
    return Path(p.stdout.strip())

def changed_files(ref):
    p = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", ref],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise SystemExit(p.stderr.strip() or "git diff failed")
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]

def should_sync(path: Path):
    if not path.is_file():
        return False
    if ".git" in path.parts:
        return False
    return True

def remote_path(local_root: Path, file_path: Path, dropbox_root: str):
    rel = file_path.relative_to(local_root).as_posix()
    root = dropbox_root.strip("/").strip()
    return f"/{root}/{rel}" if root else f"/{rel}"

def upload_file(dbx, local_root: Path, file_path: Path, dropbox_root: str):
    rp = remote_path(local_root, file_path, dropbox_root)
    size = file_path.stat().st_size

    with open(file_path, "rb") as f:
        if size <= CHUNK_SIZE:
            dbx.files_upload(
                f.read(),
                rp,
                mode=WriteMode.overwrite,
                mute=True,
            )
        else:
            session = dbx.files_upload_session_start(f.read(CHUNK_SIZE))
            cursor = dropbox.files.UploadSessionCursor(
                session_id=session.session_id,
                offset=f.tell(),
            )
            commit = dropbox.files.CommitInfo(
                path=rp,
                mode=WriteMode.overwrite,
                mute=True,
            )
            while f.tell() < size:
                remaining = size - f.tell()
                if remaining <= CHUNK_SIZE:
                    dbx.files_upload_session_finish(f.read(CHUNK_SIZE), cursor, commit)
                else:
                    dbx.files_upload_session_append_v2(f.read(CHUNK_SIZE), cursor)
                    cursor.offset = f.tell()

    return rp

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="HEAD~1..HEAD")
    ap.add_argument("--dropbox-root", default="grii-me")
    args = ap.parse_args()

    root = git_root()
    dbx = dbx_client()
    uploaded = []

    for name in changed_files(args.ref):
        fp = (root / name).resolve()
        if should_sync(fp):
            uploaded.append(upload_file(dbx, root, fp, args.dropbox_root))

    print(json.dumps({"uploaded": uploaded}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()