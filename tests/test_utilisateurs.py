import pytest

from herve.utilisateurs import ADMIN, INVITE, MEMBRE, Registre


def test_cycle_de_vie(tmp_path):
    f = tmp_path / "u.json"
    r = Registre(f, [1])
    assert r.autorise(1, ADMIN)
    assert not r.autorise(2)
    assert r.demander(2, "Alice") and not r.demander(2, "Alice")
    u = r.autoriser(2, INVITE)
    assert u.nom == "Alice" and r.autorise(2, INVITE) and not r.autorise(2, MEMBRE)
    assert 2 not in r.demandes

    r2 = Registre(f, [1])  # rechargement depuis le disque
    assert r2.get(2).role == INVITE
    r2.notifications(2, False)
    assert [u.id for u in r2.a_notifier()] == [1]

    assert r2.revoquer(2).nom == "Alice"
    with pytest.raises(PermissionError):
        r2.revoquer(1)


def test_role_inconnu(tmp_path):
    with pytest.raises(ValueError):
        Registre(tmp_path / "u.json", []).autoriser(5, "roi")
