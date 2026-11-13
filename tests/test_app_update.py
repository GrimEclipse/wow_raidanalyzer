import subprocess

from analyzer_core.app_update import latest_tag, local_update_blocker, remote_main, update_status, version_tuple
from analyzer_core.app_update_helper import apply_commit


def run(directory, *args):
    return subprocess.run(['git', *args], cwd=directory, check=True, capture_output=True,
                          text=True, encoding='utf-8', errors='replace').stdout.strip()


def test_version_tags_ignore_prereleases_and_annotated_dereference():
    refs = ('abc refs/tags/v2.0.0\nabc refs/tags/v2.0.0^{}\n'
            'def refs/tags/v2.1.0-rc1\nghi refs/tags/v1.9.9\n')
    assert version_tuple('2.0.0') == (2, 0, 0)
    assert latest_tag(refs) == 'v2.0.0'
    assert remote_main('a' * 40 + ' refs/heads/main\n') == 'a' * 40


def test_same_version_commit_update_preserves_local_edits(tmp_path):
    source, remote, client = (tmp_path / name for name in ('source', 'remote.git', 'client'))
    source.mkdir()
    run(source, 'init', '-b', 'main')
    run(source, 'config', 'user.email', 'test@example.com')
    run(source, 'config', 'user.name', 'Test')
    (source / 'app.txt').write_text('v2.0.0', encoding='utf-8')
    run(source, 'add', 'app.txt')
    run(source, 'commit', '-m', 'Initial')
    run(source, 'tag', 'v2.0.2')
    run(tmp_path, 'init', '--bare', str(remote))
    run(source, 'remote', 'add', 'origin', str(remote))
    run(source, 'push', 'origin', 'main', '--tags')
    run(tmp_path, 'clone', '-b', 'main', str(remote), str(client))
    (source / 'app.txt').write_text('same-version update', encoding='utf-8')
    run(source, 'commit', '-am', 'Update')
    target = run(source, 'rev-parse', 'HEAD')
    run(source, 'push', 'origin', 'main')
    status = update_status(client, force=True)
    assert status['currentVersion'] == status['latestVersion'] == '2.0.2'
    assert status['latestCommit'] == target
    assert status['updateAvailable'] and status['canApply']
    assert local_update_blocker(client) is None
    (client / 'local.txt').write_text('keep', encoding='utf-8')
    assert '未提交' in local_update_blocker(client)
    try:
        apply_commit(client, target)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Dirty worktree must block the update')
    assert (client / 'app.txt').read_text(encoding='utf-8') == 'v2.0.0'
    (client / 'local.txt').unlink()
    apply_commit(client, target)
    assert (client / 'app.txt').read_text(encoding='utf-8') == 'same-version update'
    assert not update_status(client, force=True)['updateAvailable']
