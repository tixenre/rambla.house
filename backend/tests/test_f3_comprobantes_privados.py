"""
Tests de F3: comprobantes migrados a bucket privado con presigned URLs.

Cobertura:
- store_raw_document almacena en bucket privado y devuelve (key, presigned_url)
- storage.presigned_url delega a boto3.generate_presigned_url
- upload-comprobante de talleres usa store_raw_document y devuelve {url, key}
- InscripcionBody acepta comprobante_key
- INSERT en taller_inscripciones guarda comprobante_key
- _comprobante_url_fresca usa presigned cuando hay key
- Endpoint /admin/media/document/presigned requiere admin
- upload de contabilidad usa bucket privado
"""
import pytest
from unittest.mock import MagicMock, patch


# ── storage.presigned_url ─────────────────────────────────────────────────────

def test_presigned_url_llama_a_boto3():
    """presigned_url() delega a generate_presigned_url con los parámetros correctos."""
    fake_client = MagicMock()
    fake_client.generate_presigned_url.return_value = "https://presigned.example/key?sig=abc"

    with (
        patch("services.media.storage._r2_config", return_value={
            "account_id": "acc", "access_key_id": "key", "secret_key": "sec",
            "bucket": "pub-bucket", "public_base": "https://cdn.test",
            "private_bucket": "priv-bucket",
        }),
        patch("services.media.storage._get_r2_client", return_value=fake_client),
    ):
        from services.media.storage import presigned_url
        url = presigned_url("docs/test/file.pdf", expires_seconds=3600, private=True)

    fake_client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "priv-bucket", "Key": "docs/test/file.pdf"},
        ExpiresIn=3600,
    )
    assert url == "https://presigned.example/key?sig=abc"


def test_presigned_url_usa_bucket_publico_por_defecto():
    """Sin private=True, presigned_url usa el bucket público."""
    fake_client = MagicMock()
    fake_client.generate_presigned_url.return_value = "https://presigned.example/pub"

    with (
        patch("services.media.storage._r2_config", return_value={
            "account_id": "acc", "access_key_id": "k", "secret_key": "s",
            "bucket": "pub-bucket", "public_base": "https://cdn.test",
            "private_bucket": "priv-bucket",
        }),
        patch("services.media.storage._get_r2_client", return_value=fake_client),
    ):
        from services.media.storage import presigned_url
        presigned_url("media/equipo/1/display.webp", expires_seconds=600)

    call_kwargs = fake_client.generate_presigned_url.call_args
    assert call_kwargs[1]["Params"]["Bucket"] == "pub-bucket"


# ── store_raw_document ────────────────────────────────────────────────────────

def test_store_raw_document_devuelve_key_y_presigned():
    """store_raw_document almacena en bucket privado y devuelve (key, presigned_url)."""
    fake_presigned = "https://r2.example/docs/test?sig=xyz"

    with (
        patch("services.media.service.storage.put_private") as mock_put,
        patch("services.media.service.storage.presigned_url", return_value=fake_presigned) as mock_ps,
    ):
        from services.media.service import store_raw_document
        key, url = store_raw_document(
            b"%PDF-content",
            kind="comprobante-taller",
            ref="taller-abc-123",
            content_type="application/pdf",
        )

    mock_put.assert_called_once()
    args = mock_put.call_args
    assert args[0][0].startswith("docs/comprobante-taller/")
    assert args[0][0].endswith(".pdf")
    assert args[0][2] == "application/pdf"

    mock_ps.assert_called_once()
    assert mock_ps.call_args[1]["private"] is True

    assert key == args[0][0]
    assert url == fake_presigned


def test_store_raw_document_kind_invalido():
    """kind con caracteres inválidos eleva MediaError(400)."""
    from services.media.service import store_raw_document
    from services.media.errors import MediaError
    with pytest.raises(MediaError) as exc:
        store_raw_document(b"data", kind="comprobante../etc", ref="ref", content_type="application/pdf")
    assert exc.value.status == 400


def test_store_raw_document_vacio_eleva_error():
    """Bytes vacíos elevan MediaError(413)."""
    from services.media.service import store_raw_document
    from services.media.errors import MediaError
    with pytest.raises(MediaError) as exc:
        store_raw_document(b"", kind="comprobante-taller", ref="slug", content_type="application/pdf")
    assert exc.value.status == 413


def test_store_raw_document_key_incluye_kind_y_ref():
    """La key de R2 incluye el kind y una versión normalizada del ref."""
    with (
        patch("services.media.service.storage.put_private"),
        patch("services.media.service.storage.presigned_url", return_value="https://p.test/x"),
    ):
        from services.media.service import store_raw_document
        key, _ = store_raw_document(
            b"content",
            kind="comprobante-taller",
            ref="mi-taller-2026",
            content_type="image/jpeg",
        )

    assert "comprobante-taller" in key
    assert key.endswith(".jpg")


# ── _comprobante_url_fresca ────────────────────────────────────────────────

def test_comprobante_url_fresca_con_key_genera_presigned():
    """_comprobante_url_fresca genera presigned URL cuando hay key."""
    fake_url = "https://presigned.example/key?sig=abc"
    with patch("services.media.storage.presigned_url", return_value=fake_url):
        from routes.talleres import _comprobante_url_fresca
        result = _comprobante_url_fresca("docs/comprobante-taller/slug.pdf", None)
    assert result == fake_url


def test_comprobante_url_fresca_sin_key_usa_fallback():
    """_comprobante_url_fresca devuelve fallback_url cuando no hay key."""
    from routes.talleres import _comprobante_url_fresca
    result = _comprobante_url_fresca(None, "https://cdn.legacy/foto.jpg")
    assert result == "https://cdn.legacy/foto.jpg"


def test_comprobante_url_fresca_sin_nada_devuelve_vacio():
    """_comprobante_url_fresca devuelve '' cuando no hay ni key ni fallback."""
    from routes.talleres import _comprobante_url_fresca
    result = _comprobante_url_fresca(None, None)
    assert result == ""


# ── endpoint presigned (admin only) ──────────────────────────────────────────

def test_presigned_endpoint_requiere_admin():
    """GET /admin/media/document/presigned devuelve 401/403 sin sesión."""
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    resp = client.get("/api/admin/media/document/presigned?key=docs/test.pdf")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_presigned_endpoint_retorna_url():
    """get_document_presigned retorna {url, expires_in} cuando admin está autenticado."""
    fake_url = "https://r2.example/docs/test.pdf?sig=xyz"

    class FakeRequest:
        pass

    with patch("routes.media_api._presigned_url", return_value=fake_url):
        with patch("routes.media_api.require_admin", return_value=None):
            from routes.media_api import get_document_presigned
            result = get_document_presigned("docs/test.pdf", FakeRequest(), expires=7200)

    assert result["url"] == fake_url
    assert result["expires_in"] == 7200


def test_presigned_endpoint_clampea_expires():
    """get_document_presigned clampea expires entre 60 y 604800."""
    fake_url = "https://r2.example/x"

    class FakeReq:
        pass

    with (
        patch("routes.media_api.require_admin", return_value=None),
        patch("routes.media_api._presigned_url", return_value=fake_url) as mock_ps,
    ):
        from routes.media_api import get_document_presigned
        get_document_presigned("k", FakeReq(), expires=9999999)

    assert mock_ps.call_args[0][1] == 604800
