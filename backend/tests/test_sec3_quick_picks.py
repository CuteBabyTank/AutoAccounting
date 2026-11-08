"""Source wiring contract for browser-only personal storage (no frontend runtime in backend image)."""
from pathlib import Path

import pytest


def test_quick_picks_use_authenticated_identity_and_remount_on_change():
    root = Path(__file__).resolve().parents[2] / 'frontend'
    if not root.exists():
        pytest.skip('frontend tree is not mounted in this backend container')
    component = (root / 'src/components/QuickPicks.tsx').read_text()
    storage = (root / 'src/lib/personal-storage.ts').read_text()
    homepage = (root / 'public/app.js').read_text()
    assert 'useAuth()' in component
    assert 'quickPickKind(user.id, props.kind)' in component
    assert 'key={kind}' in component  # drop rendered A state synchronously on an identity change
    assert 'removeItem(`aa:quick:${kind}`)' in storage  # discard unowned legacy entries
    assert 'return `${userId}:${kind}`' in storage
    assert '"aa:quick:"' in storage and 'key.startsWith("aa:quick:")' in homepage
