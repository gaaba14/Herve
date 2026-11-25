import asyncio
import socket
from datetime import datetime, timezone

from herve.config import AlarmeConf
from herve.sources.ajax_sia import AjaxSIA
from tests.conftest import PARIS


def _crc(msg: str) -> str:
    crc = 0
    for lettre in msg.encode():
        t = lettre
        for _ in range(8):
            t ^= crc & 1
            crc >>= 1
            if t & 1:
                crc ^= 0xA001
            t >>= 1
    return f"{crc:04X}"


def message_sia(compte: str, code: str, zone: str = "1", seq: str = "0001") -> bytes:
    horo = datetime.now(timezone.utc).strftime("_%H:%M:%S,%m-%d-%Y")
    contenu = f'"SIA-DCS"{seq}L0#{compte}[#{compte}|Nri{zone}/{code}501]{horo}'
    return f"\n{_crc(contenu)}{len(contenu):04X}{contenu}\r".encode()


async def test_codes_et_persistance(tmp_path):
    a = AjaxSIA(AlarmeConf(source="ajax_sia"), tmp_path, PARIS)
    recus = []

    async def ecouteur(ev):
        recus.append(ev)

    a.ecouter(ecouteur)
    assert a.etat == "unknown"
    await a.recevoir("CL")
    assert a.etat == "armed_away"
    assert await a.recevoir("RP") is None  # test périodique : silencieux
    ev = await a.recevoir("BA", zone="3")
    assert a.etat == "triggered" and ev.gravite == "urgence" and ev.zone == "3"
    await a.recevoir("OP")
    assert [e.code for e in recus] == ["CL", "BA", "OP"]

    b = AjaxSIA(AlarmeConf(source="ajax_sia"), tmp_path, PARIS)  # redémarrage
    assert b.etat == "disarmed"
    assert [e.code for e in b.historique()] == ["OP", "BA", "CL"]
    assert b.derniere_nouvelle is not None


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_reception_sia_reelle(tmp_path):
    """Une « centrale » envoie un vrai message SIA DC-09 au serveur d'Hervé."""
    port = _port_libre()
    a = AjaxSIA(AlarmeConf(source="ajax_sia", port=port, compte="AAA"), tmp_path, PARIS)
    recus = asyncio.Queue()
    a.ecouter(recus.put)
    await a.demarrer()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(message_sia("AAA", "BA", zone="2"))
        await writer.drain()
        accuse = await asyncio.wait_for(reader.read(200), 5)
        assert b"ACK" in accuse
        ev = await asyncio.wait_for(recus.get(), 5)
        assert ev.code == "BA" and ev.zone == "2" and a.etat == "triggered"
        writer.close()
    finally:
        await a.fermer()
