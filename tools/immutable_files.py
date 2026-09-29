"""Space-efficient copies for sealed build inputs on the same filesystem."""
import errno
import os
import shutil


def link_or_copy(source, target):
    try:
        os.link(source, target)
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EACCES, errno.EMLINK):
            raise
        shutil.copy2(source, target)
    return target


def deduplicate_tree(tree, verified_sources):
    """Link equal sealed bytes after rendering; never rewrite a source inode."""
    from tools.global_remote_sync import file_hash
    canonical, inodes = {}, set()
    for source, sha in verified_sources:
        stat = source.stat()
        canonical[(stat.st_size, sha)] = source
        inodes.add((stat.st_dev, stat.st_ino))
    sizes = {size for size, _ in canonical}
    saved = 0
    for target in tree.rglob('*'):
        if not target.is_file() or target.is_symlink(): continue
        stat = target.stat()
        if (stat.st_dev, stat.st_ino) in inodes or stat.st_size not in sizes: continue
        sha = file_hash(target)
        source = canonical.get((stat.st_size, sha))
        if source is None:
            canonical[(stat.st_size, sha)] = target
            inodes.add((stat.st_dev, stat.st_ino))
            continue
        if source.stat().st_dev != stat.st_dev: continue
        if file_hash(source) != sha: raise ValueError('sealed deduplication source changed')
        temporary = target.with_name('.' + target.name + '.dedup')
        os.link(source, temporary)
        os.replace(temporary, target)
        saved += stat.st_size
    return saved
